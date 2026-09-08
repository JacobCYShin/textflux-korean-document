#!/usr/bin/env python3
"""Run a benchmark manifest inside a long-lived TextFlux container.

Loads the pipeline once, then iterates. Run it INSIDE the container.
Upstream resolves `resource/font/...` and `outputs_my/` relative to the working
directory, so each shard gets a private workspace holding a `resource` symlink
and its own `outputs_my`; that is what lets several shards share one container.

  for i in 0 1 2 3; do
    CUDA_VISIBLE_DEVICES=$i python run_resident.py ... --shard-index $i --shard-count 4 &
  done; wait
"""
from __future__ import annotations
import argparse, hashlib, json, os, re, shutil, sys, time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_DATASETS_OFFLINE", "1")

APP_ROOT = Path(os.environ.get("TEXTFLUX_APP_ROOT", "/opt/textflux/app"))
FONT = APP_ROOT / "resource/font/Arial-Unicode-Regular.ttf"
CASE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,79}$")


class Tee:
    def __init__(self, s, h): self.s, self.h = s, h
    def write(self, d): self.s.write(d); self.h.write(d); return len(d)
    def flush(self): self.s.flush(); self.h.flush()


def parse_manifest(path: Path) -> list[dict[str, Any]]:
    cases, seen = [], set()
    for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"): continue
        c = json.loads(line)
        miss = {"id","track","field_type","source_image","mask_image","text"} - set(c)
        if miss: raise ValueError(f"line {n}: missing keys: {', '.join(sorted(miss))}")
        if not CASE_ID_RE.fullmatch(str(c["id"])): raise ValueError(f"line {n}: invalid case id")
        if c["id"] in seen: raise ValueError(f"line {n}: duplicate case id: {c['id']}")
        if not isinstance(c["text"], str) or not c["text"].strip() or "\n" in c["text"]:
            raise ValueError(f"line {n}: text must be a non-empty single line")
        seen.add(c["id"]); cases.append(c)
    if not cases: raise ValueError("manifest contains no cases")
    return cases


def input_path(root: Path, rel: str, label: str) -> Path:
    c = Path(rel)
    if c.is_absolute() or ".." in c.parts: raise ValueError(f"{label}: must be relative to --input-root")
    r = root.resolve(); p = (r / c).resolve()
    try: p.relative_to(r)
    except ValueError as e: raise ValueError(f"{label}: resolves outside --input-root") from e
    if not p.is_file(): raise ValueError(f"{label}: file not found: {p}")
    return p


def sha256(p: Path) -> str:
    d = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): d.update(b)
    return d.hexdigest()


def verify_font() -> None:
    """A missing Hangul font is silent: the strip renders .notdef boxes."""
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
    if not FONT.is_file(): raise RuntimeError(f"runtime font missing: {FONT}")
    f = ImageFont.truetype(str(FONT), 96); seen = []
    for ch in "금융":
        im = Image.new("L", (256, 256), 0)
        ImageDraw.Draw(im).text((128, 128), ch, font=f, fill=255, anchor="mm")
        a = np.array(im)
        if not (a > 8).any(): raise RuntimeError(f"font has no glyph for {ch!r}: {FONT}")
        seen.append(a)
    if np.array_equal(seen[0], seen[1]):
        raise RuntimeError(f"font renders Hangul as identical .notdef boxes: {FONT}")


def replace_link(link: Path, target: Path) -> None:
    if link.is_symlink(): link.unlink()
    elif link.is_dir():
        if any(link.iterdir()): raise RuntimeError(f"{link} is a non-empty real directory")
        link.rmdir()
    elif link.exists(): link.unlink()
    link.symlink_to(target, target_is_directory=True)


def prepare_workspace(base: Path, idx: int) -> Path:
    ws = base / f"shard-{idx:02d}"; ws.mkdir(parents=True, exist_ok=True)
    replace_link(ws / "resource", APP_ROOT / "resource")
    if not (ws / "resource/font/Arial-Unicode-Regular.ttf").is_file():
        raise RuntimeError(f"font not reachable through workspace link: {ws}/resource")
    return ws


def build_pipeline(model_root: Path, cpu_offload: bool):
    import torch
    from diffusers import FluxFillPipeline, FluxTransformer2DModel
    flux, tf = model_root / "flux-fill-dev", model_root / "textflux"
    for req, what in ((flux/"model_index.json","FLUX model index"), (flux/"text_encoder_2","FLUX T5 encoder"),
                      (flux/"vae","FLUX VAE"), (tf/"config.json","TextFlux transformer config")):
        if not req.exists(): raise RuntimeError(f"Missing {what}: {req}")
    print(f"Loading TextFlux transformer from {tf} ...", flush=True)
    tr = FluxTransformer2DModel.from_pretrained(tf, torch_dtype=torch.bfloat16, local_files_only=True)
    print(f"Loading FLUX pipeline from {flux} ...", flush=True)
    pipe = FluxFillPipeline.from_pretrained(flux, transformer=tr, torch_dtype=torch.bfloat16, local_files_only=True)
    if cpu_offload: pipe.enable_model_cpu_offload()
    else: pipe.to("cuda"); pipe.transformer.to(torch.bfloat16)
    return pipe


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--input-root", type=Path, required=True)
    ap.add_argument("--bundle", type=Path, required=True)
    ap.add_argument("--suite", required=True)
    ap.add_argument("--model-root", type=Path)
    ap.add_argument("--checkpoint-id", default="unknown")
    ap.add_argument("--seeds", default="42")
    ap.add_argument("--steps", type=int, default=30)
    ap.add_argument("--guidance-scale", type=float, default=30.0)
    ap.add_argument("--shard-index", type=int, default=0)
    ap.add_argument("--shard-count", type=int, default=1)
    ap.add_argument("--shard-by", choices=("case", "run"), default="case",
                    help="case (default) keeps every seed of a case on one worker")
    ap.add_argument("--workspace", type=Path, default=Path("/tmp/textflux-workspaces"))
    ap.add_argument("--cpu-offload", action="store_true")
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,79}", a.suite): ap.error("--suite: lowercase, digits, hyphens")
    if a.steps < 1: ap.error("--steps must be positive")
    if a.guidance_scale <= 0: ap.error("--guidance-scale must be positive")
    if a.shard_count < 1: ap.error("--shard-count must be >= 1")
    if not 0 <= a.shard_index < a.shard_count: ap.error("--shard-index must satisfy 0 <= index < --shard-count")

    vis = os.environ.get("CUDA_VISIBLE_DEVICES")
    if a.shard_count > 1 and not vis:
        print("WARNING: --shard-count > 1 but CUDA_VISIBLE_DEVICES is unset; every shard "
              "would load onto the same GPU.", file=sys.stderr)

    bundle, root = a.bundle.resolve(), a.input_root.resolve()
    model_root = (a.model_root or (bundle / "payload")).resolve()
    try:
        seeds = [int(s) for s in a.seeds.split(",") if s.strip()]
        if not seeds: raise ValueError("--seeds must contain at least one integer")
        cases = parse_manifest(a.manifest)
        resolved = [(c, input_path(root, c["source_image"], f"{c['id']}.source_image"),
                        input_path(root, c["mask_image"], f"{c['id']}.mask_image")) for c in cases]
    except (OSError, ValueError) as e:
        print(f"ERROR: {e}", file=sys.stderr); return 1

    def runs_for(e):
        c, s, m = e
        return [(c, s, m, sd, bundle/"runs"/a.suite/c["id"]/f"seed-{sd:06d}") for sd in seeds]

    every = [r for e in resolved for r in runs_for(e)]
    mine = ([r for e in resolved[a.shard_index::a.shard_count] for r in runs_for(e)]
            if a.shard_by == "case" else every[a.shard_index::a.shard_count])
    planned = [x for x in mine if a.overwrite or not x[4].exists()]
    tag = f"shard {a.shard_index+1}/{a.shard_count}" if a.shard_count > 1 else "single worker"
    print(f"[{tag}] {len(planned)} planned, {len(mine)-len(planned)} skipped, {len(every)} total")
    for c, _, _, sd, _ in planned: print(f"  {c['id']:28s} seed={sd:<6d} text={c['text']!r}")
    if a.dry_run: print("DRY RUN: model not loaded"); return 0
    if not planned: print("Nothing to do."); return 0

    try:
        verify_font(); ws = prepare_workspace(a.workspace / a.suite, a.shard_index)
    except (OSError, RuntimeError) as e:
        print(f"ERROR: {e}", file=sys.stderr); return 1
    os.chdir(ws); sys.path.insert(0, str(APP_ROOT))
    out_link = ws / "outputs_my"

    try:
        import torch
        if not torch.cuda.is_available():
            print("ERROR: CUDA required; start the container with --gpus all", file=sys.stderr); return 1
        print(f"[{tag}] CUDA_VISIBLE_DEVICES={vis or 'all'} -> {torch.cuda.get_device_name(0)}")
        import run_inference as textflux
        t0 = time.time(); textflux.PIPE = build_pipeline(model_root, a.cpu_offload)
        print(f"[{tag}] pipeline ready in {time.time()-t0:.0f}s\n", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"ERROR: could not load the pipeline: {e}", file=sys.stderr); return 1

    fails = 0
    for i, (c, src, msk, sd, rd) in enumerate(planned, 1):
        label = f"[{tag} {i}/{len(planned)}] {c['id']} seed={sd}"
        try:
            if rd.exists() and a.overwrite: shutil.rmtree(rd)
            rd.mkdir(parents=True, exist_ok=False)
            wp = rd / "words_0001.txt"; wp.write_text(c["text"] + "\n", encoding="utf-8")
            (rd / "case.json").write_text(json.dumps({
                "case": c, "seed": sd, "source_image": str(src), "mask_image": str(msk),
                "checkpoint_id": a.checkpoint_id, "model_root": str(model_root), "font": str(FONT),
                "steps": a.steps, "guidance_scale": a.guidance_scale, "cuda_visible_devices": vis,
                "shard": f"{a.shard_index}/{a.shard_count}", "shard_by": a.shard_by,
                "network": "not-enforced", "provenance": "interactive-resident",
                "style_reference_consumed": False,
                "created_at_utc": datetime.now(timezone.utc).isoformat(),
            }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            replace_link(out_link, rd / "outputs_my"); (rd / "outputs_my").mkdir(parents=True, exist_ok=True)
            t1 = time.time()
            with (rd / "run.log").open("w", encoding="utf-8") as h:
                so = sys.stdout; sys.stdout = Tee(so, h)
                try:
                    print(f"{label}\ntext={c['text']!r} steps={a.steps} guidance={a.guidance_scale}")
                    res = textflux.process_normal_mode(str(src), str(msk), str(wp), a.steps, a.guidance_scale, sd)
                finally:
                    sys.stdout = so
            rp = rd / "result.png"; res.save(rp)
            (rd / "result.png.sha256").write_text(f"{sha256(rp)}  result.png\n", encoding="utf-8")
            print(f"{label} DONE in {time.time()-t1:.0f}s -> {rp}", flush=True)
        except Exception as e:  # noqa: BLE001 - one bad case must not end the sweep
            fails += 1; print(f"{label} FAILED: {e}", file=sys.stderr, flush=True)

    if out_link.is_symlink(): out_link.unlink()
    print(f"\n[{tag}] {len(planned)-fails} succeeded, {fails} failed")
    print(f"Results: {bundle/'runs'/a.suite}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())

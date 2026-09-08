#!/usr/bin/env python3
"""Validate the selected FLUX layout and emit a delivery manifest."""

import argparse
import hashlib
import json
from pathlib import Path


FLUX_COMPONENTS = (
    "scheduler",
    "text_encoder",
    "text_encoder_2",
    "tokenizer",
    "tokenizer_2",
    "transformer",
    "vae",
)
ROOT_DUPLICATES = ("flux1-fill-dev.safetensors", "ae.safetensors")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def describe_tree(root: Path, include_hashes: bool) -> dict:
    files = []
    for path in sorted(root.rglob("*")):
        # snapshot_download keeps resumability metadata below .cache. It is not
        # model payload and must neither affect hashes nor be baked into image.
        if path.is_file() and ".cache" not in path.relative_to(root).parts:
            item = {"path": path.relative_to(root).as_posix(), "bytes": path.stat().st_size}
            if include_hashes:
                item["sha256"] = sha256(path)
            files.append(item)
    return {"path": str(root), "file_count": len(files), "bytes": sum(f["bytes"] for f in files), "files": files}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle-root", type=Path, required=True)
    parser.add_argument("--only", choices=("all", "flux", "textflux"), default="all")
    parser.add_argument("--sha256", action="store_true", help="Hash every payload file; this is slow for model shards.")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    root = args.bundle_root.resolve()
    flux = root / "payload" / "flux-fill-dev"
    textflux = root / "payload" / "textflux"
    failures = []

    if args.only in ("all", "flux"):
        if not (flux / "model_index.json").is_file():
            failures.append("FLUX model_index.json is missing")
        for component in FLUX_COMPONENTS:
            if not (flux / component).is_dir():
                failures.append(f"FLUX component is missing: {component}/")
        for duplicate in ROOT_DUPLICATES:
            if (flux / duplicate).exists():
                failures.append(f"Excluded duplicate is present: {duplicate}")
    if args.only in ("all", "textflux"):
        if not (textflux / "config.json").is_file():
            failures.append("TextFlux transformer config.json is missing")
        if not list(textflux.glob("*.safetensors")):
            failures.append("TextFlux transformer checkpoint shards are missing")
    if failures:
        raise SystemExit("Payload validation failed:\n- " + "\n- ".join(failures))

    manifest = {"sources": {
            "flux_fill_dev": {
                "repository": "black-forest-labs/FLUX.1-Fill-dev",
                "revision": "358293da0354175698b67ec8299acf928313a78a",
            },
            "textflux": {
                "repository": "yyyyyxie/textflux",
                "revision": "8930419673bacf8716eb54a79632a5ec5a8b9862",
            },
        }}
    if args.only in ("all", "flux"):
        manifest["flux_fill_dev"] = describe_tree(flux, args.sha256)
    if args.only in ("all", "textflux"):
        manifest["textflux"] = describe_tree(textflux, args.sha256)
    encoded = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
        print(f"Wrote {args.output}")
    else:
        print(encoded, end="")


if __name__ == "__main__":
    main()

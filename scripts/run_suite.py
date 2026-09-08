#!/usr/bin/env python3
"""Run a fixed-seed TextFlux Korean-document benchmark suite on a Linux host."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


CASE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,79}$")


def parse_manifest(path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        case = json.loads(line)
        required = {"id", "track", "field_type", "source_image", "mask_image", "text"}
        missing = required.difference(case)
        if missing:
            raise ValueError(f"line {line_number}: missing keys: {', '.join(sorted(missing))}")
        if not isinstance(case["id"], str) or not CASE_ID_RE.fullmatch(case["id"]):
            raise ValueError(f"line {line_number}: invalid case id")
        if case["id"] in seen:
            raise ValueError(f"line {line_number}: duplicate case id: {case['id']}")
        if not isinstance(case["text"], str) or not case["text"].strip() or "\n" in case["text"]:
            raise ValueError(f"line {line_number}: text must be a non-empty single line")
        seen.add(case["id"])
        cases.append(case)
    if not cases:
        raise ValueError("manifest contains no cases")
    return cases


def input_path(root: Path, relative: str, label: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"{label}: path must be relative to --input-root")
    resolved_root = root.resolve()
    resolved = (resolved_root / candidate).resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"{label}: path resolves outside --input-root") from exc
    if not resolved.is_file():
        raise ValueError(f"{label}: file not found: {resolved}")
    return resolved


def require_share_path(path: Path, label: str) -> None:
    if not str(path).startswith("/share/"):
        raise ValueError(f"{label} must be under /share because the container mounts /share: {path}")


def parse_seeds(value: str) -> list[int]:
    try:
        seeds = [int(seed.strip()) for seed in value.split(",") if seed.strip()]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("--seeds must be comma-separated integers") from exc
    if not seeds:
        raise argparse.ArgumentTypeError("--seeds must contain at least one value")
    return seeds


def command_text(command: Iterable[str]) -> str:
    return " ".join(subprocess.list2cmdline([part]) for part in command)


def run_stream(command: list[str], log_path: Path) -> int:
    with log_path.open("w", encoding="utf-8") as log_file:
        log_file.write(f"$ {command_text(command)}\n\n")
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert process.stdout is not None
        for line in process.stdout:
            print(line, end="")
            log_file.write(line)
        return process.wait()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def docker_create(
    args: argparse.Namespace,
    case: dict[str, Any],
    source: Path,
    mask: Path,
    run_dir: Path,
    words_path: Path,
    container_name: str,
) -> list[str]:
    outputs_dir = run_dir / "outputs_my"
    return [
        "sudo",
        "docker",
        "create",
        "--runtime=nvidia",
        "--gpus",
        "all",
        "--shm-size=50g",
        "--network",
        "none",
        "-v",
        "/share:/share",
        "-v",
        f"{outputs_dir}:/opt/textflux/app/outputs_my",
        "-v",
        f"{run_dir}:/output",
        "-v",
        f"{args.font}:/opt/textflux/app/resource/font/Arial-Unicode-Regular.ttf:ro",
        "--workdir",
        "/opt/textflux/app",
        "-e",
        f"TEXTFLUX_MODEL_ROOT={args.model_root}",
        "--name",
        container_name,
        args.runtime_image,
        "--image",
        str(source),
        "--mask",
        str(mask),
        "--words",
        str(words_path),
        "--output",
        "/output/result.png",
        "--steps",
        str(args.steps),
        "--guidance-scale",
        str(args.guidance_scale),
        "--seed",
        str(args.seed),
    ]


def execute_case(args: argparse.Namespace, case: dict[str, Any], source: Path, mask: Path, seed: int) -> None:
    run_dir = args.bundle / "runs" / args.suite / case["id"] / f"seed-{seed:06d}"
    if run_dir.exists():
        raise RuntimeError(f"refusing to overwrite existing run: {run_dir}")

    words_path = run_dir / "words_0001.txt"
    outputs_dir = run_dir / "outputs_my"
    run_dir.mkdir(parents=True, exist_ok=False)
    outputs_dir.mkdir()
    words_path.write_text(case["text"] + "\n", encoding="utf-8")

    metadata = {
        "case": case,
        "seed": seed,
        "source_image": str(source),
        "mask_image": str(mask),
        "runtime_image": args.runtime_image,
        "checkpoint_id": args.checkpoint_id,
        "model_root": str(args.model_root),
        "font": str(args.font),
        "steps": args.steps,
        "guidance_scale": args.guidance_scale,
        "network": "none",
        "style_reference_consumed": False,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    (run_dir / "case.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    container_name = f"textflux-bench-{case['id']}-{seed}-{stamp}".lower()
    args.seed = seed
    create_command = docker_create(args, case, source, mask, run_dir, words_path, container_name)
    (run_dir / "docker-create-command.json").write_text(
        json.dumps(create_command, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    if args.dry_run:
        print(f"DRY RUN {case['id']} seed={seed}")
        print(command_text(create_command))
        return

    create_result = subprocess.run(create_command, check=True, capture_output=True, text=True)
    container_id = create_result.stdout.strip()
    if not container_id:
        raise RuntimeError(f"docker create returned no container id for {case['id']}")

    log_path = run_dir / "run.log"
    start_command = ["sudo", "docker", "start", "-a", container_id]
    try:
        return_code = run_stream(start_command, log_path)
        if return_code != 0:
            raise RuntimeError(f"inference failed for {case['id']} seed={seed}; see {log_path}")

        subprocess.run(["sudo", "chown", "-R", f"{os.getuid()}:{os.getgid()}", str(run_dir)], check=True)
        result_path = run_dir / "result.png"
        if not result_path.is_file():
            raise RuntimeError(f"inference completed without result.png: {run_dir}")
        (run_dir / "result.png.sha256").write_text(
            f"{sha256(result_path)}  result.png\n", encoding="utf-8"
        )
        print(f"DONE {case['id']} seed={seed}: {result_path}")
    finally:
        subprocess.run(["sudo", "docker", "rm", "-f", container_id], check=False, capture_output=True, text=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--font", type=Path, required=True)
    parser.add_argument("--suite", required=True, help="new run-suite identifier; existing paths are never overwritten")
    parser.add_argument("--runtime-image", default="textflux-offline:2026-08-25")
    parser.add_argument(
        "--checkpoint-id",
        default="unknown",
        help="immutable model identifier, for example yyyyyxie/textflux@<revision>",
    )
    parser.add_argument("--model-root", type=Path)
    parser.add_argument("--seeds", default="42")
    parser.add_argument("--steps", type=int, default=30)
    parser.add_argument(
        "--guidance-scale",
        type=float,
        default=30.0,
        help="FLUX guidance. Upstream defaults to 30.0; lower values loosen prompt adherence.",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if os.name == "nt":
        parser.error("run_suite.py must run on the Linux Docker host, not Windows")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,79}", args.suite):
        parser.error("--suite must contain lowercase letters, digits, and hyphens")
    if args.steps < 1:
        parser.error("--steps must be positive")
    if args.guidance_scale <= 0:
        parser.error("--guidance-scale must be positive")

    args.bundle = args.bundle.resolve()
    args.input_root = args.input_root.resolve()
    args.font = args.font.resolve()
    args.model_root = (args.model_root or (args.bundle / "payload")).resolve()
    for path, label in ((args.bundle, "--bundle"), (args.input_root, "--input-root"), (args.font, "--font"), (args.model_root, "--model-root")):
        require_share_path(path, label)
    if not args.font.is_file():
        parser.error(f"font file not found: {args.font}")

    try:
        seeds = parse_seeds(args.seeds)
        cases = parse_manifest(args.manifest)
        for case in cases:
            source = input_path(args.input_root, case["source_image"], f"{case['id']}.source_image")
            mask = input_path(args.input_root, case["mask_image"], f"{case['id']}.mask_image")
            require_share_path(source, f"{case['id']}.source_image")
            require_share_path(mask, f"{case['id']}.mask_image")
            for seed in seeds:
                execute_case(args, case, source, mask, seed)
    except (OSError, ValueError, subprocess.CalledProcessError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

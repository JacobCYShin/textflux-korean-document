#!/usr/bin/env python3
"""Crop each target field out of the form and upscale it before inference.

Why this exists
---------------
Aspect-fitting the mask fixed *what shape* the model writes into, but not *how
many pixels* it has to work with. On the full form a text line is 81px tall,
which is 5 rows of latent patches after the VAE and patchify steps. That is too
little to place the strokes of a Hangul syllable, and the observed errors are at
exactly that level: a vertical stroke growing a crossbar, a vowel flipping.

This script writes a new source image and mask per case containing only the
field plus surrounding context, scaled so the text line is `--target-line-height`
pixels tall. The emitted manifest points at those files, so `run_suite.py` and
`validate_cases.py` run unchanged. Afterwards `paste_crop_results.py` scales the
results back down onto the original form.

Canvas sizing follows what upstream does at inference time: it stacks a glyph
strip of height 0.15625 x width above the image and then rounds the combined
canvas down to a multiple of 32. Both dimensions are chosen here so that
rounding is a no-op, otherwise every case would be resampled a second time.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

CASE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,79}$")
STRIP_RATIO = 0.15625  # upstream render_single_line_text: strip height = width * 0.15625
ALIGN = 32  # upstream rounds the combined canvas down to a multiple of this


def parse_manifest(path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            case = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"line {line_number}: invalid JSON: {exc.msg}") from exc
        for key in ("id", "source_image", "mask_image", "text"):
            if key not in case:
                raise ValueError(f"line {line_number}: missing key: {key}")
        if not CASE_ID_RE.fullmatch(str(case["id"])):
            raise ValueError(f"line {line_number}: invalid case id: {case['id']!r}")
        if case["id"] in seen:
            raise ValueError(f"line {line_number}: duplicate case id: {case['id']}")
        seen.add(case["id"])
        cases.append(case)
    if not cases:
        raise ValueError("manifest contains no cases")
    return cases


def relative_path(root: Path, value: str, label: str) -> Path:
    candidate = Path(value)
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


def mask_bbox(path: Path) -> tuple[int, int, int, int]:
    array = np.array(Image.open(path).convert("L"))
    ys, xs = np.nonzero(array >= 128)
    if len(xs) == 0:
        raise ValueError(f"{path}: mask has no white pixels")
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def grow_span(low: int, high: int, margin: int, limit: int) -> tuple[int, int]:
    """Widen [low, high] by margin on both sides, redistributing what the edges clip."""
    span = high - low + 1
    wanted = span + 2 * margin
    if wanted >= limit:
        return 0, limit - 1
    new_low = low - margin
    new_high = high + margin
    if new_low < 0:
        new_high += -new_low
        new_low = 0
    if new_high > limit - 1:
        new_low -= new_high - (limit - 1)
        new_high = limit - 1
    return max(new_low, 0), min(new_high, limit - 1)


def plan_canvas(crop_w: int, crop_h: int, scale: float) -> tuple[int, int, int]:
    """Pick output width/height so upstream's multiple-of-32 rounding changes nothing.

    Returns (width, height, strip_height).
    """
    width = max(ALIGN, int(round(crop_w * scale / ALIGN)) * ALIGN)
    strip_height = int(width * STRIP_RATIO)
    target_height = max(1, int(round(crop_h * scale)))
    # combined = strip_height + height must already be a multiple of ALIGN
    combined = int(math.ceil((strip_height + target_height) / ALIGN)) * ALIGN
    height = combined - strip_height
    return width, height, strip_height


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--out-manifest", type=Path, required=True)
    parser.add_argument("--meta", type=Path, required=True, help="crop geometry, consumed by paste_crop_results.py")
    parser.add_argument(
        "--target-line-height",
        type=int,
        default=192,
        help="pixel height of the text line after upscaling (default 192, was 81 on the full form)",
    )
    parser.add_argument(
        "--context-x",
        type=float,
        default=4.5,
        help=(
            "horizontal context around the field, in multiples of the field height. "
            "The default reaches past the printed row label; TextFlux infers style from "
            "surrounding text, so a crop of blank paper removes the only style cue it has."
        ),
    )
    parser.add_argument(
        "--context-y",
        type=float,
        default=1.2,
        help="vertical context around the field, in multiples of the field height",
    )
    parser.add_argument(
        "--min-canvas-width",
        type=int,
        default=1024,
        help="widen the crop until the upscaled image is at least this wide",
    )
    parser.add_argument(
        "--max-megapixels",
        type=float,
        default=2.6,
        help="cap on the combined glyph-strip + image canvas; scale is reduced to fit",
    )
    parser.add_argument("--prefix", default="crop", help="filename prefix for generated inputs")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.target_line_height < 16:
        parser.error("--target-line-height must be at least 16")
    if args.context_x < 0 or args.context_y < 0:
        parser.error("context margins must be non-negative")
    if args.max_megapixels <= 0:
        parser.error("--max-megapixels must be positive")

    input_root = args.input_root.resolve()
    forms_dir = input_root / "forms"
    masks_dir = input_root / "masks"
    if not args.dry_run:
        forms_dir.mkdir(parents=True, exist_ok=True)
        masks_dir.mkdir(parents=True, exist_ok=True)

    try:
        cases = parse_manifest(args.manifest)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    out_lines: list[str] = []
    meta: dict[str, Any] = {
        "target_line_height": args.target_line_height,
        "prefix": args.prefix,
        "cases": {},
    }
    failures = 0

    print(f"{'case':24s} {'line px':>8s} {'crop':>12s} {'canvas':>12s} {'field%':>7s} {'latent':>7s} {'MP':>5s}")
    print("-" * 88)
    for case in cases:
        case_id = case["id"]
        try:
            source_path = relative_path(input_root, case["source_image"], f"{case_id}.source_image")
            mask_path = relative_path(input_root, case["mask_image"], f"{case_id}.mask_image")
            with Image.open(source_path) as probe:
                source_size = probe.size
            with Image.open(mask_path) as probe:
                if probe.size != source_size:
                    raise ValueError(f"mask {probe.size} does not match source {source_size}")

            x0, y0, x1, y1 = mask_bbox(mask_path)
            field_h = y1 - y0 + 1
            field_w = x1 - x0 + 1

            scale = args.target_line_height / field_h
            for _ in range(24):
                cx0, cx1 = grow_span(x0, x1, int(round(args.context_x * field_h)), source_size[0])
                cy0, cy1 = grow_span(y0, y1, int(round(args.context_y * field_h)), source_size[1])
                # widen until the upscaled crop reaches --min-canvas-width
                need = int(math.ceil(args.min_canvas_width / scale))
                if (cx1 - cx0 + 1) < need:
                    extra = int(math.ceil((need - (cx1 - cx0 + 1)) / 2))
                    cx0, cx1 = grow_span(cx0, cx1, extra, source_size[0])
                crop_w = cx1 - cx0 + 1
                crop_h = cy1 - cy0 + 1
                width, height, strip_h = plan_canvas(crop_w, crop_h, scale)
                megapixels = width * (height + strip_h) / 1e6
                if megapixels <= args.max_megapixels:
                    break
                scale *= 0.92
            else:
                raise ValueError("could not fit the canvas under --max-megapixels")

            if scale <= 1.0:
                print(f"  NOTE {case_id}: scale fell to {scale:.2f}x; raise --max-megapixels", file=sys.stderr)

            box = (cx0, cy0, cx1 + 1, cy1 + 1)
            with Image.open(source_path) as source:
                crop_img = source.convert("RGB").crop(box).resize((width, height), Image.LANCZOS)
            with Image.open(mask_path) as mask:
                crop_mask = mask.convert("L").crop(box).resize((width, height), Image.NEAREST)

            mask_array = np.array(crop_mask)
            mask_array = np.where(mask_array >= 128, 255, 0).astype(np.uint8)
            white = int((mask_array == 255).sum())
            if white == 0:
                raise ValueError("cropped mask lost every white pixel")
            if white == mask_array.size:
                raise ValueError("cropped mask covers the whole crop; increase --context-x/--context-y")
            crop_mask = Image.fromarray(mask_array, mode="L")

            ys, xs = np.nonzero(mask_array == 255)
            new_field_h = int(ys.max() - ys.min() + 1)
            field_share = white / mask_array.size * 100
            latent_rows = new_field_h / 16  # VAE /8 then patchify /2

            form_name = f"forms/{args.prefix}__{case_id}.png"
            mask_name = f"masks/{args.prefix}__{case_id}.png"
            if not args.dry_run:
                crop_img.save(input_root / form_name)
                crop_mask.save(input_root / mask_name)

            new_case = dict(case)
            new_case["source_image"] = form_name
            new_case["mask_image"] = mask_name
            notes = str(case.get("notes") or "").strip()
            marker = f"cropped+upscaled {scale:.2f}x, line {field_h}->{new_field_h}px"
            new_case["notes"] = f"{notes}; {marker}" if notes else marker
            out_lines.append(json.dumps(new_case, ensure_ascii=False))

            meta["cases"][case_id] = {
                "source_image": case["source_image"],
                "mask_image": case["mask_image"],
                "crop_box": [cx0, cy0, cx1 + 1, cy1 + 1],
                "crop_size": [crop_w, crop_h],
                "canvas_size": [width, height],
                "scale": scale,
                "field_height_before": field_h,
                "field_height_after": new_field_h,
                "field_width_before": field_w,
            }

            print(
                f"{case_id:24s} {field_h:3d}->{new_field_h:3d} {crop_w:5d}x{crop_h:<6d} "
                f"{width:5d}x{height:<6d} {field_share:6.1f}% {latent_rows:6.1f} {megapixels:5.2f}"
            )
        except (OSError, ValueError) as exc:
            failures += 1
            print(f"ERROR {case_id}: {exc}", file=sys.stderr)

    if failures:
        print(f"\nFAILED: {failures} of {len(cases)} case(s)", file=sys.stderr)
        return 1
    if args.dry_run:
        print("\nDRY RUN: no files written")
        return 0

    args.out_manifest.parent.mkdir(parents=True, exist_ok=True)
    args.out_manifest.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    args.meta.parent.mkdir(parents=True, exist_ok=True)
    args.meta.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nWrote {len(out_lines)} case(s) -> {args.out_manifest}")
    print(f"Crop geometry              -> {args.meta}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

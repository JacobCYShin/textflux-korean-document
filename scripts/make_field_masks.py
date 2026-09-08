#!/usr/bin/env python3
"""Generate field masks whose aspect ratio matches the rendered glyph condition.

TextFlux renders the requested text into a glyph strip and expects the masked
region to have a comparable shape. When the mask box is much wider than the
rendered text, the model fills the extra width with invented characters. This
script sizes each mask to the ink aspect ratio of its own text, using the same
font the runtime uses.

The source mask supplies the field position and line height; only the width is
recomputed. A rewritten manifest pointing at the new masks is emitted.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont

CASE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,79}$")
INK_THRESHOLD = 8


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
    return resolved


def glyph_ink_aspect(font_path: Path, text: str, probe_size: int = 120) -> tuple[float, int, int]:
    """Return (aspect, ink_width, ink_height) for text rendered with this font.

    The canvas grows until the ink no longer touches an edge, so long strings
    are measured as accurately as short ones.
    """
    font = ImageFont.truetype(str(font_path), probe_size)
    width = max(probe_size * (len(text) + 4), 512)
    height = probe_size * 4
    for _ in range(8):
        image = Image.new("L", (width, height), 0)
        ImageDraw.Draw(image).text((width / 2, height / 2), text, font=font, fill=255, anchor="mm")
        array = np.array(image)
        ys, xs = np.nonzero(array > INK_THRESHOLD)
        if len(xs) == 0:
            raise ValueError(f"font rendered no ink for {text!r}; is the font missing these glyphs?")
        if xs.min() > 0 and xs.max() < width - 1 and ys.min() > 0 and ys.max() < height - 1:
            return (xs.max() - xs.min() + 1) / (ys.max() - ys.min() + 1), int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)
        width *= 2
        height *= 2
    raise ValueError(f"could not measure {text!r} without clipping")


def field_bbox(mask_path: Path) -> tuple[int, int, int, int]:
    array = np.array(Image.open(mask_path).convert("L"))
    ys, xs = np.nonzero(array >= 128)
    if len(xs) == 0:
        raise ValueError(f"{mask_path}: mask has no white pixels")
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def verify_font_has_glyphs(font_path: Path, samples: str = "금융") -> None:
    """Reject a font that renders every sample as the same .notdef box."""
    font = ImageFont.truetype(str(font_path), 96)
    rendered = []
    for character in samples:
        image = Image.new("L", (256, 256), 0)
        ImageDraw.Draw(image).text((128, 128), character, font=font, fill=255, anchor="mm")
        array = np.array(image)
        if not (array > INK_THRESHOLD).any():
            raise ValueError(f"font has no glyph for {character!r}: {font_path}")
        rendered.append(array)
    if len(rendered) > 1 and all(np.array_equal(rendered[0], other) for other in rendered[1:]):
        raise ValueError(
            f"font renders {samples!r} identically, which means the glyphs are missing: {font_path}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--font", type=Path, required=True, help="the same font the runtime mounts")
    parser.add_argument("--out-manifest", type=Path, required=True)
    parser.add_argument("--mask-subdir", default="masks", help="relative to --input-root")
    parser.add_argument("--suffix", default="fit", help="appended to generated mask filenames")
    parser.add_argument("--align", choices=("left", "center", "right"), default="left")
    parser.add_argument(
        "--slack",
        type=float,
        default=1.06,
        help="widen the box slightly so glyphs are not flush against the edge",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.slack < 1.0:
        parser.error("--slack must be >= 1.0")
    if not args.font.is_file():
        parser.error(f"font not found: {args.font}")

    input_root = args.input_root.resolve()
    mask_dir = input_root / args.mask_subdir
    if not args.dry_run:
        mask_dir.mkdir(parents=True, exist_ok=True)

    try:
        verify_font_has_glyphs(args.font)
        cases = parse_manifest(args.manifest)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    out_lines: list[str] = []
    failures = 0
    print(f"{'case':26s} {'text':22s} {'glyph':>7s} {'was':>7s} {'now':>7s}  width")
    print("-" * 82)
    for case in cases:
        case_id = case["id"]
        try:
            source_path = relative_path(input_root, case["source_image"], f"{case_id}.source_image")
            mask_path = relative_path(input_root, case["mask_image"], f"{case_id}.mask_image")
            with Image.open(source_path) as source:
                source_size = source.size
            with Image.open(mask_path) as mask_probe:
                if mask_probe.size != source_size:
                    raise ValueError(
                        f"mask {mask_probe.size} does not match source {source_size}"
                    )

            aspect, _, _ = glyph_ink_aspect(args.font, case["text"])
            x0, y0, x1, y1 = field_bbox(mask_path)
            field_width = x1 - x0 + 1
            field_height = y1 - y0 + 1
            old_aspect = field_width / field_height

            target_width = int(round(field_height * aspect * args.slack))
            note = ""
            if target_width > field_width:
                target_width = field_width
                note = "  CLAMPED: text is wider than the printed field"
            target_width = max(target_width, field_height)  # never narrower than one square cell

            if args.align == "left":
                nx0 = x0
            elif args.align == "center":
                nx0 = x0 + (field_width - target_width) // 2
            else:
                nx0 = x1 - target_width + 1
            nx1 = nx0 + target_width - 1

            new_mask = np.zeros((source_size[1], source_size[0]), dtype=np.uint8)
            new_mask[y0 : y1 + 1, nx0 : nx1 + 1] = 255
            out_name = f"{mask_path.stem}__{case_id}__{args.suffix}.png"
            out_path = mask_dir / out_name
            if not args.dry_run:
                Image.fromarray(new_mask, mode="L").save(out_path)

            new_case = dict(case)
            new_case["mask_image"] = str(Path(args.mask_subdir) / out_name)
            notes = str(case.get("notes") or "").strip()
            marker = f"aspect-fitted mask ({old_aspect:.1f}:1 -> {target_width / field_height:.1f}:1)"
            new_case["notes"] = f"{notes}; {marker}" if notes else marker
            out_lines.append(json.dumps(new_case, ensure_ascii=False))

            print(
                f"{case_id:26s} {case['text'][:20]:22s} {aspect:6.1f}  {old_aspect:6.1f}  "
                f"{target_width / field_height:6.1f}  {field_width}->{target_width}px{note}"
            )
        except (OSError, ValueError) as exc:
            failures += 1
            print(f"ERROR {case_id}: {exc}", file=sys.stderr)

    if failures:
        print(f"\nFAILED: {failures} of {len(cases)} case(s)", file=sys.stderr)
        return 1
    if not args.dry_run:
        args.out_manifest.parent.mkdir(parents=True, exist_ok=True)
        args.out_manifest.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
        print(f"\nWrote {len(out_lines)} case(s) -> {args.out_manifest}")
    else:
        print("\nDRY RUN: no files written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

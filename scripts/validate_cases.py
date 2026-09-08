#!/usr/bin/env python3
"""Validate a private TextFlux Korean-document benchmark manifest."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont


ALLOWED_TRACKS = {"content", "style"}
ALLOWED_FIELD_TYPES = {
    "hangul",
    "amount",
    "currency",
    "account",
    "swift",
    "date",
    "identifier",
    "mixed",
}
REQUIRED_KEYS = {"id", "track", "field_type", "source_image", "mask_image", "text"}
CASE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,79}$")
INK_THRESHOLD = 8
ASPECT_TOLERANCE = 0.5


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
        if not isinstance(case, dict):
            raise ValueError(f"line {line_number}: every entry must be a JSON object")
        missing = REQUIRED_KEYS.difference(case)
        if missing:
            raise ValueError(f"line {line_number}: missing keys: {', '.join(sorted(missing))}")
        case_id = case["id"]
        if not isinstance(case_id, str) or not CASE_ID_RE.fullmatch(case_id):
            raise ValueError(f"line {line_number}: invalid case id: {case_id!r}")
        if case_id in seen:
            raise ValueError(f"line {line_number}: duplicate case id: {case_id}")
        seen.add(case_id)
        cases.append(case)

    if not cases:
        raise ValueError("manifest contains no cases")
    return cases


def resolve_private_path(input_root: Path, value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label}: must be a non-empty relative path")
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"{label}: must stay inside INPUT_ROOT")
    resolved_root = input_root.resolve()
    resolved = (resolved_root / relative).resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"{label}: resolves outside INPUT_ROOT") from exc
    return resolved


def check_image(path: Path, label: str) -> tuple[int, int]:
    if not path.is_file():
        raise ValueError(f"{label}: file not found: {path}")
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            return image.size
    except Exception as exc:  # Pillow raises format-specific errors.
        raise ValueError(f"{label}: cannot read image {path}: {exc}") from exc


def check_mask(path: Path, expected_size: tuple[int, int]) -> None:
    actual_size = check_image(path, "mask_image")
    if actual_size != expected_size:
        raise ValueError(
            f"mask_image: dimensions {actual_size[0]}x{actual_size[1]} "
            f"do not match source {expected_size[0]}x{expected_size[1]}"
        )

    with Image.open(path) as image:
        grayscale = image.convert("L")
        values = grayscale.getdata()
        total = grayscale.width * grayscale.height
        white = 0
        non_binary = 0
        for value in values:
            if value == 255:
                white += 1
            if value not in (0, 255):
                non_binary += 1

    if white == 0:
        raise ValueError("mask_image: has no editable (white) pixels")
    if white == total:
        raise ValueError("mask_image: covers the full source image")
    non_binary_ratio = non_binary / total
    if non_binary_ratio > 0.01:
        raise ValueError(
            f"mask_image: {non_binary_ratio:.2%} of pixels are not 0 or 255; "
            "use a binary mask"
        )



def glyph_ink_aspect(font_path: Path, text: str, probe_size: int = 120) -> float:
    """Aspect ratio of the text as the runtime will render it into the glyph strip."""
    font = ImageFont.truetype(str(font_path), probe_size)
    width = max(probe_size * (len(text) + 4), 512)
    height = probe_size * 4
    for _ in range(8):
        image = Image.new("L", (width, height), 0)
        ImageDraw.Draw(image).text((width / 2, height / 2), text, font=font, fill=255, anchor="mm")
        array = np.array(image)
        ys, xs = np.nonzero(array > INK_THRESHOLD)
        if len(xs) == 0:
            raise ValueError(f"font rendered no ink for {text!r}; the glyphs are probably missing")
        if xs.min() > 0 and xs.max() < width - 1 and ys.min() > 0 and ys.max() < height - 1:
            return (xs.max() - xs.min() + 1) / (ys.max() - ys.min() + 1)
        width *= 2
        height *= 2
    raise ValueError(f"could not measure {text!r} without clipping")


def verify_font_has_glyphs(font_path: Path, samples: str = "\uae08\uc735") -> None:
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
        raise ValueError(f"font renders {samples!r} identically; the glyphs are missing: {font_path}")


def mask_bbox_shape(path: Path) -> tuple[int, int]:
    array = np.array(Image.open(path).convert("L"))
    ys, xs = np.nonzero(array >= 128)
    return int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)


def validate_case(
    case: dict[str, Any],
    input_root: Path,
    allow_multiline: bool,
    font_path: Path | None = None,
    strict_aspect: bool = False,
) -> list[str]:
    case_id = case["id"]
    track = case["track"]
    field_type = case["field_type"]
    text = case["text"]

    if track not in ALLOWED_TRACKS:
        raise ValueError(f"{case_id}: track must be one of {sorted(ALLOWED_TRACKS)}")
    if field_type not in ALLOWED_FIELD_TYPES:
        raise ValueError(f"{case_id}: unsupported field_type: {field_type!r}")
    if not isinstance(text, str) or not text.strip():
        raise ValueError(f"{case_id}: text must be non-empty")
    if not allow_multiline and ("\n" in text or "\r" in text):
        raise ValueError(f"{case_id}: multiline text is not allowed in the single-line baseline")

    source_path = resolve_private_path(input_root, case["source_image"], f"{case_id}.source_image")
    mask_path = resolve_private_path(input_root, case["mask_image"], f"{case_id}.mask_image")
    source_size = check_image(source_path, "source_image")
    check_mask(mask_path, source_size)

    style_reference = case.get("style_reference")
    if track == "style" and not style_reference:
        raise ValueError(f"{case_id}: style cases require style_reference metadata")
    if style_reference is not None:
        check_image(resolve_private_path(input_root, style_reference, f"{case_id}.style_reference"), "style_reference")

    warnings: list[str] = []
    if font_path is not None:
        glyph_ratio = glyph_ink_aspect(font_path, text)
        box_width, box_height = mask_bbox_shape(mask_path)
        box_ratio = box_width / box_height
        delta = abs(glyph_ratio - box_ratio)
        if delta > ASPECT_TOLERANCE:
            suggested = int(round(box_height * glyph_ratio))
            message = (
                f"{case_id}: aspect mismatch -- glyph {glyph_ratio:.1f}:1 vs mask box "
                f"{box_ratio:.1f}:1 (delta {delta:.1f}). The model tends to invent characters "
                f"to fill the extra width. Suggested mask width: about {suggested}px "
                f"instead of {box_width}px."
            )
            if strict_aspect:
                raise ValueError(message)
            warnings.append(message)
    return warnings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--allow-multiline", action="store_true")
    parser.add_argument(
        "--font",
        type=Path,
        help="the font the runtime mounts; enables the glyph/mask aspect-ratio check",
    )
    parser.add_argument(
        "--strict-aspect",
        action="store_true",
        help="treat an aspect-ratio mismatch as an error instead of a warning",
    )
    args = parser.parse_args()

    errors: list[str] = []
    warnings: list[str] = []
    if args.font is not None:
        if not args.font.is_file():
            print(f"ERROR: font not found: {args.font}", file=sys.stderr)
            return 2
        try:
            verify_font_has_glyphs(args.font)
        except (OSError, ValueError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
    try:
        cases = parse_manifest(args.manifest)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    input_root = args.input_root.resolve()
    if not input_root.is_dir():
        print(f"ERROR: INPUT_ROOT does not exist: {input_root}", file=sys.stderr)
        return 2

    for case in cases:
        try:
            case_warnings = validate_case(
                case, input_root, args.allow_multiline, args.font, args.strict_aspect
            )
            warnings.extend(case_warnings)
            print(f"{'WARN ' if case_warnings else 'OK   '} {case['id']}")
            for warning in case_warnings:
                print(f"      {warning}")
        except ValueError as exc:
            errors.append(str(exc))
            print(f"ERROR {exc}", file=sys.stderr)

    if errors:
        print(f"VALIDATION FAILED: {len(errors)} error(s), {len(cases)} case(s) checked", file=sys.stderr)
        return 1

    if warnings:
        print(
            f"VALIDATION PASSED WITH WARNINGS: {len(cases)} case(s) checked, "
            f"{len(warnings)} aspect warning(s)"
        )
        return 0

    print(f"VALIDATION PASSED: {len(cases)} case(s) checked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

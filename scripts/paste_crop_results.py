#!/usr/bin/env python3
"""Scale cropped-field results back onto the full form and build a review sheet.

Pairs with `make_crop_inputs.py`. For every run it writes `result_full.png`
(the original form with the generated field pasted back at original scale) and
`result_field.png` (the field at the resolution the model actually worked at,
which is what you should read the characters from).

It also writes one contact sheet per suite: a single PNG with the requested text
beside every seed's output, so a sweep can be judged from one image instead of
opening dozens of files.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont

RUNTIME_FONT = "/opt/textflux/app/resource/font/Arial-Unicode-Regular.ttf"
FIELD_PAD = 10
SHEET_ROW_HEIGHT = 96
SHEET_LABEL_WIDTH = 430
SHEET_GAP = 14
SHEET_ROW_STRIDE = SHEET_ROW_HEIGHT + 42  # row + seed caption + divider


def load_font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(str(path), size)
    except OSError:
        return ImageFont.load_default()


def mask_bbox(array: np.ndarray) -> tuple[int, int, int, int]:
    ys, xs = np.nonzero(array >= 128)
    if len(xs) == 0:
        raise ValueError("mask has no white pixels")
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def field_crop(result: Image.Image, mask_path: Path) -> Image.Image:
    """Cut the generated field out of a result, tolerating a size mismatch.

    Upstream rounds its canvas to a multiple of 32, so a result can be a little
    shorter than the mask it was produced from.
    """
    mask = np.array(Image.open(mask_path).convert("L"))
    x0, y0, x1, y1 = mask_bbox(mask)
    sx = result.width / mask.shape[1]
    sy = result.height / mask.shape[0]
    box = (
        max(0, int(x0 * sx) - FIELD_PAD),
        max(0, int(y0 * sy) - FIELD_PAD),
        min(result.width, int((x1 + 1) * sx) + FIELD_PAD),
        min(result.height, int((y1 + 1) * sy) + FIELD_PAD),
    )
    return result.crop(box)


def build_sheet(rows: list[dict[str, Any]], font_path: Path, title: str) -> Image.Image:
    font = load_font(font_path, 21)
    small = load_font(font_path, 17)
    head = load_font(font_path, 27)

    widths = []
    for row in rows:
        total = SHEET_LABEL_WIDTH
        for image in row["images"]:
            total += int(image.width * SHEET_ROW_HEIGHT / image.height) + SHEET_GAP
        widths.append(total)
    width = min(max(widths + [900]) + 24, 4200)
    height = 70 + len(rows) * SHEET_ROW_STRIDE + 16

    sheet = Image.new("RGB", (width, height), (250, 250, 250))
    draw = ImageDraw.Draw(sheet)
    draw.text((18, 20), title, font=head, fill=(20, 20, 20))
    y = 70
    for row in rows:
        draw.text((18, y + 6), row["case_id"], font=font, fill=(20, 20, 20))
        draw.text((18, y + 34), f"요청: {row['text']}", font=font, fill=(180, 30, 30))
        draw.text((18, y + 62), row["note"], font=small, fill=(120, 120, 120))
        x = SHEET_LABEL_WIDTH
        for seed, image in zip(row["seeds"], row["images"]):
            scaled_w = max(1, int(image.width * SHEET_ROW_HEIGHT / image.height))
            if x + scaled_w > width - 12:
                break
            sheet.paste(image.resize((scaled_w, SHEET_ROW_HEIGHT), Image.LANCZOS), (x, y))
            draw.rectangle([x, y, x + scaled_w, y + SHEET_ROW_HEIGHT], outline=(205, 205, 205))
            draw.text((x + 3, y + SHEET_ROW_HEIGHT + 4), f"seed {seed}", font=small, fill=(140, 140, 140))
            x += scaled_w + SHEET_GAP
        divider = y + SHEET_ROW_HEIGHT + 30
        draw.line([(12, divider), (width - 12, divider)], fill=(225, 225, 225))
        y += SHEET_ROW_STRIDE
    return sheet


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--meta", type=Path, required=True, help="crop-meta.json from make_crop_inputs.py")
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--suite", required=True)
    parser.add_argument("--font", type=Path, default=Path(RUNTIME_FONT))
    parser.add_argument("--sheet", type=Path, help="contact sheet path (default: <bundle>/runs/<suite>/review-sheet.png)")
    parser.add_argument("--skip-paste", action="store_true", help="only build the contact sheet")
    args = parser.parse_args()

    try:
        meta = json.loads(args.meta.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"ERROR: cannot read --meta: {exc}", file=sys.stderr)
        return 1

    input_root = args.input_root.resolve()
    suite_dir = args.bundle.resolve() / "runs" / args.suite
    if not suite_dir.is_dir():
        print(f"ERROR: suite directory not found: {suite_dir}", file=sys.stderr)
        return 1

    rows: list[dict[str, Any]] = []
    pasted = 0
    failures = 0
    for case_id, info in meta["cases"].items():
        case_dir = suite_dir / case_id
        if not case_dir.is_dir():
            print(f"SKIP {case_id}: no runs found")
            continue
        images: list[Image.Image] = []
        seeds: list[int] = []
        text = ""
        for seed_dir in sorted(case_dir.glob("seed-*")):
            result_path = seed_dir / "result.png"
            if not result_path.is_file():
                print(f"SKIP {case_id}/{seed_dir.name}: no result.png", file=sys.stderr)
                continue
            try:
                words = seed_dir / "words_0001.txt"
                if words.is_file():
                    text = words.read_text(encoding="utf-8").strip()
                with Image.open(result_path) as handle:
                    result = handle.convert("RGB")

                run_mask = seed_dir / "outputs_my/mask/mask_0001.png"
                mask_path = run_mask if run_mask.is_file() else input_root / info["mask_image"]
                field = field_crop(result, mask_path)
                field.save(seed_dir / "result_field.png")
                images.append(field)
                seeds.append(int(seed_dir.name.split("-")[-1]))

                if not args.skip_paste:
                    original = input_root / info["source_image"]
                    with Image.open(original) as handle:
                        full = handle.convert("RGB")
                    box = tuple(info["crop_box"])
                    region = result.resize((box[2] - box[0], box[3] - box[1]), Image.LANCZOS)
                    full.paste(region, (box[0], box[1]))
                    full.save(seed_dir / "result_full.png")
                    pasted += 1
            except (OSError, ValueError) as exc:
                failures += 1
                print(f"ERROR {case_id}/{seed_dir.name}: {exc}", file=sys.stderr)
        if images:
            rows.append(
                {
                    "case_id": case_id,
                    "text": text,
                    "note": f"line {info['field_height_before']}->{info['field_height_after']}px "
                    f"({info['scale']:.2f}x)",
                    "images": images,
                    "seeds": seeds,
                }
            )

    if not rows:
        print("ERROR: no results found; did run_suite.py finish?", file=sys.stderr)
        return 1

    sheet_path = args.sheet or (suite_dir / "review-sheet.png")
    sheet = build_sheet(rows, args.font, f"{args.suite}  -  crop+upscale review")
    sheet_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(sheet_path)

    print(f"\n{len(rows)} case(s), {sum(len(r['images']) for r in rows)} run(s)")
    if not args.skip_paste:
        print(f"result_full.png written for {pasted} run(s)")
    print(f"result_field.png written next to every result")
    print(f"Contact sheet -> {sheet_path}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

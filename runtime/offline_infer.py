#!/usr/bin/env python3
"""Run the official TextFlux inference flow using only local model paths."""

import argparse
import os
import sys
from pathlib import Path

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
os.environ.setdefault("HF_DATASETS_OFFLINE", "1")

# The entry-point script resides outside the pinned TextFlux source tree.
# Make that source importable regardless of the Python script launch location.
TEXTFLUX_APP_ROOT = Path(os.environ.get("TEXTFLUX_APP_ROOT", "/opt/textflux/app"))
sys.path.insert(0, str(TEXTFLUX_APP_ROOT))

import torch
from diffusers import FluxFillPipeline, FluxTransformer2DModel

import run_inference as textflux


DEFAULT_MODEL_ROOT = os.environ.get(
    "TEXTFLUX_MODEL_ROOT", "/share/jacob/textflux_offline_bundle/payload"
)
DEFAULT_FLUX_MODEL = os.environ.get("TEXTFLUX_FLUX_MODEL", f"{DEFAULT_MODEL_ROOT}/flux-fill-dev")
DEFAULT_TEXTFLUX_MODEL = os.environ.get("TEXTFLUX_TEXTFLUX_MODEL", f"{DEFAULT_MODEL_ROOT}/textflux")


def require_path(path: Path, description: str) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Missing {description}: {path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Offline TextFlux inference with a local FLUX.1-Fill-dev payload"
    )
    parser.add_argument("--image", required=True, help="Input scene image")
    parser.add_argument("--mask", required=True, help="Text-region mask image")
    parser.add_argument("--words", required=True, help="UTF-8 text file; one line per text region")
    parser.add_argument("--output", required=True, help="Destination PNG path")
    parser.add_argument("--flux-model", default=DEFAULT_FLUX_MODEL)
    parser.add_argument("--textflux-model", default=DEFAULT_TEXTFLUX_MODEL)
    parser.add_argument("--steps", type=int, default=30)
    parser.add_argument("--guidance-scale", type=float, default=30.0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--cpu-offload",
        action="store_true",
        help="Use sequential GPU offloading when the GPU cannot hold the full pipeline.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not torch.cuda.is_available():
        raise RuntimeError("A CUDA GPU is required. Start the container with --gpus all.")

    flux_model = Path(args.flux_model)
    textflux_model = Path(args.textflux_model)
    for required, description in (
        (flux_model / "model_index.json", "FLUX model index"),
        (flux_model / "text_encoder_2", "FLUX T5 encoder"),
        (flux_model / "vae", "FLUX VAE"),
        (textflux_model / "config.json", "TextFlux transformer configuration"),
    ):
        require_path(required, description)

    transformer = FluxTransformer2DModel.from_pretrained(
        textflux_model, torch_dtype=torch.bfloat16, local_files_only=True
    )
    pipe = FluxFillPipeline.from_pretrained(
        flux_model,
        transformer=transformer,
        torch_dtype=torch.bfloat16,
        local_files_only=True,
    )
    if args.cpu_offload:
        pipe.enable_model_cpu_offload()
    else:
        pipe.to("cuda")
        pipe.transformer.to(torch.bfloat16)

    # Reuse the official image/mask and glyph preparation implementation while
    # replacing its Hub model IDs with the fully local pipeline above.
    textflux.PIPE = pipe
    result = textflux.process_normal_mode(
        args.image, args.mask, args.words, args.steps, args.guidance_scale, args.seed
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    result.save(output)
    print(f"Saved image: {output}")


if __name__ == "__main__":
    main()

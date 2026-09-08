#!/usr/bin/env python3
"""Resumable download of the two model repositories into a bundle root.

Authenticate first with `hf auth login` or expose a read token through
HF_TOKEN. The token is never written into this bundle.
"""

import argparse
import os
from pathlib import Path

from huggingface_hub import snapshot_download


FLUX_PATTERNS = [
    "LICENSE.md",
    "README.md",
    "model_index.json",
    "scheduler/*",
    "text_encoder/*",
    "text_encoder_2/*",
    "tokenizer/*",
    "tokenizer_2/*",
    "transformer/*",
    "vae/*",
]
FLUX_REVISION = "358293da0354175698b67ec8299acf928313a78a"
TEXTFLUX_REVISION = "8930419673bacf8716eb54a79632a5ec5a8b9862"


def download(repo_id: str, revision: str, destination: Path, cache_dir: Path, allow_patterns=None) -> None:
    print(f"Downloading {repo_id}@{revision} -> {destination}")
    snapshot_download(
        repo_id=repo_id,
        revision=revision,
        local_dir=destination,
        cache_dir=cache_dir,
        token=True,
        allow_patterns=allow_patterns,
        max_workers=4,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle-root", type=Path, required=True)
    parser.add_argument("--only", choices=("all", "flux", "textflux"), default="all")
    args = parser.parse_args()

    root = args.bundle_root.resolve()
    payload = root / "payload"
    cache = root / ".hf-cache"
    payload.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    # hf-xet otherwise defaults to a user-profile cache, which is commonly on
    # the system drive. Keep resumable chunks beside this portable bundle.
    os.environ.setdefault("HF_XET_CACHE", str(cache / "xet"))

    if args.only in ("all", "flux"):
        download(
            "black-forest-labs/FLUX.1-Fill-dev",
            FLUX_REVISION,
            payload / "flux-fill-dev",
            cache,
            allow_patterns=FLUX_PATTERNS,
        )
    if args.only in ("all", "textflux"):
        download("yyyyyxie/textflux", TEXTFLUX_REVISION, payload / "textflux", cache)


if __name__ == "__main__":
    main()

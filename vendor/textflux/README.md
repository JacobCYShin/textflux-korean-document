# Vendored TextFlux snapshot

This directory is a verbatim snapshot of the upstream TextFlux project.

    https://github.com/yyyyyxie/textflux
    commit c791924acc4a93d48021c3731a75fada805cc501   (see UPSTREAM_REVISION)

**Do not edit anything here.** To move to a different upstream commit, update
the pin in `runtime/scripts/fetch_textflux_source.sh` and re-run it, then note
the change in `docs/decision-log.md`.

## What is and is not included

Included: source code, configuration, the modified `diffusers` tree upstream
ships, small example inputs, and upstream license and attribution files.

Excluded: TextFlux and FLUX checkpoints, evaluation OCR weights, datasets,
caches, and generated outputs. Model files are obtained separately by
`runtime/scripts/download_models.py`.

The snapshot carries no upstream git history — it is the file tree at that
commit. `runtime/scripts/fetch_textflux_source.sh` therefore verifies
`UPSTREAM_REVISION` rather than checking out a commit when it falls back here.

## Original documentation

Upstream's own README is preserved as `UPSTREAM_README.md`.

## Which files matter

`docs/pipeline.md` in the repository root explains the inference path and
points at the functions that determine behaviour. The short list:

| File | Role |
| --- | --- |
| `run_inference.py` | glyph strip rendering, vertical stacking, prompt construction |
| `image_datasets/dataset.py` | training data loader |
| `scripts/train.py`, `scripts/train_lora.py` | fine-tuning entry points |
| `diffusers/` | modified diffusers required by TextFlux; not replaceable with a PyPI release |

Licenses: `LICENSE` (upstream Apache-2.0), `LICENSE-MODEL` (FLUX.1-dev),
`NOTICE` (upstream provenance). The repository root `NOTICE` records how this
snapshot relates to the original work around it.

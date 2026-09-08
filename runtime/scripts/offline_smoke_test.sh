#!/usr/bin/env bash
# Prove the image can generate one image with no network access.
#
#   offline_smoke_test.sh [--workspace <path>] [--model-root <path>]
#
# Uses the example inputs baked into the image, so it needs no benchmark data.
# Run this first on a newly provisioned machine: it separates "the environment
# works" from "the model is accurate", which are different questions.
set -euo pipefail

WORKSPACE="${TEXTFLUX_WORKSPACE:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
MODEL_ROOT="${TEXTFLUX_MODEL_ROOT:-}"
TAG="${TEXTFLUX_IMAGE_TAG:-textflux-offline:2026-08-25}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --workspace)  WORKSPACE="$(cd "$2" && pwd)"; shift 2 ;;
    --model-root) MODEL_ROOT="$2"; shift 2 ;;
    -h|--help)    sed -n '2,10p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *)            printf 'Unknown argument: %s\n' "$1" >&2; exit 2 ;;
  esac
done

MODEL_ROOT="${MODEL_ROOT:-$WORKSPACE/payload}"
[[ -f "$MODEL_ROOT/flux-fill-dev/model_index.json" ]] || {
  echo "No FLUX payload at $MODEL_ROOT. Pass --model-root or set TEXTFLUX_MODEL_ROOT." >&2; exit 1; }

OUT="$WORKSPACE/deliverable/offline-smoke"
mkdir -p "$OUT"

CID=""
cleanup() { [[ -n "$CID" ]] && docker rm -f "$CID" >/dev/null 2>&1 || true; }
trap cleanup EXIT

# The deployment platform is responsible for exposing MODEL_ROOT at this
# absolute path inside the container. This script creates no bind mount and
# copies no model file.
CID="$(docker create --network none --gpus all \
  -e TEXTFLUX_MODEL_ROOT="$MODEL_ROOT" \
  "$TAG" \
  --image /opt/textflux/app/resource/example/ori/ori_0001.png \
  --mask /opt/textflux/app/resource/example/mask/mask_0001.png \
  --words /opt/textflux/app/resource/example/txt/words_0001.txt \
  --output /output/textflux-offline-smoke.png \
  --steps 30 \
  --seed 42)"

docker start -a "$CID"
docker cp "$CID:/output/textflux-offline-smoke.png" "$OUT/textflux-offline-smoke.png"

test -s "$OUT/textflux-offline-smoke.png"
sha256sum "$OUT/textflux-offline-smoke.png" | tee "$OUT/textflux-offline-smoke.png.sha256"
printf '\nOffline inference confirmed: %s\n' "$OUT/textflux-offline-smoke.png"

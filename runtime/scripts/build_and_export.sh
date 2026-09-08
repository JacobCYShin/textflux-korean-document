#!/usr/bin/env bash
# Build the inference image and export it as a tar archive.
#
#   build_and_export.sh [--repo <path>] [--workspace <path>]
#
# Two roots, deliberately separate:
#   repo       the checkout. Holds runtime/ and vendor/textflux/ and is the
#              Docker build context.
#   workspace  machine state. Holds payload/ (model files) and receives
#              deliverable/ (the exported tar). Never committed.
#
# They may be the same directory, but keeping them apart is what lets a fresh
# clone work without also carrying 54 GiB of weights.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORKSPACE="${TEXTFLUX_WORKSPACE:-$REPO}"
TAG="${TEXTFLUX_IMAGE_TAG:-textflux-offline:2026-08-25}"
SHA="c791924acc4a93d48021c3731a75fada805cc501"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo)      REPO="$(cd "$2" && pwd)"; shift 2 ;;
    --workspace) WORKSPACE="$(cd "$2" && pwd)"; shift 2 ;;
    -h|--help)   sed -n '2,14p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *)           printf 'Unknown argument: %s\n' "$1" >&2; exit 2 ;;
  esac
done

[[ -f "$REPO/runtime/Dockerfile"        ]] || { echo "Not a repository checkout: $REPO" >&2; exit 1; }
[[ -f "$REPO/vendor/textflux/run_inference.py" ]] || {
  echo "vendor/textflux is missing. Run runtime/scripts/fetch_textflux_source.sh first." >&2; exit 1; }

ARCHIVE="$WORKSPACE/deliverable/textflux-offline_2026-08-25.tar"
mkdir -p "$(dirname "$ARCHIVE")"

python3 "$REPO/runtime/scripts/verify_payload.py" \
  --bundle-root "$WORKSPACE" \
  --output "$WORKSPACE/deliverable/payload-manifest.json"

docker build --pull --no-cache \
  --build-arg TEXTFLUX_GIT_SHA="$SHA" \
  -t "$TAG" \
  -f "$REPO/runtime/Dockerfile" \
  "$REPO"

# Stream to the final path instead of `docker save -o`. Docker's temporary-file
# rename can fail on an exFAT volume accessed through WSL.
docker save "$TAG" > "$ARCHIVE"
sha256sum "$ARCHIVE" > "$ARCHIVE.sha256"
printf 'Created %s\n' "$ARCHIVE"

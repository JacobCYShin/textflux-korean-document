#!/usr/bin/env bash
# Place the pinned TextFlux source at <root>/source/textflux.
#
# Primary path: fetch the exact commit from upstream.
# Fallback:     clone the snapshot mirror, which holds the same tree at that
#               commit. Used when upstream is unreachable or the commit has
#               been removed. The mirror carries no upstream history, so the
#               pin is verified through its UPSTREAM_REVISION file instead of
#               a commit checkout.
set -euo pipefail

ROOT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
DEST="$ROOT/vendor/textflux"
SHA="c791924acc4a93d48021c3731a75fada805cc501"
UPSTREAM="${TEXTFLUX_UPSTREAM_REPO:-https://github.com/yyyyyxie/textflux.git}"
MIRROR="${TEXTFLUX_MIRROR_REPO:-https://github.com/JacobCYShin/textflux-airgap-source.git}"

git_at() { git -c safe.directory="$DEST" -C "$DEST" "$@"; }

from_upstream() {
  if [[ ! -d "$DEST/.git" ]]; then
    mkdir -p "$(dirname "$DEST")"
    git clone "$UPSTREAM" "$DEST"
  fi
  git_at fetch --depth 1 origin "$SHA"
  git_at checkout --detach "$SHA"
  git_at submodule update --init --recursive
}

from_mirror() {
  rm -rf "$DEST"
  mkdir -p "$(dirname "$DEST")"
  git clone --depth 1 "$MIRROR" "$DEST"
  local pinned
  pinned="$(tr -d '[:space:]' < "$DEST/UPSTREAM_REVISION")"
  if [[ "$pinned" != "$SHA" ]]; then
    printf 'Mirror is pinned to %s but this script expects %s\n' "$pinned" "$SHA" >&2
    exit 1
  fi
}

if from_upstream; then
  printf 'TextFlux source ready at %s (%s, from upstream)\n' "$DEST" "$SHA"
else
  printf 'Upstream fetch failed; falling back to the snapshot mirror\n' >&2
  from_mirror
  printf 'TextFlux source ready at %s (%s, from mirror)\n' "$DEST" "$SHA"
fi

# The mirror adds a few files upstream does not carry (README, NOTICE,
# LICENSE-MODEL, UPSTREAM_README, UPSTREAM_REVISION). They are small documents
# and harmless inside the image.

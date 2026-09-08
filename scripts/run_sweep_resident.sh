#!/usr/bin/env bash
# TextFlux probe sweep, run INSIDE the long-lived container.
#
#   sudo docker exec -it textflux-dev bash /share/.../scripts/run_sweep_resident.sh
#
# Differences from run_sweep.sh, which drove the host:
#   * no sudo anywhere, so nothing expires half way through
#   * the model loads once per shard instead of once per case
#   * work is split across GPUS shards, one GPU each
#   * resume is per case, not per stage: re-running continues where it stopped,
#     including a stage that died part way through
#
#   GPUS=1 ...       use a single GPU
#   DRY=1 ...        print what would run, touch nothing

set -uo pipefail

BUNDLE="${BUNDLE:-/share/jacob/textflux_offline_bundle}"
BENCH="${BENCH:-$BUNDLE/textflux-korean-document-benchmark}"
INPUTS="${INPUTS:-$BUNDLE/private-inputs}"
FONT="${FONT:-$BUNDLE/textflux-korean-font-patch/fonts/NotoSansCJKkr-Regular.otf}"
CKPT="${CKPT:-yyyyyxie/textflux}"
GPUS="${GPUS:-4}"
PY="${PY:-python}"
SCRIPTS="$BENCH/scripts"
CASES="$BENCH/cases"
LOGS="$BUNDLE/runs"
DRY="${DRY:-0}"
STAGGER="${STAGGER:-20}"   # seconds between shard starts, so weights are not pulled all at once

SUBSET='len-hangul-2|len-hangul-4|len-hangul-5|ctl-chinese-4|risk-amount-usd'

say()  { printf '\n\033[1m== %s\033[0m\n' "$*"; }
warn() { printf '   !! %s\n' "$*" >&2; }
run()  { if [ "$DRY" = "1" ]; then printf '   $ %s\n' "$*"; else "$@"; fi; }

preflight() {
  local missing=0
  for f in "$SCRIPTS/make_field_masks.py" "$SCRIPTS/make_crop_inputs.py" \
           "$SCRIPTS/paste_crop_results.py" "$SCRIPTS/validate_cases.py" \
           "$SCRIPTS/run_resident.py" "$CASES/probe-v2-all.jsonl" \
           "$CASES/jamo-probe.jsonl" "$FONT"; do
    [ -e "$f" ] || { warn "missing: $f"; missing=1; }
  done
  # this script must run inside the container, where the app tree exists
  [ -d "${TEXTFLUX_APP_ROOT:-/opt/textflux/app}" ] || {
    warn "not inside the runtime container (no ${TEXTFLUX_APP_ROOT:-/opt/textflux/app})"; missing=1; }
  if [ "$DRY" != "1" ]; then
    "$PY" - <<'EOF' || missing=1
import sys
try:
    import torch
    if not torch.cuda.is_available():
        print("   !! CUDA not available; start the container with --gpus all", file=sys.stderr); sys.exit(1)
    print(f"   {torch.cuda.device_count()} GPU(s) visible")
except Exception as exc:
    print(f"   !! torch unusable: {exc}", file=sys.stderr); sys.exit(1)
EOF
  fi
  [ "$missing" = 0 ] || { echo; echo "preflight failed - fix the above and re-run"; exit 1; }
  mkdir -p "$LOGS"
  echo "preflight OK   (GPUS=$GPUS)"
}

# stage <suite> <manifest> <meta> <seeds> <steps> <guidance> <label>
stage() {
  local suite=$1 manifest=$2 meta=$3 seeds=$4 steps=$5 guidance=$6 label=$7
  say "$suite  ($label)"
  local n; n=$(grep -c . "$manifest" 2>/dev/null); n=${n:-0}
  echo "   $n case(s), seeds $seeds, steps $steps, guidance $guidance, $GPUS shard(s)"

  run "$PY" "$SCRIPTS/validate_cases.py" --manifest "$manifest" --input-root "$INPUTS" \
    || { warn "$suite: validation failed, skipping"; return 1; }

  local i pids=()
  for (( i=0; i<GPUS; i++ )); do
    if [ "$DRY" = "1" ]; then
      printf '   $ CUDA_VISIBLE_DEVICES=%s %s run_resident.py --suite %s --shard-index %s --shard-count %s ...\n' \
        "$i" "$PY" "$suite" "$i" "$GPUS"
      continue
    fi
    CUDA_VISIBLE_DEVICES="$i" "$PY" "$SCRIPTS/run_resident.py" \
      --manifest "$manifest" --input-root "$INPUTS" --bundle "$BUNDLE" \
      --suite "$suite" --checkpoint-id "$CKPT" --seeds "$seeds" \
      --steps "$steps" --guidance-scale "$guidance" \
      --shard-index "$i" --shard-count "$GPUS" \
      > "$LOGS/$suite.shard$i.log" 2>&1 &
    pids+=($!)
    [ "$STAGGER" -gt 0 ] && sleep "$STAGGER"
  done
  local p
  for p in "${pids[@]:-}"; do [ -n "$p" ] && wait "$p" || warn "$suite: a shard exited non-zero"; done

  run "$PY" "$SCRIPTS/paste_crop_results.py" --meta "$meta" --input-root "$INPUTS" \
    --bundle "$BUNDLE" --suite "$suite" --font "$FONT" || warn "$suite: review sheet failed"
}

preflight

say "building cropped + upscaled inputs"
run "$PY" "$SCRIPTS/make_crop_inputs.py" \
  --manifest "$CASES/probe-v2-all.jsonl" --input-root "$INPUTS" \
  --out-manifest "$CASES/sweep-main.jsonl" --meta "$CASES/sweep-main-meta.json" \
  --target-line-height 288 --context-x 4.5 --context-y 0.5 --max-megapixels 2.6 \
  --prefix crop3 || exit 1
run "$PY" "$SCRIPTS/make_field_masks.py" \
  --manifest "$CASES/jamo-probe.jsonl" --input-root "$INPUTS" --font "$FONT" \
  --out-manifest "$CASES/jamo-fit.jsonl" --suffix jfit || exit 1
run "$PY" "$SCRIPTS/make_crop_inputs.py" \
  --manifest "$CASES/jamo-fit.jsonl" --input-root "$INPUTS" \
  --out-manifest "$CASES/sweep-jamo.jsonl" --meta "$CASES/sweep-jamo-meta.json" \
  --target-line-height 288 --context-x 4.5 --context-y 0.5 --max-megapixels 2.6 \
  --prefix jcrop || exit 1

if [ "$DRY" != "1" ]; then
  grep -E "\"id\": ?\"($SUBSET)\"" "$CASES/sweep-main.jsonl" > "$CASES/sweep-subset.jsonl"
  [ -s "$CASES/sweep-subset.jsonl" ] || { warn "subset manifest empty - check SUBSET ids"; exit 1; }
fi

stage crop-probe-v3 "$CASES/sweep-main.jsonl"   "$CASES/sweep-main-meta.json" 42,43,44 30 30   "resolution 259px, context restored"
stage guid-15       "$CASES/sweep-subset.jsonl" "$CASES/sweep-main-meta.json" 42,43    30 15   "guidance 30 -> 15"
stage guid-7        "$CASES/sweep-subset.jsonl" "$CASES/sweep-main-meta.json" 42,43    30 7.5  "guidance 30 -> 7.5"
stage steps-50      "$CASES/sweep-subset.jsonl" "$CASES/sweep-main-meta.json" 42,43    50 30   "steps 30 -> 50"
stage jamo-probe-v1 "$CASES/sweep-jamo.jsonl"   "$CASES/sweep-jamo-meta.json" 42,43,44 30 30   "jamo minimal pairs"

say "summary"
printf '%-16s %8s %8s  %s\n' suite results sheet ''
for suite in crop-probe-v3 guid-15 guid-7 steps-50 jamo-probe-v1; do
  r=$(find "$LOGS/$suite" -name result.png 2>/dev/null | wc -l)
  s="$LOGS/$suite/review-sheet.png"
  printf '%-16s %8s  %s\n' "$suite" "$r" "$([ -f "$s" ] && echo "$s" || echo -)"
done
echo
echo "re-run this script any time; finished cases are skipped, unfinished ones resume."

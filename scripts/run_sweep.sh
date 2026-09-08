#!/usr/bin/env bash
# One-shot TextFlux probe sweep.
#
#   bash run_sweep.sh            run everything that has not run yet
#   DRY=1 bash run_sweep.sh      print what would run, touch nothing
#
# Stages are skipped when their run directory already exists, so it is safe to
# re-run after an interruption. Each stage writes its own log and its own
# review sheet; nothing is overwritten.

set -uo pipefail

BUNDLE="${BUNDLE:-/share/jacob/textflux_offline_bundle}"
BENCH="${BENCH:-$BUNDLE/textflux-korean-document-benchmark}"
INPUTS="${INPUTS:-$BUNDLE/private-inputs}"
FONT="${FONT:-$BUNDLE/textflux-korean-font-patch/fonts/NotoSansCJKkr-Regular.otf}"
IMAGE="${IMAGE:-textflux-offline:2026-08-25}"
CKPT="${CKPT:-yyyyyxie/textflux}"
SCRIPTS="$BENCH/scripts"
CASES="$BENCH/cases"
LOGS="$BUNDLE/runs"
DRY="${DRY:-0}"

# case subset used for the parameter stages: short Hangul, long Hangul,
# a Chinese control at identical geometry, and the amount field
SUBSET='len-hangul-2|len-hangul-4|len-hangul-5|ctl-chinese-4|risk-amount-usd'

say()  { printf '\n\033[1m== %s\033[0m\n' "$*"; }
warn() { printf '   !! %s\n' "$*" >&2; }

run() {
  if [ "$DRY" = "1" ]; then printf '   $ %s\n' "$*"; return 0; fi
  "$@"
}

inpy() {  # run a bundled python script inside the runtime image
  if [ "${NO_DOCKER:-0}" = "1" ]; then run python3 "$@"; return $?; fi
  run sudo docker run --rm --network none -v /share:/share \
    --entrypoint python "$IMAGE" "$@"
}

preflight() {
  local missing=0
  for f in "$SCRIPTS/make_field_masks.py" "$SCRIPTS/make_crop_inputs.py" \
           "$SCRIPTS/paste_crop_results.py" "$SCRIPTS/validate_cases.py" \
           "$SCRIPTS/run_suite.py" "$CASES/probe-v2-all.jsonl" \
           "$CASES/jamo-probe.jsonl" "$FONT"; do
    [ -e "$f" ] || { warn "missing: $f"; missing=1; }
  done
  if ! grep -q 'guidance-scale' "$SCRIPTS/run_suite.py" 2>/dev/null; then
    warn "run_suite.py has no --guidance-scale; copy the patched version over first"
    missing=1
  fi
  if [ "$DRY" != "1" ] && [ "${NO_DOCKER:-0}" != "1" ]; then
    sudo docker image inspect "$IMAGE" >/dev/null 2>&1 || { warn "docker image not loaded: $IMAGE"; missing=1; }
  fi
  [ "$missing" = 0 ] || { echo; echo "preflight failed - fix the above and re-run"; exit 1; }
  mkdir -p "$LOGS"
  echo "preflight OK"
}

# stage <suite> <manifest> <meta> <seeds> <steps> <guidance> <label>
stage() {
  local suite=$1 manifest=$2 meta=$3 seeds=$4 steps=$5 guidance=$6 label=$7
  say "$suite  ($label)"
  if [ -d "$LOGS/$suite" ]; then echo "   already run, skipping"; return 0; fi
  local n; n=$(grep -c . "$manifest" 2>/dev/null); n=${n:-0}
  local total=$(( n * $(echo "$seeds" | tr ',' ' ' | wc -w) ))
  echo "   $n case(s), seeds $seeds, steps $steps, guidance $guidance  -> $total run(s)"

  inpy "$SCRIPTS/validate_cases.py" --manifest "$manifest" --input-root "$INPUTS" \
    || { warn "$suite: validation failed, skipping"; return 1; }

  run python3 "$SCRIPTS/run_suite.py" \
    --manifest "$manifest" --input-root "$INPUTS" --bundle "$BUNDLE" --font "$FONT" \
    --suite "$suite" --checkpoint-id "$CKPT" --seeds "$seeds" --steps "$steps" \
    --guidance-scale "$guidance" > "$LOGS/$suite.log" 2>&1
  local rc=$?
  [ $rc -eq 0 ] || warn "$suite: run_suite exited $rc (see $LOGS/$suite.log); continuing"

  inpy "$SCRIPTS/paste_crop_results.py" --meta "$meta" --input-root "$INPUTS" \
    --bundle "$BUNDLE" --suite "$suite" --font "$FONT" \
    || warn "$suite: review sheet failed"
  [ "$DRY" = "1" ] || run sudo chown -R "$(id -u):$(id -g)" "$LOGS/$suite" 2>/dev/null
}

preflight

# ---------------------------------------------------------------- inputs
say "building cropped + upscaled inputs"
# main set: masks are already aspect-fitted, so only crop+upscale is needed
inpy "$SCRIPTS/make_crop_inputs.py" \
  --manifest "$CASES/probe-v2-all.jsonl" --input-root "$INPUTS" \
  --out-manifest "$CASES/sweep-main.jsonl" --meta "$CASES/sweep-main-meta.json" \
  --target-line-height 288 --context-x 4.5 --context-y 0.5 --max-megapixels 2.6 \
  --prefix crop3 || exit 1

# jamo probe: raw text needs the aspect-fitting pass first
inpy "$SCRIPTS/make_field_masks.py" \
  --manifest "$CASES/jamo-probe.jsonl" --input-root "$INPUTS" --font "$FONT" \
  --out-manifest "$CASES/jamo-fit.jsonl" --suffix jfit || exit 1
inpy "$SCRIPTS/make_crop_inputs.py" \
  --manifest "$CASES/jamo-fit.jsonl" --input-root "$INPUTS" \
  --out-manifest "$CASES/sweep-jamo.jsonl" --meta "$CASES/sweep-jamo-meta.json" \
  --target-line-height 288 --context-x 4.5 --context-y 0.5 --max-megapixels 2.6 \
  --prefix jcrop || exit 1

if [ "$DRY" != "1" ]; then
  # json.dumps writes '"id": "x"', so tolerate the space
  grep -E "\"id\": ?\"($SUBSET)\"" "$CASES/sweep-main.jsonl" > "$CASES/sweep-subset.jsonl"
  [ -s "$CASES/sweep-subset.jsonl" ] || { warn "subset manifest came out empty - check SUBSET ids"; exit 1; }
  sudo chown -R "$(id -u):$(id -g)" "$INPUTS" "$CASES" 2>/dev/null
fi

# ---------------------------------------------------------------- stages
stage crop-probe-v3   "$CASES/sweep-main.jsonl"   "$CASES/sweep-main-meta.json" 42,43,44 30 30   "resolution 259px, context restored"
stage guid-15         "$CASES/sweep-subset.jsonl" "$CASES/sweep-main-meta.json" 42,43    30 15   "guidance 30 -> 15"
stage guid-7          "$CASES/sweep-subset.jsonl" "$CASES/sweep-main-meta.json" 42,43    30 7.5  "guidance 30 -> 7.5"
stage steps-50        "$CASES/sweep-subset.jsonl" "$CASES/sweep-main-meta.json" 42,43    50 30   "steps 30 -> 50"
stage jamo-probe-v1   "$CASES/sweep-jamo.jsonl"   "$CASES/sweep-jamo-meta.json" 42,43,44 30 30   "jamo minimal pairs"

# ---------------------------------------------------------------- summary
say "summary"
printf '%-18s %8s %8s  %s\n' suite done errors sheet
for suite in crop-probe-v3 guid-15 guid-7 steps-50 jamo-probe-v1; do
  log="$LOGS/$suite.log"; sheet="$LOGS/$suite/review-sheet.png"
  d=$(grep -c '^DONE' "$log" 2>/dev/null); d=${d:-0}
  e=$(grep -c '^ERROR' "$log" 2>/dev/null); e=${e:-0}
  printf '%-18s %8s %8s  %s\n' "$suite" "$d" "$e" "$([ -f "$sheet" ] && echo "$sheet" || echo -)"
done
echo
echo "review sheets are the files to look at; one PNG per suite."

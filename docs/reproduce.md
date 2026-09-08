# 재현 절차

이 저장소의 측정을 다시 돌리는 방법. 모든 경로는 환경 변수로 받으므로 배치 위치에 의존하지 않는다.

파이프라인 이해가 먼저 필요하면 [pipeline.md](pipeline.md)를,
파라미터 값의 근거는 [decision-log.md](decision-log.md)를 본다.

---

## 0. 전제

| 항목 | 내용 |
| --- | --- |
| 런타임 | TextFlux 소스와 diffusers가 설치된 컨테이너 이미지. 구성은 `textflux-airgap-runtime` 참조 |
| 모델 | `flux-fill-dev/`(diffusers 형식, T5 포함)와 `textflux/` 체크포인트 |
| 폰트 | 한글 글리프를 가진 OTF/TTF. 측정에는 Noto Sans CJK KR Regular 사용 |
| GPU | bf16 파이프라인 약 32 GiB. 병렬 실행 시 GPU당 그만큼 |
| 입력 | 서식지 이미지 + 필드 마스크. `examples/demo-inputs/`로 시작할 수 있다 |

폰트는 컨테이너의 `resource/font/Arial-Unicode-Regular.ttf` 위에 덮어 마운트한다.
업스트림이 그 경로를 **작업 디렉터리 기준 상대 경로**로 읽으므로,
실행 시 작업 디렉터리를 애플리케이션 루트(`/opt/textflux/app`)로 고정해야 한다.
고정하지 않으면 오류 없이 기본 폰트로 대체되어 한글만 깨진다.

---

## 1. 환경 변수

```bash
export BENCH=/path/to/textflux-korean-document-benchmark
export INPUTS=/path/to/private-inputs          # 서식지·마스크. Git 밖에 둔다
export OUTPUT=/path/to/output-root             # runs/ 가 생길 위치
export FONT=/path/to/NotoSansCJKkr-Regular.otf
export IMAGE=textflux-offline:2026-08-25       # 런타임 이미지 태그
```

`config/benchmark.env.example`을 복사해 쓸 수도 있다.
셸을 새로 열면 다시 설정해야 한다 — 변수가 비어 있으면 경로가 잘린 채 실행되어
`No such file or directory`가 엉뚱한 위치를 가리킨다.

입력 디렉터리 구조:

```text
$INPUTS/
├── forms/
│   └── demo_foreign_exchange_form.png
└── masks/
    ├── demo_name.png
    ├── demo_purpose.png
    ├── demo_date.png
    └── demo_amount.png
```

데모 입력으로 시작하려면:

```bash
mkdir -p "$INPUTS" && cp -a "$BENCH/examples/demo-inputs/." "$INPUTS/"
```

---

## 2. 마스크 종횡비 맞춤

각 문구를 실제 폰트로 렌더해 잉크 종횡비를 재고, 필드 높이를 유지한 채 폭만 맞춘다.

```bash
python "$BENCH/scripts/make_field_masks.py" \
  --manifest "$BENCH/cases/jamo-probe.jsonl" \
  --input-root "$INPUTS" \
  --font "$FONT" \
  --out-manifest "$BENCH/cases/jamo-fit.jsonl" \
  --suffix jfit
```

출력 표의 `was` → `now` 열이 종횡비 변화다. `CLAMPED`는 문자열이 인쇄된 칸보다 길어
칸 전체 폭으로 고정됐다는 뜻이며 정상 동작이다.

`cases/probe-v2a-scan.jsonl`, `cases/probe-v2b-highrisk.jsonl`도 같은 방식으로 처리한다.

---

## 3. 크롭·확대

필드 주변만 잘라 확대한 입력을 만든다. 원본은 건드리지 않고 새 파일을 쓴다.

```bash
python "$BENCH/scripts/make_crop_inputs.py" \
  --manifest "$BENCH/cases/jamo-fit.jsonl" \
  --input-root "$INPUTS" \
  --out-manifest "$BENCH/cases/jamo-crop.jsonl" \
  --meta "$BENCH/cases/jamo-crop-meta.json" \
  --target-line-height 288 \
  --context-x 4.5 \
  --context-y 0.5 \
  --max-megapixels 2.6 \
  --prefix jcrop
```

출력 표의 `latent` 열이 잠재 세로 행 수다. **16 전후가 나오면 정상**이다.
5에 가깝게 나오면 확대가 걸리지 않은 것이니 `--max-megapixels`를 확인한다.

`--meta`가 만드는 JSON은 크롭 좌표와 배율을 담고 있으며, 6단계 되붙이기에서 쓴다. **지우지 말 것.**

> **다른 서식으로 옮길 때는 `--context-x`를 다시 계산해야 한다.**
> 항목명 라벨이 크롭에 들어가야 스타일이 안정된다.
> `--dry-run`으로 크롭 폭을 먼저 확인하는 것이 안전하다. 근거는
> [decision-log.md](decision-log.md#--context-x-45--가장-중요한-값) 참조.

---

## 4. 검증

이미지·마스크의 크기 일치, 이진성, 경로 안전성을 확인한다. **실행 전에 반드시 통과시킨다.**

```bash
python "$BENCH/scripts/validate_cases.py" \
  --manifest "$BENCH/cases/jamo-crop.jsonl" \
  --input-root "$INPUTS"
```

```
VALIDATION PASSED: 16 case(s) checked
```

컨테이너 안에서 돌려도 되고 Pillow와 NumPy가 있는 호스트에서 돌려도 된다.

---

## 5. 실행

러너가 두 개다. 목적에 따라 고른다.

| | `run_suite.py` | `run_resident.py` |
| --- | --- | --- |
| 실행 위치 | 컨테이너 밖 (케이스마다 컨테이너 생성) | **컨테이너 안** |
| 모델 로드 | 케이스마다 | 샤드당 1회 |
| GPU | 1장 | N장 병렬 |
| 중단 후 재개 | **불가 — 전체 중단** | 케이스 단위 재개 |
| 실행 격리 | 강제하고 기록 | 기록만 |

**탐색·반복 측정은 `run_resident.py`, 최종 기록은 `run_suite.py`를 쓴다.**
두 러너의 결과를 한 표에 섞지 않는다 — `case.json`의 `provenance` 필드로 구분된다.

### 5-A. 상주 러너 (권장)

컨테이너 안에서 실행한다.

```bash
python "$BENCH/scripts/run_resident.py" \
  --manifest "$BENCH/cases/jamo-crop.jsonl" \
  --input-root "$INPUTS" \
  --bundle "$OUTPUT" \
  --suite jamo-probe-v1 \
  --checkpoint-id "yyyyyxie/textflux" \
  --seeds 42,43,44 \
  --steps 30 \
  --guidance-scale 30
```

GPU 4장 병렬:

```bash
for i in 0 1 2 3; do
  CUDA_VISIBLE_DEVICES=$i python "$BENCH/scripts/run_resident.py" \
    --manifest "$BENCH/cases/jamo-crop.jsonl" \
    --input-root "$INPUTS" --bundle "$OUTPUT" \
    --suite jamo-probe-v1 --seeds 42,43,44 \
    --shard-index $i --shard-count 4 \
    > "$OUTPUT/jamo-probe-v1.shard$i.log" 2>&1 &
  sleep 20
done
wait
```

`--shard-by case`가 기본이므로 한 케이스의 모든 시드가 한 GPU에 머문다.
시드 차이와 GPU 차이가 섞이지 않게 하기 위한 것이다.

`sleep 20`은 여러 샤드가 같은 가중치를 동시에 읽어 첫 로드가 느려지는 것을 막는다.

**중단되면 같은 명령을 다시 넣으면 된다.** 끝난 케이스는 건너뛰고 빠진 것만 채운다.

### 5-B. 순차 러너

```bash
python "$BENCH/scripts/run_suite.py" \
  --manifest "$BENCH/cases/jamo-crop.jsonl" \
  --input-root "$INPUTS" \
  --bundle "$OUTPUT" \
  --font "$FONT" \
  --suite jamo-probe-v1 \
  --checkpoint-id "yyyyyxie/textflux" \
  --seeds 42,43,44 \
  --steps 30 \
  --guidance-scale 30
```

`--suite` 이름은 재사용할 수 없다. 기존 디렉터리를 만나면 중단되므로 새 이름을 쓴다.

### 5-C. 스윕 일괄 실행

여러 조건을 한 번에 돌리려면 스윕 스크립트를 쓴다.
단계 정의는 스크립트 상단에서 편집한다.

```bash
DRY=1 bash "$BENCH/scripts/run_sweep_resident.sh"    # 점검만
bash "$BENCH/scripts/run_sweep_resident.sh"          # 실행
```

`GPUS=2`처럼 GPU 수를 줄일 수 있다. `run_sweep.sh`는 순차 러너용 대응 스크립트다.

---

## 6. 판독

크롭·확대로 만든 결과는 원본 크기로 되돌리고, 판독용 대조 시트를 만든다.

```bash
python "$BENCH/scripts/paste_crop_results.py" \
  --meta "$BENCH/cases/jamo-crop-meta.json" \
  --input-root "$INPUTS" \
  --bundle "$OUTPUT" \
  --suite jamo-probe-v1 \
  --font "$FONT"
```

생성물:

| 파일 | 용도 |
| --- | --- |
| `$OUTPUT/runs/<suite>/review-sheet.png` | **판독용.** 요청 문구와 시드별 결과가 한 장에 |
| `<case>/<seed>/result_field.png` | 글자 판독용. 모델이 작업한 해상도 그대로 |
| `<case>/<seed>/result_full.png` | 원본 서식지에 되붙인 결과 |

### 판독 순서

1. **`outputs_my/rendered/rendered_0001.png`** — 조건 그림이 올바른지.
   여기서 글자가 깨졌으면 폰트나 렌더 문제이며 모델 능력과 무관하다.
2. **`result_field.png`** — 실제 출력 글자.
3. **`review-sheet.png`** — 케이스·시드 전체를 한눈에.

### 채점 기준

**문자열 완전 일치.** 부분 정확은 0으로 계산한다.
`금융기관` → `금융지관`은 4자 중 3자가 맞았지만 0점이다.

시드별로 따로 세어 `n/3` 형태로 기록한다.
1시드만 보면 계통적 결함과 샘플링 잡음을 구분할 수 없다.

---

## 7. 집계

사람이 전사한 결과를 CSV에 채우고 집계한다.

```bash
cp "$BENCH/reviews.template.csv" "$BENCH/reviews/jamo-probe-v1.csv"
# observed_text 열을 채운다

python "$BENCH/scripts/score_reviews.py" \
  --manifest "$BENCH/cases/jamo-crop.jsonl" \
  --reviews "$BENCH/reviews/jamo-probe-v1.csv" \
  --output "$BENCH/reviews/jamo-probe-v1-summary.json"
```

금액·통화·계좌·SWIFT·날짜는 전체 CER이 아니라 **완전 일치**로 따로 집계된다.

---

## 문제 해결

| 증상 | 원인 |
| --- | --- |
| 한글이 네모 상자로 나온다 | 폰트를 못 찾아 기본 폰트로 대체됐다. 작업 디렉터리를 애플리케이션 루트로 고정하고 폰트 마운트를 확인한다. **오류가 나지 않으므로 로그만으로는 안 보인다** |
| 경로가 `/masks/...`처럼 잘려 있다 | 환경 변수가 비어 있다. 1단계를 다시 실행한다 |
| `latent` 열이 5 근처다 | 확대가 걸리지 않았다. `--max-megapixels`를 확인한다 |
| 결과에 글자가 중복된다 | 캔버스가 3 MP를 넘었을 가능성. `--max-megapixels`를 2.6 이하로 |
| 색·굵기가 제멋대로다 | 크롭에 인쇄 텍스트가 없다. `--context-x`를 키워 라벨을 포함시킨다 |
| 병렬 실행 결과가 섞인다 | 샤드가 작업 디렉터리를 공유하고 있다. `run_resident.py`는 샤드별 디렉터리를 만든다 |
| `refusing to overwrite existing run` | `run_suite.py`는 재개를 지원하지 않는다. 새 `--suite` 이름을 쓰거나 `run_resident.py`로 전환한다 |

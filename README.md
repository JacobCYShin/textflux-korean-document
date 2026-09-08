# TextFlux 한국어 문서 필드 측정

TextFlux 체크포인트가 한국어 문서 서식의 기입란에 지정한 문구를 얼마나 정확히 써 넣는지
측정한 벤치마크와 그 기록이다. **학습은 수행하지 않았고, 입력 조건만 바꿔가며 정확도를 측정했다.**

TextFlux 프로젝트의 공식 배포물이 아니며, 독립적으로 만든 평가 도구다.
모델 가중치, 컨테이너 이미지, 문서 스캔, 생성 결과는 포함하지 않는다.

> **English abstract.** An independent measurement harness for TextFlux on Korean document
> fields, plus the record of what was measured. No training was performed; only input
> conditions were varied. Findings, parameter rationale, and reproduction steps are in
> `docs/`, written in Korean.

---

## 핵심 결과

정확도를 지배한 것은 모델의 한국어 능력이 아니라 **입력 기하 세 가지**였다.
세 조건을 교정하는 것만으로 난수 출력이 부분 정확으로 바뀌었다.

| 요인 | 교정 전 → 후 | 확인된 효과 |
| --- | --- | --- |
| 마스크 종횡비 | 8.8:1 박스에 2.9:1 글자 → 글자 수에 맞춤 | 종횡비 차 ≤ 0.3인 4건 중 3건 정확, ≥ 1.4인 3건 전부 실패 |
| 잠재 해상도 | 잠재 세로 5행 → 16행 | 겹받침 `몫값닭앉` 3/3, `ABCD` 3/3 |
| 주변 인쇄 문맥 | 항목명 라벨 포함 여부 | 제외 시 색·굵기 붕괴, 글자 중복 재현 |

교정 후 15케이스 × 3시드 (완전 일치 기준):

| 문자 종류 | 결과 |
| --- | --- |
| 겹받침 한글 4자 · 중국어 4자 · `USD` · `ABCD` | **3/3** |
| 한글 6자 | 2/3 |
| 한글 3자 | 1/3 |
| 한글 4·5·7자 | 0/3 |
| 금액 · 계좌 · 날짜 | **0/3** — 교정 전 전체 이미지에서는 16자 중 15자였다 (역행) |

**남은 한글 오류는 계통적이다.** 관측된 모든 오류가 세로모음에 가로획이 더해지는 한 방향이며
(`신→선`, `민→면`, `청→쳥`), 특정 음절에 집중된다. 시드에 무관하다.

자세한 수치와 자모 프로브 결과는 [docs/findings.md](docs/findings.md)에 있다.

---

## 읽는 순서

| 순서 | 문서 | 답하는 질문 |
| --- | --- | --- |
| 1 | [docs/pipeline.md](docs/pipeline.md) | 이 모델은 무엇을 받아 무엇을 하는가 |
| 2 | [docs/findings.md](docs/findings.md) | 무엇을 측정했고 결과가 어땠는가 |
| 3 | [docs/decision-log.md](docs/decision-log.md) | 파라미터가 왜 그 값인가, 어디서 막혔는가 |
| 4 | [docs/reproduce.md](docs/reproduce.md) | 어떻게 다시 돌리는가 |

**처음 보는 사람은 1번부터 읽는다.** 파이프라인 구조를 모르면 나머지 세 문서의 근거를 해석할 수 없다.
파라미터를 바꿀 계획이라면 3번을 반드시 읽는다 — 값의 출처가 거기에만 있다.

보조 문서:

| 문서 | 내용 |
| --- | --- |
| [docs/protocol.md](docs/protocol.md) | 측정 트랙 정의 (content / style) |
| [docs/input-spec.md](docs/input-spec.md) | 이미지·마스크·매니페스트 형식 요건 |
| [docs/style-conditioning-boundary.md](docs/style-conditioning-boundary.md) | 러너가 스타일 조건을 소비하지 않는 이유 |

---

## 저장소 구조

```text
scripts/
  make_field_masks.py      문구의 잉크 종횡비를 재서 마스크 폭을 맞춘다
  make_crop_inputs.py      필드 주변을 잘라 확대한 입력을 만든다
  validate_cases.py        크기·이진성·경로 검증. 실행 전 필수
  run_resident.py          컨테이너 안에서 파이프라인 1회 로드 후 순회. N-GPU 샤딩, 케이스 단위 재개
  run_suite.py             케이스마다 컨테이너를 생성하는 순차 러너
  run_sweep_resident.sh    상주 러너용 다단계 스윕
  run_sweep.sh             순차 러너용 다단계 스윕
  paste_crop_results.py    결과를 원본 크기로 되붙이고 판독 시트를 만든다
  score_reviews.py         전사 결과를 필드별 완전 일치로 집계
  create_demo_assets.py    데모 서식지·마스크 생성

cases/
  jamo-probe.jsonl         자모 최소대립쌍 16종
  probe-v2a-scan.jsonl     한글 길이 계단 + 언어 대조
  probe-v2b-highrisk.jsonl 금액·계좌·SWIFT·날짜
  manifest.example.jsonl   매니페스트 형식 예시

examples/demo-inputs/      합성 서식지 1장 + 필드 마스크 4개. 모든 측정이 이것으로 수행됐다
results/                   측정 증거 이미지
tests/                     스크립트 스모크 테스트
config/                    환경 변수 예시
```

---

## 빠른 시작

```bash
export BENCH=$(pwd)
export INPUTS=/path/to/private-inputs
export FONT=/path/to/NotoSansCJKkr-Regular.otf

mkdir -p "$INPUTS" && cp -a "$BENCH/examples/demo-inputs/." "$INPUTS/"

python scripts/make_field_masks.py \
  --manifest cases/jamo-probe.jsonl --input-root "$INPUTS" \
  --font "$FONT" --out-manifest cases/jamo-fit.jsonl --suffix jfit

python scripts/make_crop_inputs.py \
  --manifest cases/jamo-fit.jsonl --input-root "$INPUTS" \
  --out-manifest cases/jamo-crop.jsonl --meta cases/jamo-crop-meta.json \
  --target-line-height 288 --context-x 4.5 --context-y 0.5 \
  --max-megapixels 2.6 --prefix jcrop

python scripts/validate_cases.py \
  --manifest cases/jamo-crop.jsonl --input-root "$INPUTS"
```

여기까지는 GPU 없이 돌아간다. Pillow와 NumPy만 필요하다.
추론 실행은 [docs/reproduce.md](docs/reproduce.md)를 따른다.

테스트:

```bash
python -m unittest discover -s tests
```

---

## 관련 저장소

세 저장소가 각각 다른 역할을 한다. **모델 가중치는 어디에도 없다.**

| 저장소 | 역할 | 규모 |
| --- | --- | --- |
| [`textflux-airgap-source`](https://github.com/JacobCYShin/textflux-airgap-source) | 상류 TextFlux 트리를 고정 커밋으로 떠놓은 스냅샷. 상류가 수정한 `diffusers` 포함. 상류에 접근할 수 없을 때의 fallback | 약 1,800개 파일 |
| [`textflux-airgap-runtime`](https://github.com/JacobCYShin/textflux-airgap-runtime) | 추론 이미지 빌드 자산. Dockerfile, 고정 의존성, 로컬 경로 러너, 준비 스크립트 | 12개 파일 |
| **이 저장소** | 측정 도구와 측정 기록 | 약 37개 파일 |

```text
textflux-airgap-source              상류 트리, 커밋 c791924… 고정
        │
        │   fetch_textflux_source.sh
        │   상류를 먼저 시도하고, 실패하면 이 스냅샷으로
        ▼
textflux-airgap-runtime             Dockerfile COPY → 실행 가능한 이미지
        │
        │   이 이미지를 벤치마크가 실행한다
        ▼
이 저장소                            측정 · 판독 · 결과 기록
```

스냅샷에는 상류 히스토리가 없다. 해당 커밋 시점의 파일 트리이고, 고정값은
`UPSTREAM_REVISION` 파일에 기록되어 있다. fallback 시 커밋 체크아웃이 불가능하므로
fetch 스크립트가 그 파일을 검증한다.

체크포인트는 `assembly/scripts/download_models.py`가 별도로 받아 Git 밖에 둔다.

- `black-forest-labs/FLUX.1-Fill-dev@358293da0354175698b67ec8299acf928313a78a`
- `yyyyyxie/textflux@8930419673bacf8716eb54a79632a5ec5a8b9862`

`docs/pipeline.md`와 `docs/decision-log.md`의 코드 참조는 위 고정 커밋 기준이다.

**처음 보는 사람의 읽는 순서: 이 저장소 → runtime → source.**
이 저장소에서 무엇을 측정했고 무엇을 안 했는지 파악하고, 실행 환경을 다시 만들어야 할 때
runtime을, 코드 동작을 파고들 때 source를 본다.

---

## 측정 범위

**측정한 것** — 지정한 문구를 정확히 써 넣는 능력. 한글·한자·라틴·숫자·기호.
마스크 종횡비, 잠재 해상도, 주변 문맥, `guidance-scale`, `steps`의 영향.

**측정하지 않은 것**

| 항목 | 이유 |
| --- | --- |
| 손글씨 스타일 전이 | 러너에 스타일 조건 입력 경로가 없다. 매니페스트의 `style_reference`는 기록용이며 소비되지 않는다 |
| 실제 업무 서식 기준 성능 | 모든 측정은 `examples/demo-inputs/`의 합성 서식지로 수행했다 |
| 캔버스 종횡비 상한 효과 | 숫자 필드 역행의 유력 가설이나 실험하지 않았다 |
| `textflux-beta` 체크포인트 | 원본 `yyyyyxie/textflux`만 사용했다 |
| 다중 행 경로 | 단일 행 경로만 사용했다. 다중 행은 자간·회전 처리가 달라 결과를 전용할 수 없다 |

**모든 수치는 합성 데모 서식지 기준이다.** 실제 서식의 괘선 밀도·인쇄 품질·필드 크기가 다르면
결과가 달라질 수 있다.

---

## 라이선스

Apache-2.0. `LICENSE` 참조.
이 저장소는 평가 도구와 측정 기록만 담으며, 모델 가중치나 그 라이선스를 포함하지 않는다.

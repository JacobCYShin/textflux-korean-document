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
| 1 | [docs/getting-started.md](docs/getting-started.md) | **추론을 한 번 돌려보려면** · 저장소와 워크스페이스는 무엇이 다른가 |
| 2 | [docs/pipeline.md](docs/pipeline.md) | 이 모델은 무엇을 받아 무엇을 하는가 |
| 3 | [docs/findings.md](docs/findings.md) | 무엇을 측정했고 결과가 어땠는가 |
| 4 | [docs/decision-log.md](docs/decision-log.md) | 파라미터가 왜 그 값인가, 어디서 막혔는가 |
| 5 | [docs/reproduce.md](docs/reproduce.md) | 측정을 어떻게 다시 돌리는가 |

**손을 대볼 사람은 1번, 결과를 알고 싶은 사람은 3번부터 읽는다.**
2번을 모르면 3·4번의 근거를 해석할 수 없다.
파라미터를 바꿀 계획이라면 4번을 반드시 읽는다 — 값의 출처가 거기에만 있다.

이전 구조(저장소 3개)에서 넘어오는 경우 [docs/migration.md](docs/migration.md)를 따른다.

보조 문서:

| 문서 | 내용 |
| --- | --- |
| [docs/protocol.md](docs/protocol.md) | 측정 트랙 정의 (content / style) |
| [docs/input-spec.md](docs/input-spec.md) | 이미지·마스크·매니페스트 형식 요건 |
| [docs/style-conditioning-boundary.md](docs/style-conditioning-boundary.md) | 러너가 스타일 조건을 소비하지 않는 이유 |

---

## 저장소 구조

```text
docs/                      측정 기록과 절차 문서
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

runtime/                   추론 이미지 빌드 자산
  Dockerfile               빌드 컨텍스트는 저장소 루트
  offline_infer.py         상류의 허브 참조를 로컬 경로로 대체하는 러너
  requirements-runtime.txt 추론 의존성 (버전 고정)
  scripts/                 모델 다운로드 · payload 검증 · 빌드 · 오프라인 스모크

vendor/textflux/           상류 TextFlux 코드 스냅샷 (커밋 c791924…)
                           상류가 수정한 diffusers 트리 포함. 직접 수정하지 않는다
```

**모델 가중치·실행 결과·서식지는 이 저장소에 없다.** 워크스페이스에 둔다.
경계와 판정 기준은 [docs/getting-started.md](docs/getting-started.md#새로-만든-산출물은-어디에-두는가)에 있다.

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

## 이전 저장소

이 저장소는 원래 셋으로 나뉘어 있었다. 하나로 합쳤고, 이전 것들은 아카이브했다.

| 이전 저장소 | 현재 위치 |
| --- | --- |
| `textflux-airgap-runtime` | `runtime/` |
| `textflux-airgap-source` | `vendor/textflux/` |
| `textflux-korean-document-benchmark` | 이 저장소 루트 |

합친 이유는 셋 중 어느 것도 독립적으로 소비되거나 버전이 매겨지지 않았고,
`runtime`의 Dockerfile이 `source`의 디렉터리를 필요로 하는 **암묵적 의존**이 있어
저장소 하나만 클론해서는 빌드가 되지 않았기 때문이다.
지금은 `COPY vendor/textflux/`가 저장소 내부 경로이므로 클론 하나로 빌드된다.

기존 클론에서 넘어오려면 [docs/migration.md](docs/migration.md)를 따른다.

## 모델 가중치

세 저장소 어디에도 없었고 지금도 없다. `runtime/scripts/download_models.py`가
받아 워크스페이스에 둔다.

- `black-forest-labs/FLUX.1-Fill-dev@358293da0354175698b67ec8299acf928313a78a`
- `yyyyyxie/textflux@8930419673bacf8716eb54a79632a5ec5a8b9862`

`docs/pipeline.md`와 `docs/decision-log.md`의 코드 참조는
`vendor/textflux/UPSTREAM_REVISION`에 기록된 커밋 기준이다.

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

`vendor/`를 제외한 모든 내용은 Apache-2.0이다. `LICENSE` 참조.

`vendor/textflux/`는 상류 TextFlux의 스냅샷이며 자체 라이선스 파일을 그대로 보존한다
(`LICENSE`, `LICENSE-MODEL`, `NOTICE`). 구분과 출처는 루트 [NOTICE](NOTICE)에 정리했다.

모델 가중치는 이 저장소에 없으며, 그 라이선스와 접근 조건은 배포처가 정한다.

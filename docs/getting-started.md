# 시작하기

처음 온 사람이 **추론 1회를 성공시키는 것**까지가 이 문서의 범위다.
측정은 그다음이며 [reproduce.md](reproduce.md)가 다룬다.

---

## 먼저 이해할 것 — 저장소와 워크스페이스는 다르다

이 프로젝트는 두 가지를 명확히 나눈다. **섞으면 반드시 헷갈린다.**

| | 저장소 (repo) | 워크스페이스 (workspace) |
| --- | --- | --- |
| 무엇 | 코드·문서·테스트 케이스 | 모델 가중치·입력·실행 결과 |
| 크기 | 약 70 MB | 54 GiB 이상 |
| 버전 관리 | Git | **하지 않음** |
| 얻는 방법 | `git clone` | 별도 다운로드 또는 기존 것 사용 |
| 예 | `docs/` `scripts/` `runtime/` `vendor/` | `payload/` `private-inputs/` `runs/` `deliverable/` |

모든 스크립트가 이 둘을 **별도 인자로** 받는다. 한 디렉터리에 둘 수도 있지만,
나눠 두는 것이 클론 하나로 코드를 받고 54 GiB는 그대로 두는 유일한 방법이다.

```text
<repo>/                        git clone 으로 얻는 것
├── docs/  scripts/  cases/  examples/  results/  tests/  config/
├── runtime/                   이미지 빌드 자산
│   ├── Dockerfile
│   ├── offline_infer.py       로컬 경로 러너
│   ├── requirements-runtime.txt
│   └── scripts/               다운로드 · 검증 · 빌드 · 스모크
└── vendor/textflux/           상류 코드 스냅샷 (고정 커밋)

<workspace>/                   Git 대상 아님
├── payload/
│   ├── flux-fill-dev/         31.59 GiB
│   └── textflux/              22.17 GiB
├── deliverable/               이미지 tar · 체크섬 · 스모크 결과
├── private-inputs/            서식지 · 마스크
├── runs/                      실행 결과
└── fonts/                     한글 폰트
```

---

## 어느 경로인가

| 상황 | 따를 절차 |
| --- | --- |
| 이미지가 이미 로드되어 있고 `payload/`도 있다 | **경로 A** — 5분 |
| 아무것도 없다. 모델부터 받아야 한다 | **경로 B** — 반나절 |

기존 머신을 인수받았다면 대개 경로 A다. 먼저 확인한다.

```bash
docker image ls | grep textflux
ls <workspace>/payload/flux-fill-dev/model_index.json
```

둘 다 있으면 경로 A.

---

## 경로 A — 이미 구축된 환경에서 첫 추론

### A-1. 환경 변수

```bash
export BENCH=/path/to/this/repo
export WORKSPACE=/path/to/workspace
export TEXTFLUX_MODEL_ROOT="$WORKSPACE/payload"
export FONT="$WORKSPACE/fonts/NotoSansCJKkr-Regular.otf"
export IMAGE=textflux-offline:2026-08-25
```

`config/benchmark.env.example`을 복사해 쓰면 된다. **셸을 새로 열면 다시 설정해야 한다.**
변수가 비어 있으면 경로가 잘린 채 실행되어 엉뚱한 위치를 가리키는 오류가 난다.

### A-2. 스모크 테스트 — 환경이 도는지만 확인

```bash
bash "$BENCH/runtime/scripts/offline_smoke_test.sh" \
  --workspace "$WORKSPACE" \
  --model-root "$TEXTFLUX_MODEL_ROOT"
```

이미지에 내장된 예제 입력을 쓰므로 벤치마크 데이터가 필요 없다.
네트워크를 차단(`--network none`)한 상태로 돌기 때문에, PNG가 하나 나오면
**오프라인 추론이 성립한다는 증명**이 된다.

```
Offline inference confirmed: <workspace>/deliverable/offline-smoke/textflux-offline-smoke.png
```

> 이 단계는 **"환경이 도는가"만** 확인한다. 예제가 중국어 간판이라
> 한국어 문서 성능과는 무관하다. 이 결과로 모델 품질을 판단하면 안 된다.
> 두 질문을 분리하지 않아 초기에 이틀을 잃었다 —
> [decision-log.md](decision-log.md#조건이-목적과-무관한-상태로-판단하려-한-것) 참조.

### A-3. 한글이 실제로 나오는지 확인

스모크 테스트는 중국어라 한글 폰트 문제를 잡지 못한다. 한글로 한 번 더 돌린다.

```bash
mkdir -p "$WORKSPACE/private-inputs"
cp -a "$BENCH/examples/demo-inputs/." "$WORKSPACE/private-inputs/"
printf '금융기관\n' > /tmp/words.txt

docker run --rm --network none --gpus all \
  -v "$WORKSPACE":"$WORKSPACE" \
  -v /tmp/words.txt:/tmp/words.txt:ro \
  -v "$FONT":/opt/textflux/app/resource/font/Arial-Unicode-Regular.ttf:ro \
  -w /opt/textflux/app \
  -e TEXTFLUX_MODEL_ROOT="$TEXTFLUX_MODEL_ROOT" \
  "$IMAGE" \
  --image "$WORKSPACE/private-inputs/forms/demo_foreign_exchange_form.png" \
  --mask  "$WORKSPACE/private-inputs/masks/demo_name.png" \
  --words /tmp/words.txt \
  --output "$WORKSPACE/deliverable/hangul-check.png" \
  --steps 30 --seed 42
```

**세 옵션이 필수다.** 빼면 조용히 잘못 동작한다.

| 옵션 | 없으면 |
| --- | --- |
| 폰트 마운트 | 한글이 네모 상자로 렌더된다 |
| `-w /opt/textflux/app` | 폰트를 상대 경로로 찾다 실패하고 **오류 없이** 기본 폰트로 대체된다 |
| `-e TEXTFLUX_MODEL_ROOT` | 모델을 찾지 못한다 |

확인은 결과 이미지가 아니라 **조건 그림**을 먼저 본다.

```bash
ls /opt/textflux/app/outputs_my/rendered/   # 컨테이너 안 경로
```

컨테이너가 끝나면 사라지므로, 남겨서 보려면 `outputs_my`를 마운트한다.
`scripts/run_resident.py`와 `run_suite.py`가 그 작업을 대신 해준다 —
A-4로 넘어가는 편이 빠르다.

> `rendered_0001.png`에 `금융기관`이 또렷하게 보이면 폰트·경로가 정상이다.
> 여기서 깨졌으면 모델 문제가 아니다.

### A-4. 벤치마크로 넘어가기

여기까지 되면 환경 검증은 끝이다. [reproduce.md](reproduce.md)로 간다.

---

## 경로 B — 처음부터 구축

네트워크가 되는 머신에서 준비하고 결과물을 대상 머신으로 옮긴다.

### B-1. 상류 소스 배치

저장소에 `vendor/textflux/`가 이미 들어 있으면 이 단계는 건너뛴다.
상류 핀을 올릴 때만 필요하다.

```bash
bash "$BENCH/runtime/scripts/fetch_textflux_source.sh" "$BENCH"
```

상류를 먼저 시도하고, 접근이 안 되면 스냅샷 미러로 넘어간다.
미러는 상류 히스토리가 없으므로 `UPSTREAM_REVISION` 값으로 핀을 검증한다.

### B-2. 모델 다운로드

Hugging Face 읽기 토큰이 필요하다. FLUX.1-Fill-dev는 라이선스 동의가 선행된다.

```bash
python "$BENCH/runtime/scripts/download_models.py" \
  --bundle-root "$WORKSPACE" --only all
```

재개 가능하다. 총 약 54 GiB.

| 받는 것 | 크기 |
| --- | --- |
| `payload/flux-fill-dev/` (diffusers 형식) | 31.59 GiB |
| `payload/textflux/` | 22.17 GiB |

**`text_encoder_2`(T5-XXL, 9.5 GiB)가 반드시 포함되어야 한다.**
루트의 단일 파일 `flux1-fill-dev.safetensors`는 transformer만 담고 있어
그것만 받으면 파이프라인이 뜨지 않는다. 다운로드 스크립트가 diffusers 형식만 선택한다.

### B-3. 구성 검증

```bash
python "$BENCH/runtime/scripts/verify_payload.py" \
  --bundle-root "$WORKSPACE" --sha256 \
  --output "$WORKSPACE/deliverable/payload-manifest.sha256.json"
```

`model_index.json`의 7개 구성요소가 모두 있는지 확인한다.

### B-4. 이미지 빌드

```bash
bash "$BENCH/runtime/scripts/build_and_export.sh" \
  --repo "$BENCH" --workspace "$WORKSPACE"
```

빌드 컨텍스트는 저장소 루트이고 약 48 MB다.
`payload/`는 `.dockerignore`로 제외되므로 **가중치가 이미지 레이어에 들어가지 않는다.**
결과는 `<workspace>/deliverable/`에 tar와 SHA-256으로 남는다.

### B-5. 대상 머신에서 적재

```bash
cd "$WORKSPACE/deliverable"
sha256sum -c textflux-offline_2026-08-25.tar.sha256
docker load -i textflux-offline_2026-08-25.tar
```

이후 경로 A-2로 간다.

---

## 새로 만든 산출물은 어디에 두는가

작업을 이어가며 만드는 것들의 자리다. **이 규칙을 지키지 않으면 저장소가 다시 뒤섞인다.**

| 만든 것 | 위치 | 커밋? |
| --- | --- | --- |
| 측정 결과 해석·결론 | `docs/findings.md`에 추가 | ✅ |
| 파라미터를 새로 정한 근거 | `docs/decision-log.md`에 추가 | ✅ |
| 새 측정 스크립트 | `scripts/` | ✅ |
| 새 테스트 케이스 매니페스트 | `cases/*.jsonl` | ✅ |
| 판독 시트·증거 이미지 | `results/` + `results/README.md`에 설명 | ✅ |
| 이미지 빌드·의존성 변경 | `runtime/` | ✅ |
| 상류 코드 수정 | **하지 않는다.** 핀을 올리고 `vendor/`를 교체 | ✅ |
| 실행 결과 (`runs/`) | 워크스페이스 | ❌ 용량이 크고 재생성 가능 |
| 생성된 마스크·매니페스트 (`fit__`, `crop__`, `*-fit.jsonl`) | 워크스페이스 · `.gitignore` 처리됨 | ❌ 스크립트가 재생성 |
| 모델 가중치·이미지 tar | 워크스페이스 | ❌ 용량·라이선스 |
| 서식지·마스크 원본 | 워크스페이스 `private-inputs/` | ❌ 민감할 수 있음 |

판정 기준은 하나다. **스크립트로 재생성되거나 용량이 크거나 민감하면 워크스페이스, 사람이 쓴 것이면 저장소.**

예외가 하나 있다. `examples/demo-inputs/`의 합성 서식지는 스크립트로 생성되지만
**모든 측정의 기준 입력**이므로 커밋한다. 이것이 바뀌면 과거 수치와 비교할 수 없다.

---

## 자주 막히는 곳

| 증상 | 원인 |
| --- | --- |
| 한글이 네모 상자 | 폰트 마운트 누락 또는 작업 디렉터리 미고정. **오류가 나지 않는다** |
| `Missing FLUX T5 encoder` | `text_encoder_2`를 안 받았다. B-2를 다시 |
| 경로가 `/masks/...`처럼 잘림 | 환경 변수가 비어 있다 |
| `vendor/textflux is missing` | B-1을 실행한다 |
| `Not a repository checkout` | `--repo`가 저장소 루트를 가리키지 않는다 |
| 빌드 컨텍스트가 수 GB | `.dockerignore`가 적용되지 않았다. 저장소 루트에서 빌드하는지 확인 |

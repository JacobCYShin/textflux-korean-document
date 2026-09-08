# 기존 환경 정리

이전 구조(저장소 3개, 워크스페이스와 저장소가 한 디렉터리)에서
현재 구조(저장소 1개, 워크스페이스 분리)로 옮기는 절차다.

**원칙: 아무것도 옮기지 않는다. 추가하고, 검증하고, 중복만 지운다.**
54 GiB 가중치와 실행 결과는 제자리에 둔다. 검증 전에는 어떤 것도 삭제하지 않는다.

---

## 무엇이 바뀌었나

| 이전 | 현재 |
| --- | --- |
| `textflux-airgap-source` (저장소) | `vendor/textflux/` (통합 저장소 안) |
| `textflux-airgap-runtime` (저장소) | `runtime/` (통합 저장소 안) |
| `textflux-korean-document-benchmark` (저장소) | 통합 저장소 루트 |
| `$ROOT` 하나가 저장소와 워크스페이스 겸용 | `--repo` 와 `--workspace` 로 분리 |
| `COPY source/textflux/` | `COPY vendor/textflux/` |
| `COPY assembly/…` | `COPY runtime/…` |

**이미지를 다시 빌드할 필요는 없다.** 이미 적재된 `textflux-offline:2026-08-25`은
이미지 내부 경로(`/opt/textflux/app`)만 사용하므로 저장소 구조와 무관하다.
빌드 경로 변경은 다음에 이미지를 새로 만들 때부터 적용된다.

---

## 현재 상태 판정

`/share/jacob/textflux_offline_bundle/` 안의 항목을 두 부류로 나눈다.

| 항목 | 성격 | 처리 |
| --- | --- | --- |
| `assembly/` | 저장소 | 검증 후 삭제 → `runtime/`으로 대체됨 |
| `source/textflux/` | 저장소 | 검증 후 삭제 → `vendor/textflux/`로 대체됨 |
| `textflux-korean-document-benchmark/` | 저장소 | 검증 후 삭제 → 통합 저장소로 대체됨 |
| `payload/` (54 GiB) | **워크스페이스** | **그대로 둔다** |
| `runs/` (실행 결과) | **워크스페이스** | **그대로 둔다** |
| `private-inputs/` | **워크스페이스** | **그대로 둔다** |
| `deliverable/` (이미지 tar) | **워크스페이스** | **그대로 둔다** |
| `textflux-korean-font-patch/` | **워크스페이스** | **그대로 둔다** |

> **디렉터리 이름은 바꾸지 않는다.** `runs/*/case.json`에 절대 경로가 기록되어 있어,
> 이름을 바꾸면 과거 실행 기록이 존재하지 않는 경로를 가리키게 된다.
> `textflux_offline_bundle`은 이제 워크스페이스라는 뜻이며, 그 사실은 문서로 남긴다.

---

## 절차

### 0. 현재 상태 기록

되돌릴 필요가 생겼을 때의 기준점이다.

```bash
B=/share/jacob/textflux_offline_bundle
{ date; echo; ls -la "$B"; echo; du -sh "$B"/*; echo; find "$B/runs" -name result.png | wc -l; } \
  > ~/textflux-layout-before.txt
cat ~/textflux-layout-before.txt
```

### 1. 통합 저장소 반입

네트워크가 되는 머신에서 히스토리째 하나의 파일로 묶는다.

```bash
git clone https://github.com/JacobCYShin/textflux-korean-document-benchmark
cd textflux-korean-document-benchmark
git bundle create ~/textflux-repo.bundle --all
```

파일 하나(약 70 MB)를 대상 머신으로 옮긴 뒤 펼친다.

```bash
cd /share/jacob
git clone ~/textflux-repo.bundle textflux-korean-document
cd textflux-korean-document && git log --oneline -3
```

`git bundle`을 쓰면 커밋 히스토리가 보존된다. 단순 복사도 되지만 그 경우 이력이 사라진다.

### 2. 환경 변수 파일

```bash
cd /share/jacob/textflux-korean-document
cp config/benchmark.env.example config/benchmark.env
vi config/benchmark.env
```

기존 자산을 가리키도록 채운다.

```bash
BENCH=/share/jacob/textflux-korean-document
WORKSPACE=/share/jacob/textflux_offline_bundle
INPUTS=/share/jacob/textflux_offline_bundle/private-inputs
OUTPUT=/share/jacob/textflux_offline_bundle
MODEL_ROOT=/share/jacob/textflux_offline_bundle/payload
FONT=/share/jacob/textflux_offline_bundle/textflux-korean-font-patch/fonts/NotoSansCJKkr-Regular.otf
IMAGE=textflux-offline:2026-08-25
```

셸에 적용한다. **새 셸을 열 때마다 필요하다.**

```bash
set -a; . /share/jacob/textflux-korean-document/config/benchmark.env; set +a
echo "BENCH=[$BENCH] WORKSPACE=[$WORKSPACE]"
```

### 3. 검증 — 여기를 통과해야 삭제로 넘어간다

세 가지를 확인한다. **하나라도 실패하면 6단계로 가지 않는다.**

**3-1. 환경이 도는가**

```bash
bash "$BENCH/runtime/scripts/offline_smoke_test.sh" \
  --workspace "$WORKSPACE" --model-root "$MODEL_ROOT"
```

`Offline inference confirmed:` 로 끝나야 한다.

**3-2. 측정 도구가 도는가**

```bash
docker run --rm --network none -v /share:/share --entrypoint python "$IMAGE" \
  "$BENCH/scripts/validate_cases.py" \
  --manifest "$BENCH/examples/demo-manifest.jsonl" \
  --input-root "$INPUTS"
```

`VALIDATION PASSED: 4 case(s) checked`

**3-3. 과거 결과를 다시 읽을 수 있는가**

```bash
docker run --rm --network none -v /share:/share --entrypoint python "$IMAGE" \
  "$BENCH/scripts/paste_crop_results.py" \
  --meta "$WORKSPACE/textflux-korean-document-benchmark/cases/crop-meta-v3.json" \
  --input-root "$INPUTS" --bundle "$WORKSPACE" \
  --suite crop-probe-v3 --font "$FONT" --skip-paste \
  --sheet "$WORKSPACE/deliverable/migration-check.png"
```

`crop-meta-v3.json`은 아직 구 벤치마크 클론 안에 있다. 시트가 생성되면
**과거 실행 결과가 새 저장소의 도구로도 판독된다**는 뜻이다.

> 메타 파일은 크롭 좌표를 담고 있어 과거 결과 판독에 필요하다.
> 삭제 전에 `$WORKSPACE/cases-archive/`로 옮겨 보관한다 — 5단계.

### 4. 워크스페이스에 안내문 남기기

다음 사람이 이 디렉터리를 저장소로 착각하지 않도록 한다.

```bash
cat > "$WORKSPACE/README.md" <<'EOF'
# TextFlux 워크스페이스

이 디렉터리는 Git 저장소가 아니라 **머신 상태**를 담는다.
코드와 문서는 /share/jacob/textflux-korean-document 에 있다.

| 디렉터리 | 내용 |
| --- | --- |
| payload/ | 모델 가중치 54 GiB. flux-fill-dev/ 와 textflux/ |
| private-inputs/ | 서식지·마스크. 스크립트가 생성한 fit__ crop__ 마스크 포함 |
| runs/ | 실행 결과. case.json 에 설정과 절대 경로가 기록되어 있다 |
| deliverable/ | 이미지 tar·체크섬·스모크 결과 |
| textflux-korean-font-patch/ | 한글 폰트 |
| cases-archive/ | 과거 실행의 크롭 메타 파일. 결과 판독에 필요 |

디렉터리 이름을 바꾸지 말 것. runs/*/case.json 에 절대 경로가 남아 있다.

사용법: /share/jacob/textflux-korean-document/docs/getting-started.md
EOF
cat "$WORKSPACE/README.md"
```

### 5. 판독에 필요한 메타 파일 보존

구 벤치마크 클론을 지우기 전에, 과거 결과 판독에 필요한 파일만 빼둔다.

```bash
mkdir -p "$WORKSPACE/cases-archive"
OLD="$WORKSPACE/textflux-korean-document-benchmark"
cp "$OLD/cases/"*-meta*.json "$WORKSPACE/cases-archive/" 2>/dev/null || true
cp "$OLD/cases/"*.jsonl      "$WORKSPACE/cases-archive/" 2>/dev/null || true
ls -la "$WORKSPACE/cases-archive/"
```

이 파일들은 스크립트가 생성한 것이라 저장소에는 커밋하지 않는다.
다만 **과거 `runs/`를 다시 판독하려면 당시의 크롭 좌표가 필요**하므로 워크스페이스에 남긴다.

### 6. 중복 삭제

3단계를 전부 통과했고 5단계를 마쳤을 때만 진행한다.

```bash
B=/share/jacob/textflux_offline_bundle
du -sh "$B/assembly" "$B/source" "$B/textflux-korean-document-benchmark"

rm -rf "$B/assembly" \
       "$B/source" \
       "$B/textflux-korean-document-benchmark"
```

### 7. 최종 확인

```bash
echo "--- 워크스페이스 ---"; ls /share/jacob/textflux_offline_bundle
echo "--- 저장소 ---";       ls /share/jacob/textflux-korean-document
echo "--- 결과 보존 ---";    find /share/jacob/textflux_offline_bundle/runs -name result.png | wc -l
```

워크스페이스에 `payload` `runs` `private-inputs` `deliverable`
`textflux-korean-font-patch` `cases-archive` `README.md` 만 남고,
`result.png` 개수가 0단계 기록과 같으면 완료다.

---

## 되돌리기

6단계 전이라면 새로 만든 것만 지우면 원상태다.

```bash
rm -rf /share/jacob/textflux-korean-document
rm -f  /share/jacob/textflux_offline_bundle/README.md
rm -rf /share/jacob/textflux_offline_bundle/cases-archive
```

6단계 이후라면 삭제한 셋은 저장소에서 다시 얻을 수 있다.
`assembly/`는 `runtime/`, `source/textflux/`는 `vendor/textflux/`,
구 벤치마크 클론은 통합 저장소 루트에 그대로 대응한다.
**복구 불가능한 것은 없다** — 셋 다 저장소 내용이었고 워크스페이스는 건드리지 않았다.

---

## 이관 후 달라지는 명령

기존 문서나 메모에 남아 있는 명령은 경로가 바뀐다.

| 이전 | 현재 |
| --- | --- |
| `$BUNDLE/textflux-korean-document-benchmark/scripts/…` | `$BENCH/scripts/…` |
| `$BUNDLE/assembly/scripts/build_and_export.sh $BUNDLE` | `$BENCH/runtime/scripts/build_and_export.sh --repo $BENCH --workspace $WORKSPACE` |
| `$BUNDLE/assembly/scripts/offline_smoke_test.sh $BUNDLE` | `$BENCH/runtime/scripts/offline_smoke_test.sh --workspace $WORKSPACE` |
| `--bundle $BUNDLE` (측정 스크립트) | `--bundle $WORKSPACE` — 값은 같다 |

측정 스크립트의 `--bundle`은 `runs/`가 생길 위치이므로 워크스페이스를 가리킨다.
경로 문자열은 이전과 동일하다.

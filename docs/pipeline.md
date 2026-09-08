# 추론 파이프라인

TextFlux가 실제로 무엇을 받아 무엇을 하는지 정리한다. 이 문서의 내용을 모르면
[findings.md](findings.md)의 결과와 [decision-log.md](decision-log.md)의 파라미터 근거를 해석할 수 없다.

코드 위치는 `textflux-airgap-source` 저장소의 고정 커밋
`c791924acc4a93d48021c3731a75fada805cc501` 기준이다.

---

## 핵심 — 모델은 글자를 읽지 않는다

TextFlux는 "금융기관이라고 써라"라는 지시를 이해하지 않는다.
**금융기관이라는 글자를 그림으로 렌더링해 원본 위에 붙여 보여주고, 그 모양을 마스크 영역에 옮겨 그리게** 한다.
내부에 문자 인식(OCR) 경로가 없다. 논문이 스스로를 "OCR-Free"라 부르는 이유다.

따라서 **글자를 이해하는 능력이 아니라 그림을 옮기는 능력이 결과를 지배한다.**
조건 그림의 크기·비율·해상도가 정확도를 좌우하며, 관측된 실패는 대부분 여기서 비롯됐다.

---

## 입력과 출력

`offline_infer.py` 기준.

| 구분 | 인자 | 내용 |
| --- | --- | --- |
| 입력 | `--image` | 글자를 써 넣을 원본 이미지 (RGB) |
| 입력 | `--mask` | 흑백 이미지. **흰 부분만 재생성**, 검은 부분은 원본 보존 |
| 입력 | `--words` | 쓸 문구를 담은 UTF-8 텍스트 파일. 한 줄에 한 문구 |
| 설정 | `--steps` | 확산 스텝 수. 기본 30 |
| 설정 | `--guidance-scale` | 조건 추종 강도. 기본 30.0 |
| 설정 | `--seed` | 난수 시드 |
| 출력 | `--output` | 마스크 영역이 채워진 이미지. 나머지는 원본 유지 |

부가 산출물이 작업 디렉터리의 `outputs_my/` 아래에 남는다.

| 파일 | 내용 |
| --- | --- |
| `rendered/rendered_0001.png` | **글리프 띠.** 모델에 준 조건 그림. 여기서 글자가 깨졌으면 모델 문제가 아니다 |
| `mask/mask_0001.png` | 사용된 마스크 |
| `ori/ori_0001.png` | 원본 |
| `result_0001.png` | 띠를 포함한 전체 합성 결과 |
| `crop/crop_0001.png` | 띠를 잘라낸 결과 |

> **판독 시에는 `rendered_0001.png`를 먼저 본다.** 조건 그림 자체가 잘못됐는지 확인하기 전에는
> 출력 품질을 모델 능력으로 해석할 수 없다. 실제로 초기 실패 두 건이 조건 그림 단계의 문제였다.

---

## 흐름 6단계

```
                            words.txt        form.png       mask.png
                                |                |              |
  (1) 글리프 띠 렌더링 ─────────┤                |              |
      폰트로 검은 배경에         |                |              |
      흰 글자를 그림             v                |              |
                          glyph strip             |              |
                                |                |              |
  (2) 세로 결합 ────────────────┴────────────────┘              |
      vstack(strip, image)                                      |
      vstack(black, mask) ────────────────────────────────────── ┘
                                |
                          합성 캔버스 1장
                                |
  (3) VAE 인코더  ──────────────┤   가로·세로 각 1/8, 패치화로 추가 1/2 → 총 1/16
                                v
  (4) MMDiT 30스텝 ◄──── T5-XXL · CLIP (문구가 들어간 문장)
      TextFlux 체크포인트
                                |
  (5) VAE 디코더 ───────────────┤
                                v
  (6) 위쪽 띠를 잘라내고 반환 → result.png
```

**1·2·6번은 일반 이미지 처리 코드이고, 생성 모델은 3·4·5번에서만 관여한다.**

문구는 **두 경로로** 들어간다. 그림(글리프 띠)으로 한 번, 문장 속 텍스트로 한 번.
글자 모양을 결정하는 쪽은 그림이다.

### 1단계 — 글리프 띠 렌더링

`render_single_line_text()` / `draw_glyph_flexible()`

```python
text_height_ratio = 0.15625
text_render_height = int(w * text_height_ratio)   # w = 원본 이미지 '폭'
```

**띠 높이가 원본 이미지의 폭으로 결정된다.** 폭 1280px 이미지면 띠는 1280×200이 된다.
띠가 넓어지면 띠 높이도 같이 커지므로, 크롭 폭을 바꾸면 캔버스 전체 크기가 따라 움직인다.

글자는 띠 안에 중앙 정렬(`anchor='mm'`)되고, 폭·높이의 90%에 맞춰 자동 확대되며 상한이 걸린다.

```python
max_font_size = 140
if width > 1280:
    max_font_size = 200
```

폰트 경로는 **작업 디렉터리 기준 상대 경로**다.

```python
font = ImageFont.truetype("resource/font/Arial-Unicode-Regular.ttf", 60)   # run_inference.py:169
```

`except IOError`로 기본 폰트로 조용히 대체되므로, **경로를 못 찾아도 오류 없이 진행되고 한글만 깨진다.**
`outputs_my/` 역시 작업 디렉터리 기준이다(`run_inference.py:390`, `472~489`).
이 두 상대 경로가 병렬 실행과 폰트 문제의 원인이며, 자세한 경위는
[decision-log.md](decision-log.md#상대-경로-두-개가-만든-문제)에 있다.

### 2단계 — 세로 결합

`process_singleline_mode()`

```python
text_mask_pil  = Image.new("RGB", rendered_text.size, "black")   # 띠 영역은 편집 금지
combined_image = vstack(rendered_text, original_image)
combined_mask  = vstack(text_mask_pil,  mask_image)
```

띠에 대응하는 마스크는 완전 검은색이라 모델이 띠를 고치지 않는다.
**모델이 보는 것은 이 합성 캔버스 한 장이며, 위쪽 띠와 아래쪽 마스크 영역의 형태를 대응시켜야 한다.**

### 3~5단계 — 확산

`run_inference()`

```python
new_width  = (w // 32) * 32
new_height = (h // 32) * 32
```

**합성 캔버스를 32의 배수로 내림 반올림한다.** 미리 맞춰두지 않으면 여기서 재샘플링이 한 번 더 일어나
글자가 미세하게 눌린다. `make_crop_inputs.py`가 이걸 no-op으로 만드는 이유다.

프롬프트는 두 개로 갈라져 서로 다른 인코더로 간다.

```python
result = pipe(
    prompt   = prompt_template2,      # 문구 없는 일반형 → CLIP
    prompt_2 = generate_prompt(words) # 문구 포함        → T5-XXL
)
```

### 6단계 — 띠 잘라내기

```python
crop_top_edge = int(res_h * (text_render_height / (orig_h + text_render_height)))
cropped_result = full_result.crop((0, crop_top_edge, res_w, res_h))
```

비율로 계산하므로 32배수 반올림이 있었더라도 대략 맞게 잘린다.
그 결과 **반환 이미지 높이가 입력 이미지 높이와 몇 px 다를 수 있다.**
후처리에서 마스크 좌표를 쓸 때는 크기 비율로 보정해야 한다(`paste_crop_results.py`가 그렇게 한다).

---

## 거치는 모델 네 개

bf16 기준 합계 약 32 GiB가 GPU에 올라간다.

| 모델 | 크기 | 역할 |
| --- | --- | --- |
| **MMDiT 트랜스포머**<br>TextFlux 체크포인트 | 22.17 GiB | 실제로 그림을 그리는 본체. FLUX.1-Fill-dev의 transformer 자리에 갈아 끼운다. **이 교체가 TextFlux의 본질이다** |
| **T5-XXL v1.1**<br>`text_encoder_2` | 9.5 GiB | 문구가 들어간 긴 문장을 처리 |
| **CLIP ViT-L/14**<br>`text_encoder` | 250 MiB | 문구가 빠진 일반 안내문을 처리하는 보조 인코더 |
| **VAE** (`AutoencoderKL`) | 335 MiB | 이미지 ↔ 잠재 변환. **가로·세로를 각 1/8로 줄이고, 패치화가 추가로 1/2을 줄여 총 1/16이 된다** |

조립은 `offline_infer.py`가 한다.

```python
transformer = FluxTransformer2DModel.from_pretrained(textflux_model, torch_dtype=torch.bfloat16)
pipe = FluxFillPipeline.from_pretrained(flux_model, transformer=transformer, torch_dtype=torch.bfloat16)
textflux.PIPE = pipe                      # 업스트림의 허브 참조를 로컬 파이프라인으로 대체
textflux.process_normal_mode(...)          # 이미지·마스크·글리프 준비 로직은 업스트림 것을 그대로 사용
```

`text_encoder_2`(T5)를 빼먹으면 파이프라인이 뜨지 않는다. 모델 파일을 옮길 때 가장 자주 놓치는 부분이다.

---

## 모델에 실제로 전달되는 문장

`generate_prompt()`에 고정된 템플릿이며 문구만 채워진다.

```
The pair of images highlights some white words on a black background,
as well as their style on a real-world scene image.
[IMAGE1] is a template image rendering the text, with the words '금융기관';
[IMAGE2] shows the text content '금융기관' naturally and correspondingly
integrated into the image.
```

"위쪽은 글자를 그려둔 견본, 아래쪽은 그 글자가 장면에 자연스럽게 들어간 모습"이라는 뜻이다.
**즉 위아래 두 이미지의 관계를 알려주고 아래쪽 마스크 영역을 채우게 하는 구조다.**

`prompt`(CLIP)에는 문구가 들어가지 않고 `prompt_2`(T5)에만 들어간다.
문구 문자열이 실제로 전달됐는지 확인하려면 실행 로그의 `Generated prompt:` 줄을 본다.

---

## 스타일이 정해지는 방식

**TextFlux에는 스타일 인코더가 없다.** 마스크 밖 영역에서 글자체를 유추한다.

이 성질이 두 가지 결과를 낳는다.

1. **마스크 주변에 인쇄 텍스트가 없으면 참고할 스타일이 사라진다.** 색·굵기·효과가 제멋대로 나온다.
   측정에서 재현했다 — [findings.md](findings.md#3차-요인--주변-인쇄-텍스트-문맥) 참조.
2. **별도의 필체 레퍼런스를 넣을 경로가 없다.** 매니페스트의 `style_reference` 필드는
   기록용이며 러너가 읽지 않는다(`case.json`에 `style_reference_consumed: false`로 남는다).
   구조적 배경은 [style-conditioning-boundary.md](style-conditioning-boundary.md)에 있다.

---

## 단일 행과 다중 행

`process_normal_mode()`가 `--words` 파일의 줄 수로 분기한다.

| 줄 수 | 경로 | 글리프 조건 방식 |
| --- | --- | --- |
| 1줄 | `process_singleline_mode()` | 띠 하나를 위에 붙임 (`draw_glyph_flexible`) |
| 2줄 이상 | `process_multiline_mode()` | 마스크의 각 영역을 윤곽선으로 찾아 개별 렌더 (`render_glyph_multi` → `draw_glyph2`) |

이 저장소의 모든 측정은 **단일 행 경로**만 사용했다.
다중 행 경로는 자간 자동 삽입(`insert_spaces`)과 회전 처리가 들어가 동작이 다르므로,
단일 행 결과를 다중 행에 그대로 적용해서는 안 된다.

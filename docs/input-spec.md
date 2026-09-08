# Input Specification

## Data handling

Keep source documents, masks, style references, generated results, and review files outside Git. Strip personal, account, and transaction values before building a test set.

Recommended private layout:

```text
private-inputs/
  forms/
    form_001.png
  masks/
    form_001_name.png
  styles/
    form_003_reference_crop.png
```

The manifest paths are relative to `INPUT_ROOT`. Absolute paths and `..` segments are rejected.

## Source image

- Use a PNG, JPG, or JPEG scan or photograph representative of the target documents.
- Preserve the final orientation and approximate production resolution.
- Do not use the upstream Chinese signboard example for this benchmark.
- For content-only cases, use a target-like form and a target field. A blank field is acceptable.
- For handwriting-style cases, keep style evidence outside the target mask, or record a separate style reference. A blank form alone cannot establish a writer-specific style target, because the runner infers style from unmasked context only.

## Mask image

- The mask must have exactly the same pixel dimensions as the source image.
- Use black (`0`) outside the editable field and white (`255`) inside it.
- Cover all existing target text plus a small, documented margin. Do not crop parts of existing glyphs.
- Do not expand the mask across adjacent labels, ruled lines, stamps, or fields unless their regeneration is part of the test.
- Inspect the mask at 100% zoom before running inference.

The validator accepts grayscale or RGB masks but rejects masks that are empty, full-frame, or materially non-binary.

## Text and field types

`text` is embedded in the UTF-8 JSONL manifest. Use one line per case for the initial single-line benchmark.

Allowed `field_type` values:

- `hangul`
- `amount`
- `currency`
- `account`
- `swift`
- `date`
- `identifier`
- `mixed`

For `amount`, `currency`, `account`, `swift`, `date`, and `identifier`, punctuation and case are part of the value. Review against the entire expected string.

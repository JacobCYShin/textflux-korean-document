# Baseline Protocol

## Purpose

The first experiment is a measurement of the current checkpoint on target-like Korean documents. It is not a training run and it is not evidence of writer-style transfer.

## Required tracks

### Content track

Use target-like forms and tightly bounded masks. Include at least:

- basic Hangul without final consonants;
- Hangul with final consonants and double final consonants;
- dates;
- amounts and currency codes;
- identifiers containing digits, letters, and separators.

The same field may be reused with different requested values. This isolates text content from layout changes.

### Style track

Use a document containing handwriting evidence outside the target mask, or record a separate style reference image. The current runner does not use the separate reference automatically. The track exists to establish the style target and to distinguish a content failure from a style failure before architecture changes are proposed.

## Minimum pilot

Begin with 24 generated outputs:

```text
3 target-like documents × 4 field values × 2 fixed seeds
```

Use more seeds only after mask correctness is confirmed. Every output must retain its case ID, seed, source and mask paths, model image tag, model payload root, and SHA-256.

## Review rules

1. Review `rendered_*.png` first. If it does not show the requested value, stop: this is an input, font, or rendering-condition failure.
2. Review `result.png` next. Transcribe the generated field exactly, including punctuation.
3. Mark mask coverage and leakage separately from character correctness.
4. Score handwriting style only for `style` cases. Do not infer a writer-style failure from a blank document.

## Decision gates

| Observation | Next action |
| --- | --- |
| Rendered condition is wrong | Repair font, UTF-8 input, or case construction. Do not evaluate the model. |
| Rendered condition is right, but target text is wrong | Record a content-model failure. Compare checkpoints before training. |
| Text is exact but style is generic | Content is viable; style conditioning or style-domain adaptation is required. |
| Text is wrong and style is wrong | Establish a Korean document adaptation baseline before adding style conditioning. |
| Amount, account, SWIFT, date, or identifier differs by any character | Failure, regardless of visual quality. |

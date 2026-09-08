# Style Conditioning Boundary

## What the current runner does

The existing TextFlux inference path receives:

1. a scene or document image;
2. a binary edit mask; and
3. a rendered text-glyph condition.

It infers style from the unmasked scene context. It has no supported command-line input for a separate handwriting reference image.

## What a separate reference requires

A future handwriting-reference feature is not a font substitution or an inference-only flag. It requires a trained conditioning path with, at minimum:

- a reference-image representation or encoder;
- a defined injection point into the diffusion model;
- paired training data linking reference handwriting, target text, target document, and target mask;
- an identity split so that reference writers in validation are not copied from training; and
- separate content, style, and privacy evaluations.

Until that work exists, a `style_reference` in the benchmark manifest is metadata only. It identifies the desired style target and supports later training-set construction; it does not influence a current TextFlux output.

## Baseline interpretation

- A blank form is valid for a content-accuracy test.
- A blank form is not sufficient to claim writer-specific handwriting transfer.
- Handwriting visible outside the mask can provide in-context style evidence, but it is not equivalent to a controlled external reference pathway.

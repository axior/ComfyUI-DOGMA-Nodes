# DOGMA Nodes 1.0.9

Five new node IDs; existing 1.0.8 workflows keep their behavior. Use the new V3 workflow to enable these changes.

## Mask pipeline

- Scene inventory now provides up to three specific visible targets per family. A prominent arch/colonnade or tram can be searched explicitly, rather than only as a generic building/vehicle. Queries are generated from the input, not forced onto every scene.
- Text SAM provides object boxes. Each selected box is segmented using a single official box-only SAM decoder pass on a contextual crop. The output is not ORed with the raw text-detector mask.
- Geometry checks reject sparse outlines, fragmented selections without a dominant component, and substantial leakage outside the object box. Tiny islands are removed without closing/dilation/hole filling. True architectural openings and occlusions are preserved by these operations.
- Per-instance VLM instructions require the substantial visible body of the target, rejecting outline-only masks, surface fragments and background rectangles. Geometry alone cannot establish semantic correctness.
- Default budget is eight decoder attempts per category across both stages, including rejected attempts. Six are available globally; two reserved attempts can recover missing/rejected regions even when other objects were approved. At most three global and two local text-detection calls per category. At most eight instance audits per category.
- Recovery prioritizes rejected/unprocessed boxes and specific queries unrepresented by accepted masks. This remains a bounded search, not guaranteed full coverage. Unapproved/unsearched source regions are retained.
- Existing native-resolution crops, padding, tile budgets, optional Qwen reference and lazy phase bypass are unchanged. Reports keep internal recovery state out of visible text.

## Validation and limits

CPU regression tests cover preservation of an arch opening, rejection of outlines/speckles/box leakage, box-only API dispatch, exclusion of all-white raw masks, a detector returning 150 candidates despite its cap, reserved recovery after partial success, cumulative limits even when all attempts fail, and strict audit prompts. Workflow validation covers all links/schema, query routing, audits and retained phase/settings controls.

No end-to-end GPU inference was run on the user's scene. Detector/decoder calls in CPU tests use synthetic data. The update addresses pipeline defects; exact segmentation still depends on SAM/VLM model output. Requires current ComfyUI SAM3 box-prompt support and the existing DOGMA 1.0.8 dependencies. No automatic downloads or changes to ComfyUI core.

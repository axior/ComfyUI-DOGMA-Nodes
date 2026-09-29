# DOGMA Nodes 1.0.8

New node IDs preserve existing workflows. No models are downloaded or ComfyUI internals patched.

- Optional second style reference delegates to the official Qwen 2.1 encoder; primary image determines canvas. The optional image loader supports an explicit absent value.
- Optional lazy saving and a dimensions-only node allow a phase to be bypassed without output-node side effects.
- SAM candidate selection is capped before cleaning, with a shared global/recovery audit budget. Default 8 audits per category, 2 global aliases, at most 2 recovery views; recovery runs only when no candidate has passed and budget remains. This is a bounded selection, not an exhaustive object inventory.
- Empty masks and categories fully occluded by higher-priority ownership are skipped with reports instead of aborting.
- Semantic crops split large source regions at native resolution. A hard per-category tile budget limits cost; uncovered regions remain unchanged. Small crops can grow up to 2x; VAE alignment pads instead of shrinking. Reports list source/render sizes and deferred windows.

Validation: CPU tensor tests, geometry/coverage cases including 1000 random dimensions, synthetic 150-object overflow, cumulative budgets, empty/conflicting masks, optional-reference dispatch. No end-to-end GPU generation was performed for this release.

Requires a current ComfyUI exposing TextEncodeQwenImage21, SAM3 and lazy switches, plus the existing workflow dependencies. This release does not update ComfyUI or install third-party packs.

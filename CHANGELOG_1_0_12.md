# DOGMA Nodes 1.0.12 — bounded category inventory

Fix for V5 phase3 failure in DOGMAProposeCategoriesV111: repetitive person-instance JSON was truncated, and the parser chose the last nested query-array bracket as the inventory end. json.loads raised JSONDecodeError instead of handling model output.

New opt-in V112 planner/proposal/presence nodes used by workflow V5.1. Other node IDs and mask/render pipelines remain unchanged.

- Compact category | target noun | evidence output; category types once each, not individual instances. Up to eight unique categories.
- Preserve complete delimited rows or complete JSON objects only; ignore incomplete tails without inventing fields or classes. Deduplicate canonical synonyms such as person/people. Bound parser text and records.
- First inventory generation capped at320 tokens. One optional recovery capped at192 tokens on malformed/repetitive output, sharing the same worker/model. The worker is released in finally, including cancellation/model errors. No retry loop. Runtime exceptions from the model are not concealed.
- Prefer fresh recovery categories; retain valid complete original categories when absent from the retry. Recovered/partial status and raw outputs remain visible in the planner panels. Zero usable categories skips SAM/caption/diffusion and reports the reason.
- Independent visual presence uses short rows and a256-token limit. Missing, uncertain, malformed or duplicate-ID verdicts cannot confirm a category. Truncated JSON may contribute only complete verdict records. This is still probabilistic recognition, not a guarantee of correctness or coverage.
- Phase3 planner status is included in the parsed-plan preview. Phase1/2 controls, masks, LoRAs, native object crops, category chooser, all samplers, DAY/NIGHT and defaults remain as V5.

Validation: malformed/repetitive JSON reproduces the old exception. CPU regressions cover complete-row/object recovery, nested arrays, quoted braces, duplicate categories, absent/uncertain/conflicting verdicts, bounded retry/model reuse/cleanup, empty inventory, and raised model failures. Full static workflow checks include all phase switches, zero/three/eight selected categories, caption/sampling pruning and DAY/NIGHT routing. VLM calls simulated. No real GPU planner or full scene generation was performed.

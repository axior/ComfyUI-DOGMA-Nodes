# DOGMA Nodes 1.0.10

Corrective opt-in nodes for the coverage regression reported with 1.0.9. Old node IDs remain unchanged; load the V4 workflow.

- Restore official SAM3 text conditioning with four refinement passes, as used in DOGMA_COMPLEX_V56_11_SIX_PHASE2.json. Remove the box-only replacement introduced in 1.0.9.
- Preserve SAM mask surfaces without clipping them to detector boxes or rejecting masks based on density, dominant-component ratio or completeness. Keep format/finite/empty checks and duplicate suppression.
- Default to 32 detections per category across global/local search, with eight slots reserved for four overlapping recovery views. Use the generic category first, followed by specific visible terms from the planner. Detection limits are forwarded to the official SAM node and over-limit outputs are truncated instead of raising the former 128-object error.
- Audit four numbered candidates per VLM call. Default report_only reports PASS/FAIL/REVIEW without deleting SAM masks. The exposed reject_explicit_fail mode optionally rejects explicit numbered FAIL answers. Malformed answers are marked REVIEW and retained; batch count mismatches raise a diagnostic.
- Report retained mask count, image coverage percentage, invalid/empty detections and audit decisions. Report-only can retain incorrect SAM selections: it is not a guarantee of semantic accuracy.
- V4 workflow: Lying Sigma 0.00 in all phases, interval .2-.8 retained; phase2 8 steps Euler/simple, phase3 4 steps Euler/simple. Native semantic tile budget raised from 4 to 12 per category, preserving no-downscale/padding behavior. All other phase1/ref/day-night/preview controls retained.

Validation: CPU tensor regressions verify preserved disconnected regions and true holes, official text/4-pass dispatch, >8 retained candidates, 150-output overflow bounded to 32, four recovery views, four-per-sheet audit alignment, report/reject modes, malformed audit handling and empty diagnostics. Workflow schema/link/control checks passed. Model calls were simulated; no end-to-end GPU run on the user's scene was performed. Coverage and model segmentation quality require a real-image check.

No ComfyUI core patches, downloads or installation mutations are performed by these nodes.

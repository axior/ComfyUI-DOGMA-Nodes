DOGMA Nodes 1.0.45

Includes the full-duration rounding and visible overlay-validation fixes from 1.0.44.

- Fast edit trials use installed Ref2Video Turbo 4-step sampling; final quality settings remain separate and frozen in the selected trial.
- Trial sizes 256/384/512 px; optional live previews are disabled by default for trials.
- Source, references, text conditioning and native mask preparation are reused for identical prompts across seed trials. Reference images/video are reduced for draft preparation only.
- Selecting a completed trial during a batch abandons the unfinished trial at the next local checkpoint, skips the remaining trials and immediately regenerates the selected trial at original size. No global Comfy interrupt is used.
- Source and comparison playback loop by default; one click restarts playback after a non-looping finish.
- Independent A/B selectors compare original, trials and completed versions from the same source with synchronized source-time offsets. A or B can be selected for the final render.
- A newly completed trial no longer replaces a trial the user is already inspecting.

Validation uses real file processing and deterministic CPU H3 stand-ins, including interruption during sampling, exact frozen selection, separate 4/20-step settings, preparation reuse and browser loop/promotion/A-B tests. No new GPU H3 performance benchmark was run.

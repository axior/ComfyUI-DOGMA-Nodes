# DOGMA Nodes 1.0.7 — one VLM load per image list

Use workflow V56.19. DOGMAVLMListV568 owns one ModernVLM worker per ordered image list, reuses its model sequentially, and clears its private model handle in a finally block. This removes the repeated reload/quantization caused by ordinary Comfy list mapping with unload_after=True. It does not retain a separate model cache per graph node. Empty lists load nothing; mismatched prompts fail before loading. Progress and per-image elapsed times are logged. Cancellation is checked before/after each image; an already-running ModernVLM generation must return before the next check.

All 16 list-fed audit/caption nodes use the adapter. The single-image planner retains its ordinary unload behavior. Audit reasons are capped at 32 tokens and requested in six words. File selectors, diffusion settings, candidate counts and segmentation parameters are preserved. Requires the existing comfyui_vlm_nodes ModernVLM with clear_model API; no additional models. Publish this release, update DOGMA via Manager, restart ComfyUI, and load V56.19.

59 CPU regression tests passed. Frontend import/export and graph wiring validated offline. No GPU benchmark or visual generation has been performed on the pod; further hardware/quantization bottlenecks remain possible.

# DOGMA Nodes 1.0.6 — instance review and local recovery

Workflow V56.18 keeps the supplied SimplePod model filenames and uses KJNodes for explicit memory cleanup. ModernVLM retains its own private-model lifecycle. Update through ComfyUI-Manager after this release is available in the Registry.

Phase 3 detects raw SAM masks with paired boxes, removes speckles without growing ownership, reviews each candidate separately, and searches four overlapping local views to recover missed targets. Valid detections survive rejection of unrelated candidates. Duplicate detections and cross-category overlaps are removed. Captions describe actual crops. Inactive slots do not execute caption or diffusion; a selected visible category with no verified masks after both searches raises an explicit diagnostic instead of silently returning an empty result.

This adds CPU-tested processing and workflow wiring; actual segmentation quality and GPU runtime still require validation on the user's pod. SAM/Qwen can fail. Instance-level review and local search require more analysis than a single category-wide verdict.

# DOGMA Nodes 1.0.5 — Phase 3 mask and caption correction

New opt-in V566 nodes provide per-crop declarative prompts, SAM box ownership cleanup, per-category visual audits, masked img2img latent encoding, and distance-feathered compositing with low-frequency color protection. Existing node IDs retain their behaviour. Use the DOGMA V56.17 workflow. CPU regression tests: `python tests/run.py` (requires pytest).

# DOGMA Nodes

Custom ComfyUI nodes for DOGMA AI video workflows.

## Nodes

### WAN VACE Keyframe Control Prep

Category:

```text
video/WAN VACE
```

This node prepares a WAN VACE control video and control mask video from:

```text
video             IMAGE batch
mask_video        IMAGE batch
reference_frames  IMAGE batch
keyframe_indices  STRING
```

It replaces selected video frames with the corresponding reference frames, turns the mask fully black at those same frames, and pads the result to a WAN VACE-compatible frame count.

WAN VACE expects frame counts in the form:

```text
4n + 1
```

So the node pads the sequence by duplicating frames at the beginning and end, symmetrically, with preference for the beginning when the padding count is odd.

`keyframe_indices` supports comma, space, or semicolon separated values.

Examples:

```text
start, 25, end
0 24 48
first; 32; last
```

Indexing is **0-based**.

```text
0 = first frame
24 = 25th frame
end = last frame
```

Outputs:

```text
control_video       IMAGE batch
control_mask_video  IMAGE batch
frame_count         INT
padding_info        WANVACE_PAD_INFO
```

### WAN VACE Remove Added Padding

Category:

```text
video/WAN VACE
```

This node removes the replicated start/end frames that were added by **WAN VACE Keyframe Control Prep**.

Use it after WAN VACE generation when a later crop-and-stitch step needs the generated video to return to the original unpadded frame count.

Inputs:

```text
video         IMAGE batch
padding_info  WANVACE_PAD_INFO
```

Output:

```text
video        IMAGE batch
frame_count  INT
```

Typical use:

```text
WAN VACE Keyframe Control Prep → padding_info
WAN generated video            → WAN VACE Remove Added Padding
```

### DOGMA Sampler Select

Category:

```text
sampling/custom_sampling/samplers
```

This node returns a DOGMA sampler as a `SAMPLER` object. Use it with `SamplerCustomAdvanced` and any `SIGMAS` source, including custom hand-drawn sigma curves.

The same DOGMA samplers are also registered into normal ComfyUI sampler menus after restart, so they can appear in ordinary `KSampler`, `KSampler Advanced`, and `KSamplerSelect` dropdowns.

Available samplers:

| Sampler | Intended use | Approximate model calls |
|---|---|---:|
| `DOGMA_klein_distilled_REBUILD` | T2I, strong edit, heavily damaged upscale tile | `2 × non-final steps + 1` |
| `DOGMA_klein_distilled_BALANCED` | General T2I / i2i / edit | `2 × non-final steps + 1` |
| `DOGMA_klein_distilled_DETAIL` | Soft edit, good upscale tile, fine reconstruction | `3 × non-final steps + 1` |
| `DOGMA_klein_basemodel_REBUILD` | Fast strong reconstruction, bad source anatomy or structure | `1 × steps` |
| `DOGMA_klein_basemodel_BALANCED` | General base-model work with selective correction | Usually `1.2-1.35 × steps` |
| `DOGMA_klein_basemodel_DETAIL` | Soft edit and upscale refinement; extra work at low sigma | Usually `1.4-1.5 × steps` |

These are experimental ODE samplers designed around **FLUX.2 Klein 9B** workflows: three for the 4-6 step distilled model and three for the 20-50 step base model. No LoRA is included or required.

## Install

Install through ComfyUI Manager as **DOGMA Nodes**, or with:

```text
comfy node install comfyui-dogma-nodes
```

## Notes

The nodes use only PyTorch and ComfyUI's built-in sampler APIs. No extra Python dependencies are required.


## HDR finishing (DOGMA Nodes 1.0.51)

The HDR master workflow uses the same DOGMA Nodes Manager package on Windows and Linux.
`DOGMAHDRColorChunkedV1`, `DOGMAHDRCheckpointV1`, and `DOGMAHDRSaveStreamingV1`
require ComfyUI 0.45.0 or later. Update the existing package; no separate HDR pack
or installer is required. Existing H3 workflows and node identifiers are unchanged.

The master is a 3840x2160 ACEScg RGB HALF EXR sequence (ZIP lossless, AP1/D60).
The optional MOV is ProRes 4444 HLG / BT.2020 with 10-bit 4:4:4 encoder input
and original PCM24 audio; the EXR sequence is the 16-bit floating-point master.
Finishing is sequential per frame, but native VAE decode still returns a complete batch.
Output is under the actual Comfy output folder in `DOGMA_HDR_4K/master_XXXXX/`.

The checkpoint is saved before decode in `DOGMA_HDR_4K/checkpoints/`.
To recover an interrupted export, keep the same source loaded and enter the saved
`.latent` path (relative to Comfy output) in `resume_from`; leave it empty for a new generation.
Do not use `--fp16-intermediates` for the HDR master path.


## HDR controls (DOGMA Nodes 1.0.52 / workflow V4)

Choose everything in the main settings node: final resolution, source colour,
EXR master colour, optional MOV transfer, seed, output directory/prefix.
The model's internal ACEScct conversion is automatic and is separate from the
linear ACEScg/Rec.709 EXR output and BT.2020 HLG/PQ MOV delivery.

Original resolution means native source canvas (aligned internally to LTX),
single-stage eight-step HDR generation and exact original output dimensions.
The latent upsampler and second stage are skipped through a lazy selector.
4K retains the official eight-plus-three two-stage path and UHD final geometry.
Source transfer must match the source's export; sRGB and Rec.709 gamma 2.4 are
different choices. EXRs remain linear 16-bit float; selecting a MOV transfer
does not change the EXR master or the model's working encoding.
The single visible settings group contains independent generation and delivery
producers. Delivery-only changes reuse the model branch while Comfy's relevant
cache is available; this is not persistent recovery across server restarts.


## API Platform V2 / 1.0.54

Open DOGMA_API_PLATFORM_V2.json and press APRI DOGMA / API PLATFORM.
Quantity creates independent native asynchronous partner-node branches inside
one prompt, with a distinct seed per request. Provider limits still apply.
The original graphs are retained but inactive; use Run in the DOGMA panel.
Includes image/video references, per-reference preparation, Seedance video,
project library, workspace copies, Comfy credits/pricing and zoom comparison.
Existing DOGMA and H3 workflows keep their identifiers.


## API Platform V3 / 1.0.55
Open DOGMA_API_PLATFORM_V3.json: one launcher node. The panel appears before asynchronous initialization. Folder navigation stays in the browser. Stop cancels DOGMA jobs; provider billing for already completed work still applies. Remaining time is an estimate from completed jobs when available.


## API Platform V4 / 1.0.56
Open DOGMA_API_PLATFORM_V4.json: one launcher node. The panel appears before asynchronous initialization. Folder navigation stays in the browser. Stop cancels DOGMA jobs; provider billing for already completed work still applies. Remaining time is an estimate from completed jobs when available.


## API Platform V5 / 1.0.57 — selective video repair

Enable **Correggi scatti** in Video to save both the original and `_FIX.mp4`. Both Ref → Video and First / Last frame use the same local repair. The setting does not change paid API inputs, quantities or seeds. A verified unchanged copy is produced when no reliable problem is detected. If processing fails or is stopped, the original remains available and the panel shows a warning.

The detector operates on small previews; RIFE reconstructs only selected frames at source resolution. Reliable pans with repeated jumps may additionally receive small camera translations, capped at 0.4% of width/height. This extends a thin edge strip by reflection instead of cropping or zooming. Camera refinement and interpolation share one encoding pass. Clean clips, poorly tracked shots, zooms and reversing camera paths are not stabilized. Frame count, timestamps, source bit depth and audio packet identity are checked before accepting the second file. A motion-based quality gate is an additional check, not a guarantee against every possible visual artifact. The method is independent of source fps and has no fixed clip-duration setting; processing time and memory grow with frame count and resolution. It does not impose 24 fps. CUDA and NVIDIA video encoding provide the fast path; CPU/software fallback is slower. First use includes model download and GPU initialization. No video is uploaded to another service. Generative deformations or newly invented content cannot be reliably restored by a cadence repair.

RIFE 4.26 code/weights: https://github.com/hzwer/Practical-RIFE (MIT; LICENSE_RIFE.txt). Verified weights are automatically cached under `models/DOGMA/rife`. Architecture derived from the official model archive, revision `01fdc7e97404120c243c3ea7b427046e5dc7643e`. DOGMA motion detection, timestamp planning and integration are separate from RIFE inference. No other ComfyUI interpolation extension is required.


## Standalone Seedance fix / 1.0.58

`Load Video → DOGMA / Fix video Seedance → Save Video` uses only the generated video. No original footage, API generation, credentials or credits are needed. The node reuses the unchanged 1.0.57 repair engine and its cached RIFE weights. Progress and a short result message are reported in ComfyUI. Clips without confidently detected stutter are returned unchanged; a rejected correction is explicitly reported as unchanged.

Use MP4 and codec **auto** in Save Video to preserve the corrected stream without another encoding pass. The supplied standalone workflow writes to `output/DOGMA/SeedanceFix/Seedance_FIX_*.mp4`. Duration, fps, frame timestamps, dimensions, color depth and audio are checked by the repair engine. The uploaded source is not overwritten. The fix runs outside the async event loop; Stop cancels processing and removes that attempt's partial files. Intermediate output and diagnostics live in ComfyUI's temp directory, so cached results can be saved again without repeating inference.

Existing API Platform, H3 and HDR workflows remain compatible. The same package supports Windows and the pod. No extra node pack is required.


## Correggi scatti: precise MP4 timing / 1.0.59

Fix the shared repair encoder used by API Platform's **Correggi scatti** switch and the standalone Seedance fix node. MP4's default 1000 Hz movie clock could truncate fractional-second clip ends and trigger "La durata del file corretto è cambiata", even with every frame and timestamp intact. For example, a 457-frame, 24 fps clip was rejected because the reported duration differed by eight video-clock ticks.

Both the NVIDIA and software encoder now use the source video's time base for the MP4 movie and video track clocks. The strict checks on frame count, timestamps, duration, fps, dimensions, color depth and copied audio remain in place. This changes only the container timing; motion analysis, interpolation, quality gates and correction settings are unchanged. It adds no interpolation or encoding pass.

When enabled, API Platform saves the generated original and a second locally processed copy in the existing project/scene workspace. Turning the switch off skips repair. Stop and real processing errors retain the original and report the outcome; an unsuccessful correction is never presented as repaired. Existing workflows and node IDs are compatible, with no new dependencies and the same code on Windows and the pod.


## Compare controls and sidebar alignment / 1.0.60

API Platform now has a compact **Compare** switch next to **Mostra errori** in the gallery filters and at the right of the enlarged image toolbar. Both controls share one saved session preference. OFF removes the original/reference overlay and divider immediately; ON enables the existing pointer comparison. Existing sessions default to ON. Selecting an explicit A/B pair still opens the comparison automatically and enables Compare. The enlarged-image switch is unavailable when there is no second image to compare.

The extra left inset below the Image/Video tabs is removed from the controls and Image Edit row. References, prompt, filename/workspace and model sections now align with the left edge of the tabs; their existing right edge is preserved. Works in Image and Video mode. Existing node IDs, generation behavior, video repair and workflow JSON are unchanged.


## Drag to reorder models / 1.0.61

Drag an existing model heading up or down to change the order of the blocks under **MODELS**. The order is saved with the session/workflow, including when switching between Image and Video. No new buttons or drag handles are added. A normal click still expands or collapses the model; switches, quantities and parameters keep their usual behavior. Drag near the sidebar edge to scroll, or release outside the list / press Escape to cancel.

The visible switches in model headings, Image Edit, the date row and video repair align with the left edge of the Image/Video tabs and section dividers. Their existing click targets and text positions are preserved; switches inside reference thumbnails and parameter fields keep their own inset.

Generation quantities and seeds, API execution, video repair behavior and existing workflow identifiers remain unchanged. Previous workflows load with their original model order.

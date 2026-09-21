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

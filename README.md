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

## Install

Install through ComfyUI Manager as **DOGMA Nodes**, or with:

```text
comfy node install comfyui-dogma-nodes
```

## Notes

The nodes use only PyTorch, which is already part of a normal ComfyUI installation. No extra Python dependencies are required.

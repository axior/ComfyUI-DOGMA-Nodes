# ComfyUI WanVACE Keyframe Prep

A minimal ComfyUI custom node for preparing **WAN VACE control video** and **control mask video** from an image-batch video, a mask-video batch, and one or more reference keyframes.

## Node

**WAN VACE Keyframe Control Prep**

Category:

```text
video/WAN VACE
```

## What it does

The node takes a video batch, a mask-video batch, reference frames, and a list of keyframe indices. It replaces the selected video frames with the corresponding reference frames, turns the mask fully black at those same frames, and pads the result to a WAN VACE-compatible frame count.

WAN VACE expects frame counts in the form:

```text
4n + 1
```

So the node pads the sequence by duplicating frames at the beginning and end, symmetrically, with preference for the beginning when the padding count is odd.

## Inputs

```text
video             IMAGE batch
mask_video        IMAGE batch
reference_frames  IMAGE batch
keyframe_indices  STRING
```

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

## Outputs

```text
control_video       IMAGE batch
control_mask_video  IMAGE batch
frame_count         INT
```

## Install

1. Open ComfyUI Manager
2. Click “Install via Git URL”
3. Paste:

https://github.com/axior/ComfyUI-DOGMA-Nodes

4. Click Install
5. Restart ComfyUI

## Notes

The node uses only PyTorch, which is already part of a normal ComfyUI installation. No extra Python dependencies are required.

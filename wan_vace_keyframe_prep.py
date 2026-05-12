import re
from typing import List

import torch


def _parse_indices(text: str) -> List[str]:
    """Parse a comma/space separated list into tokens: integers or start/end."""
    if text is None:
        return []
    t = text.strip().lower()
    if not t:
        return []
    # split on commas or whitespace
    parts = re.split(r"[\s,;]+", t)
    parts = [p for p in parts if p]
    # normalize aliases
    norm = []
    for p in parts:
        if p in ("s", "first", "begin", "beginning"):
            norm.append("start")
        elif p in ("e", "last"):
            norm.append("end")
        else:
            norm.append(p)
    return norm


def _resolve_indices(tokens: List[str], length: int) -> List[int]:
    out: List[int] = []
    for tok in tokens:
        if tok == "start":
            out.append(0)
        elif tok == "end":
            out.append(max(0, length - 1))
        else:
            try:
                out.append(int(tok))
            except Exception:
                # ignore unknown tokens
                continue
    return out


def _next_vace_len(length: int) -> int:
    """VACE accepts 4n+1: 1,5,9,..."""
    if length <= 1:
        return 1
    r = (length - 1) % 4
    if r == 0:
        return length
    return length + (4 - r)


def _ensure_4d_image_batch(x: torch.Tensor) -> torch.Tensor:
    # Comfy IMAGE is [B,H,W,C]
    if not isinstance(x, torch.Tensor):
        raise TypeError("Expected torch.Tensor for IMAGE")
    if x.ndim != 4:
        raise ValueError(f"Expected IMAGE batch with 4 dims [B,H,W,C], got {x.shape}")
    return x


def _make_black_frame_like(frame: torch.Tensor) -> torch.Tensor:
    # frame is [H,W,C] or [1,H,W,C]?
    if frame.ndim == 3:
        return torch.zeros_like(frame)
    if frame.ndim == 4:
        return torch.zeros_like(frame)
    raise ValueError("Unexpected frame shape")


def _resize_like(src: torch.Tensor, ref: torch.Tensor) -> torch.Tensor:
    """Resize src frame/batch to match ref H,W using bilinear. Keeps channel count."""
    # src may be [H,W,C] or [B,H,W,C]
    # ref is [H,W,C] or [B,H,W,C]
    if ref.ndim == 4:
        ref_h, ref_w = ref.shape[1], ref.shape[2]
    else:
        ref_h, ref_w = ref.shape[0], ref.shape[1]

    if src.ndim == 3:
        h, w = src.shape[0], src.shape[1]
        if h == ref_h and w == ref_w:
            return src
        # to NCHW
        t = src.permute(2, 0, 1).unsqueeze(0)
        t = torch.nn.functional.interpolate(t, size=(ref_h, ref_w), mode="bilinear", align_corners=False)
        return t.squeeze(0).permute(1, 2, 0)

    if src.ndim == 4:
        h, w = src.shape[1], src.shape[2]
        if h == ref_h and w == ref_w:
            return src
        t = src.permute(0, 3, 1, 2)
        t = torch.nn.functional.interpolate(t, size=(ref_h, ref_w), mode="bilinear", align_corners=False)
        return t.permute(0, 2, 3, 1)

    raise ValueError("Unexpected src shape")


class WanVACEKeyframeControlPrep:
    """Prepare Control Video + Control Mask Video for WAN VACE.

    - Replaces selected frames in the input video with reference keyframes.
    - Disables the mask at those same frames by inserting fully black frames in the mask video.
    - Pads the sequence to a VACE-compatible length (4n+1) by duplicating start/end frames symmetrically,
      with preference for padding at the start.

    Inputs are IMAGE batches (video as frames).
    """

    CATEGORY = "video/WAN VACE"
    FUNCTION = "prep"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "video": ("IMAGE", {}),
                "mask_video": ("IMAGE", {}),
                "reference_frames": ("IMAGE", {}),
                "keyframe_indices": (
                    "STRING",
                    {
                        "multiline": False,
                        "default": "start, 25, end",
                        "tooltip": "Comma/space separated indices. Supports start/end. 0-based indexing.",
                    },
                ),
            }
        }

    RETURN_TYPES = ("IMAGE", "IMAGE", "INT")
    RETURN_NAMES = ("control_video", "control_mask_video", "frame_count")

    def prep(self, video, mask_video, reference_frames, keyframe_indices):
        video = _ensure_4d_image_batch(video)
        mask_video = _ensure_4d_image_batch(mask_video)
        reference_frames = _ensure_4d_image_batch(reference_frames)

        # Make lengths consistent between video and mask by truncating to min length
        L = int(video.shape[0])
        Lm = int(mask_video.shape[0])
        L0 = min(L, Lm)
        if L0 <= 0:
            # degenerate
            return (video, mask_video, 0)

        video = video[:L0]
        mask_video = mask_video[:L0]

        tokens = _parse_indices(keyframe_indices)
        raw_indices = _resolve_indices(tokens, L0)

        # Pair references with indices (use min count)
        K = min(int(reference_frames.shape[0]), len(raw_indices))
        if K <= 0:
            # still enforce VACE length even if no keyframes
            target = _next_vace_len(L0)
            pad = target - L0
            if pad > 0:
                pad_start = (pad + 1) // 2  # prefer start
                pad_end = pad - pad_start
                first_v = video[0:1].repeat(pad_start, 1, 1, 1)
                last_v = video[-1:].repeat(pad_end, 1, 1, 1)
                first_m = mask_video[0:1].repeat(pad_start, 1, 1, 1)
                last_m = mask_video[-1:].repeat(pad_end, 1, 1, 1)
                video_out = torch.cat([first_v, video, last_v], dim=0)
                mask_out = torch.cat([first_m, mask_video, last_m], dim=0)
            else:
                video_out = video
                mask_out = mask_video
            return (video_out, mask_out, int(video_out.shape[0]))

        indices = raw_indices[:K]
        refs = reference_frames[:K]

        # Enforce same size as video frames
        refs = _resize_like(refs, video)

        # Prepare output copies
        video_out = video.clone()
        mask_out = mask_video.clone()

        # Replace frames, and disable mask frames
        black = torch.zeros_like(mask_out[0])
        for i, idx in enumerate(indices):
            if 0 <= idx < L0:
                video_out[idx] = refs[i]
                mask_out[idx] = black

        # Pad to VACE accepted length: 4n+1
        target = _next_vace_len(int(video_out.shape[0]))
        pad = target - int(video_out.shape[0])
        if pad > 0:
            pad_start = (pad + 1) // 2  # prefer start
            pad_end = pad - pad_start

            # padding frames
            first_v = video_out[0:1].repeat(pad_start, 1, 1, 1)
            last_v = video_out[-1:].repeat(pad_end, 1, 1, 1)
            first_m = mask_out[0:1].repeat(pad_start, 1, 1, 1)
            last_m = mask_out[-1:].repeat(pad_end, 1, 1, 1)

            video_out = torch.cat([first_v, video_out, last_v], dim=0)
            mask_out = torch.cat([first_m, mask_out, last_m], dim=0)

            # shift indices because of pad_start
            shifted_indices = [idx + pad_start for idx in indices]

            # Ensure keyframes are still present at shifted locations (safe reapply)
            black2 = torch.zeros_like(mask_out[0])
            for i, idx in enumerate(shifted_indices):
                if 0 <= idx < int(video_out.shape[0]):
                    video_out[idx] = refs[i]
                    mask_out[idx] = black2

        return (video_out, mask_out, int(video_out.shape[0]))

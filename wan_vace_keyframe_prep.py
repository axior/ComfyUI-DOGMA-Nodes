import re
from typing import Dict, List, Tuple

import torch


PAD_INFO_TYPE = "WANVACE_PAD_INFO"


def _parse_indices(text: str) -> List[str]:
    """Parse a comma/space/semicolon separated list into tokens: integers or start/end."""
    if text is None:
        return []
    t = text.strip().lower()
    if not t:
        return []
    parts = re.split(r"[\s,;]+", t)
    parts = [p for p in parts if p]

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
                continue
    return out


def _next_vace_len(length: int) -> int:
    """WAN VACE accepts frame counts in the form 4n+1: 1, 5, 9, ..."""
    if length <= 1:
        return 1
    remainder = (length - 1) % 4
    if remainder == 0:
        return length
    return length + (4 - remainder)


def _compute_padding(length: int) -> Tuple[int, int, int]:
    """Return pad_start, pad_end, target_length. Odd padding prefers the start."""
    target = _next_vace_len(length)
    pad = max(0, target - length)
    pad_start = (pad + 1) // 2
    pad_end = pad - pad_start
    return pad_start, pad_end, target


def _make_pad_info(original_length: int, pad_start: int, pad_end: int, padded_length: int) -> Dict[str, int]:
    return {
        "original_length": int(original_length),
        "pad_start": int(pad_start),
        "pad_end": int(pad_end),
        "padded_length": int(padded_length),
    }


def _ensure_4d_image_batch(x: torch.Tensor) -> torch.Tensor:
    # Comfy IMAGE is [B,H,W,C]
    if not isinstance(x, torch.Tensor):
        raise TypeError("Expected torch.Tensor for IMAGE")
    if x.ndim != 4:
        raise ValueError(f"Expected IMAGE batch with 4 dims [B,H,W,C], got {x.shape}")
    return x


def _resize_like(src: torch.Tensor, ref: torch.Tensor) -> torch.Tensor:
    """Resize src frame/batch to match ref H,W using bilinear. Keeps channel count."""
    if ref.ndim == 4:
        ref_h, ref_w = ref.shape[1], ref.shape[2]
    else:
        ref_h, ref_w = ref.shape[0], ref.shape[1]

    if src.ndim == 3:
        h, w = src.shape[0], src.shape[1]
        if h == ref_h and w == ref_w:
            return src
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


def _pad_image_batch(video: torch.Tensor, pad_start: int, pad_end: int) -> torch.Tensor:
    if pad_start <= 0 and pad_end <= 0:
        return video

    parts = []
    if pad_start > 0:
        parts.append(video[0:1].repeat(pad_start, 1, 1, 1))
    parts.append(video)
    if pad_end > 0:
        parts.append(video[-1:].repeat(pad_end, 1, 1, 1))
    return torch.cat(parts, dim=0)


class WanVACEKeyframeControlPrep:
    """Prepare Control Video + Control Mask Video for WAN VACE.

    - Replaces selected frames in the input video with reference keyframes.
    - Disables the mask at those same frames by inserting fully black frames in the mask video.
    - Pads the sequence to a WAN VACE-compatible length (4n+1) by duplicating start/end frames,
      with preference for padding at the start.
    - Outputs padding metadata that can later be used to remove the added frames after generation.
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
                        "tooltip": "Comma/space/semicolon separated indices. Supports start/end. 0-based indexing.",
                    },
                ),
            }
        }

    RETURN_TYPES = ("IMAGE", "IMAGE", "INT", PAD_INFO_TYPE)
    RETURN_NAMES = ("control_video", "control_mask_video", "frame_count", "padding_info")

    def prep(self, video, mask_video, reference_frames, keyframe_indices):
        video = _ensure_4d_image_batch(video)
        mask_video = _ensure_4d_image_batch(mask_video)
        reference_frames = _ensure_4d_image_batch(reference_frames)

        original_video_length = int(video.shape[0])
        original_mask_length = int(mask_video.shape[0])
        working_length = min(original_video_length, original_mask_length)

        if working_length <= 0:
            pad_info = _make_pad_info(0, 0, 0, 0)
            return (video, mask_video, 0, pad_info)

        video_out = video[:working_length].clone()
        mask_out = mask_video[:working_length].clone()

        tokens = _parse_indices(keyframe_indices)
        raw_indices = _resolve_indices(tokens, working_length)

        keyframe_count = min(int(reference_frames.shape[0]), len(raw_indices))
        if keyframe_count > 0:
            indices = raw_indices[:keyframe_count]
            refs = _resize_like(reference_frames[:keyframe_count], video_out)

            black = torch.zeros_like(mask_out[0])
            for i, idx in enumerate(indices):
                if 0 <= idx < working_length:
                    video_out[idx] = refs[i]
                    mask_out[idx] = black
        else:
            indices = []
            refs = None

        pad_start, pad_end, target_length = _compute_padding(int(video_out.shape[0]))
        video_out = _pad_image_batch(video_out, pad_start, pad_end)
        mask_out = _pad_image_batch(mask_out, pad_start, pad_end)

        # Safe reapply after padding, so the requested keyframes remain exact at shifted positions.
        if keyframe_count > 0 and refs is not None:
            black = torch.zeros_like(mask_out[0])
            for i, idx in enumerate(indices):
                shifted_idx = idx + pad_start
                if 0 <= shifted_idx < int(video_out.shape[0]):
                    video_out[shifted_idx] = refs[i]
                    mask_out[shifted_idx] = black

        pad_info = _make_pad_info(
            original_length=working_length,
            pad_start=pad_start,
            pad_end=pad_end,
            padded_length=int(video_out.shape[0]),
        )

        return (video_out, mask_out, int(video_out.shape[0]), pad_info)


class WanVACERemoveAddedPadding:
    """Remove the start/end frames that WanVACEKeyframeControlPrep added for 4n+1 compatibility."""

    CATEGORY = "video/WAN VACE"
    FUNCTION = "remove_padding"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "video": ("IMAGE", {}),
                "padding_info": (PAD_INFO_TYPE, {}),
            }
        }

    RETURN_TYPES = ("IMAGE", "INT")
    RETURN_NAMES = ("video", "frame_count")

    def remove_padding(self, video, padding_info):
        video = _ensure_4d_image_batch(video)

        if not isinstance(padding_info, dict):
            return (video, int(video.shape[0]))

        pad_start = int(padding_info.get("pad_start", 0) or 0)
        pad_end = int(padding_info.get("pad_end", 0) or 0)
        expected_original_length = int(padding_info.get("original_length", 0) or 0)

        length = int(video.shape[0])
        start = max(0, pad_start)
        end = length - max(0, pad_end)

        if end < start:
            return (video, length)

        trimmed = video[start:end]

        # If the metadata contains the original length and a length mismatch still remains,
        # prefer the exact original length from the start of the trimmed sequence.
        if expected_original_length > 0 and int(trimmed.shape[0]) > expected_original_length:
            trimmed = trimmed[:expected_original_length]

        if int(trimmed.shape[0]) <= 0:
            return (video, length)

        return (trimmed, int(trimmed.shape[0]))

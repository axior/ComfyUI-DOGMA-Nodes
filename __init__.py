from .wan_vace_keyframe_prep import WanVACEKeyframeControlPrep, WanVACERemoveAddedPadding
from .dogma_samplers import (
    DOGMASamplerSelect,
    register_samplers,
)

register_samplers()

NODE_CLASS_MAPPINGS = {
    "WanVACEKeyframeControlPrep": WanVACEKeyframeControlPrep,
    "WanVACERemoveAddedPadding": WanVACERemoveAddedPadding,
    "DOGMASamplerSelect": DOGMASamplerSelect,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "WanVACEKeyframeControlPrep": "WAN VACE Keyframe Control Prep",
    "WanVACERemoveAddedPadding": "WAN VACE Remove Added Padding",
    "DOGMASamplerSelect": "DOGMA Sampler Select",
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]

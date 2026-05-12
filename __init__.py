from .wan_vace_keyframe_prep import WanVACEKeyframeControlPrep

NODE_CLASS_MAPPINGS = {
    "WanVACEKeyframeControlPrep": WanVACEKeyframeControlPrep,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "WanVACEKeyframeControlPrep": "WAN VACE Keyframe Control Prep",
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]

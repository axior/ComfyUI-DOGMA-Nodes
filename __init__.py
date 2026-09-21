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

# >>> DOGMA SEMANTIC V56.4.1 >>>
from .dogma_semantic_v5641 import (
    NODE_CLASS_MAPPINGS as _DOGMA_SEMANTIC_5641,
    NODE_DISPLAY_NAME_MAPPINGS as _DOGMA_SEMANTIC_DISPLAY_5641,
)

try:
    NODE_CLASS_MAPPINGS
except NameError:
    NODE_CLASS_MAPPINGS = {}

try:
    NODE_DISPLAY_NAME_MAPPINGS
except NameError:
    NODE_DISPLAY_NAME_MAPPINGS = {}

NODE_CLASS_MAPPINGS.update(_DOGMA_SEMANTIC_5641)
NODE_DISPLAY_NAME_MAPPINGS.update(_DOGMA_SEMANTIC_DISPLAY_5641)

del _DOGMA_SEMANTIC_5641
del _DOGMA_SEMANTIC_DISPLAY_5641
# <<< DOGMA SEMANTIC V56.4.1 <<<

# >>> DOGMA V56.5 NODES >>>
from .dogma_semantic_v565 import (
    NODE_CLASS_MAPPINGS as _DOGMA_V565_NODE_CLASS_MAPPINGS,
    NODE_DISPLAY_NAME_MAPPINGS as _DOGMA_V565_NODE_DISPLAY_NAME_MAPPINGS,
)

NODE_CLASS_MAPPINGS.update(_DOGMA_V565_NODE_CLASS_MAPPINGS)
NODE_DISPLAY_NAME_MAPPINGS.update(_DOGMA_V565_NODE_DISPLAY_NAME_MAPPINGS)

del _DOGMA_V565_NODE_CLASS_MAPPINGS
del _DOGMA_V565_NODE_DISPLAY_NAME_MAPPINGS
# <<< DOGMA V56.5 NODES <<<
# DOGMA v56.6: opt-in corrected phase-3 nodes.
from .dogma_semantic_v566 import NODE_CLASS_MAPPINGS as _V566, NODE_DISPLAY_NAME_MAPPINGS as _V566_NAMES
NODE_CLASS_MAPPINGS.update(_V566)
NODE_DISPLAY_NAME_MAPPINGS.update(_V566_NAMES)
del _V566, _V566_NAMES

from .dogma_semantic_v567 import NODE_CLASS_MAPPINGS as _V567, NODE_DISPLAY_NAME_MAPPINGS as _V567_NAMES
NODE_CLASS_MAPPINGS.update(_V567)
NODE_DISPLAY_NAME_MAPPINGS.update(_V567_NAMES)
del _V567, _V567_NAMES

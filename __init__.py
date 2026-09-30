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

from .dogma_semantic_v568 import NODE_CLASS_MAPPINGS as _V568, NODE_DISPLAY_NAME_MAPPINGS as _V568_NAMES
NODE_CLASS_MAPPINGS.update(_V568)
NODE_DISPLAY_NAME_MAPPINGS.update(_V568_NAMES)
del _V568, _V568_NAMES

# DOGMA 1.0.8: optional reference, lazy phase bypass and bounded native refinement.
from .dogma_simplepod_v2 import NODE_CLASS_MAPPINGS as _V108, NODE_DISPLAY_NAME_MAPPINGS as _V108_NAMES
NODE_CLASS_MAPPINGS.update(_V108)
NODE_DISPLAY_NAME_MAPPINGS.update(_V108_NAMES)
del _V108, _V108_NAMES

# DOGMA 1.0.9: coherent box-prompt masks and reserved recovery after partial success.
from .dogma_semantic_v109 import NODE_CLASS_MAPPINGS as _V109, NODE_DISPLAY_NAME_MAPPINGS as _V109_NAMES
NODE_CLASS_MAPPINGS.update(_V109)
NODE_DISPLAY_NAME_MAPPINGS.update(_V109_NAMES)
del _V109, _V109_NAMES

# DOGMA 1.0.10: restored text SAM refinement, broader coverage and grouped audits.
from .dogma_semantic_v110 import NODE_CLASS_MAPPINGS as _V110, NODE_DISPLAY_NAME_MAPPINGS as _V110_NAMES
NODE_CLASS_MAPPINGS.update(_V110)
NODE_DISPLAY_NAME_MAPPINGS.update(_V110_NAMES)
del _V110, _V110_NAMES

from .dogma_control_v111 import NODE_CLASS_MAPPINGS as _V111, NODE_DISPLAY_NAME_MAPPINGS as _V111_NAMES
NODE_CLASS_MAPPINGS.update(_V111)
NODE_DISPLAY_NAME_MAPPINGS.update(_V111_NAMES)
del _V111, _V111_NAMES

from .dogma_objects_v111 import NODE_CLASS_MAPPINGS as _V111, NODE_DISPLAY_NAME_MAPPINGS as _V111_NAMES
NODE_CLASS_MAPPINGS.update(_V111)
NODE_DISPLAY_NAME_MAPPINGS.update(_V111_NAMES)
del _V111, _V111_NAMES

from .dogma_audit_v111 import NODE_CLASS_MAPPINGS as _V111, NODE_DISPLAY_NAME_MAPPINGS as _V111_NAMES
NODE_CLASS_MAPPINGS.update(_V111)
NODE_DISPLAY_NAME_MAPPINGS.update(_V111_NAMES)
del _V111, _V111_NAMES

from .dogma_control_v111 import register_routes as _register_v111
_register_v111()
del _register_v111
WEB_DIRECTORY = "./web_v111"

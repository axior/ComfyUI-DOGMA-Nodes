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

# Opt-in robust inventory used by workflow V5.1; existing V111 node IDs unchanged.
from .dogma_planner_v112 import NODE_CLASS_MAPPINGS as _V112, NODE_DISPLAY_NAME_MAPPINGS as _V112_NAMES
NODE_CLASS_MAPPINGS.update(_V112)
NODE_DISPLAY_NAME_MAPPINGS.update(_V112_NAMES)
del _V112, _V112_NAMES

# Category-relative audit, opt-in workflow V5.3. Older workflows remain unchanged.
from .dogma_audit_v114 import NODE_CLASS_MAPPINGS as _V114, NODE_DISPLAY_NAME_MAPPINGS as _V114_NAMES
NODE_CLASS_MAPPINGS.update(_V114)
NODE_DISPLAY_NAME_MAPPINGS.update(_V114_NAMES)
del _V114, _V114_NAMES

# Opt-in mask laboratory; production workflows and older node IDs unchanged.
from .dogma_mask_lab_v115 import NODE_CLASS_MAPPINGS as _LAB115, NODE_DISPLAY_NAME_MAPPINGS as _LAB115_NAMES
NODE_CLASS_MAPPINGS.update(_LAB115)
NODE_DISPLAY_NAME_MAPPINGS.update(_LAB115_NAMES)
del _LAB115, _LAB115_NAMES

# Isolated phase-3 preparation test; production workflows unchanged.
from .dogma_phase3_prep_v117 import NODE_CLASS_MAPPINGS as _PREP117, NODE_DISPLAY_NAME_MAPPINGS as _PREP117_NAMES
NODE_CLASS_MAPPINGS.update(_PREP117)
NODE_DISPLAY_NAME_MAPPINGS.update(_PREP117_NAMES)
del _PREP117, _PREP117_NAMES

from .dogma_integrated_v122 import NODE_CLASS_MAPPINGS as _V122, NODE_DISPLAY_NAME_MAPPINGS as _V122_NAMES
NODE_CLASS_MAPPINGS.update(_V122)
NODE_DISPLAY_NAME_MAPPINGS.update(_V122_NAMES)
del _V122, _V122_NAMES

# Content-versioned UI and non-invasive review outputs; V122 identifiers remain valid.
from pathlib import Path as _DogmaPath
from .dogma_frontend_v123 import register_frontend as _register_frontend123
_register_frontend123(_DogmaPath(__file__).parent / WEB_DIRECTORY)
del _register_frontend123, _DogmaPath
from .dogma_review_v123 import NODE_CLASS_MAPPINGS as _V123, NODE_DISPLAY_NAME_MAPPINGS as _V123_NAMES
NODE_CLASS_MAPPINGS.update(_V123)
NODE_DISPLAY_NAME_MAPPINGS.update(_V123_NAMES)
del _V123, _V123_NAMES

from .dogma_coherence_v124 import NODE_CLASS_MAPPINGS as _V124, NODE_DISPLAY_NAME_MAPPINGS as _V124_NAMES
NODE_CLASS_MAPPINGS.update(_V124)
NODE_DISPLAY_NAME_MAPPINGS.update(_V124_NAMES)
del _V124, _V124_NAMES

# Isolated signs workflow; previous node classes and frontend are unchanged.
from .dogma_signs_v125 import NODE_CLASS_MAPPINGS as _SIGNS125, NODE_DISPLAY_NAME_MAPPINGS as _SIGNS125_NAMES, register_routes as _signs_routes125
NODE_CLASS_MAPPINGS.update(_SIGNS125)
NODE_DISPLAY_NAME_MAPPINGS.update(_SIGNS125_NAMES)
_signs_routes125()
del _SIGNS125, _SIGNS125_NAMES, _signs_routes125

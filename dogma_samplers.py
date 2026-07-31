"""ComfyUI registration and selector node for DOGMA samplers."""

from __future__ import annotations

import logging

import comfy.samplers
from comfy.k_diffusion import sampling as k_sampling

from .samplers import SAMPLER_FUNCTIONS, SAMPLER_NAMES


_LOG = logging.getLogger("DOGMA_Samplers")


def register_samplers() -> None:
    """Register DOGMA functions in ComfyUI's global sampler catalogue.

    ComfyUI resolves ordinary KSampler names as attributes named
    ``sample_<sampler_name>`` on ``comfy.k_diffusion.sampling``. Registering both
    the function and the name makes the samplers available in normal KSampler,
    KSampler Advanced, and KSamplerSelect menus after a ComfyUI restart.
    """
    current_samplers = comfy.samplers.KSampler.SAMPLERS
    sampler_list = list(current_samplers)
    added = []

    for name, function in SAMPLER_FUNCTIONS.items():
        setattr(k_sampling, f"sample_{name}", function)
        if name not in sampler_list:
            sampler_list.append(name)
            added.append(name)

    if sampler_list != list(current_samplers):
        comfy.samplers.KSampler.SAMPLERS = sampler_list

    if added:
        _LOG.info("Registered DOGMA samplers: %s", ", ".join(added))


class DOGMASamplerSelect:
    """Return one of the six samplers as a ComfyUI SAMPLER object."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "sampler_name": (list(SAMPLER_NAMES),),
            }
        }

    RETURN_TYPES = ("SAMPLER",)
    RETURN_NAMES = ("sampler",)
    FUNCTION = "get_sampler"
    CATEGORY = "sampling/custom_sampling/samplers"
    DESCRIPTION = (
        "Select a DOGMA sampler. Use this output with SamplerCustomAdvanced and "
        "any SIGMAS source, including NKD Sigmas Curve."
    )

    def get_sampler(self, sampler_name):
        function = SAMPLER_FUNCTIONS[sampler_name]
        return (comfy.samplers.KSAMPLER(function),)


NODE_CLASS_MAPPINGS = {
    "DOGMASamplerSelect": DOGMASamplerSelect,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "DOGMASamplerSelect": "DOGMA Sampler Select",
}

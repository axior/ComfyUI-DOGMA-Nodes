"""DOGMA samplers for ComfyUI.

Six experimental ODE samplers tuned around FLUX.2 Klein 9B workflows:
three for the 4-6 step distilled model and three for the 20-50 step base model.

The functions intentionally follow ComfyUI's k-diffusion sampler signature so they
can be used both through the normal KSampler menus and as SAMPLER objects with
SamplerCustomAdvanced / custom sigma curves.
"""

from __future__ import annotations

from typing import Callable, Dict, Optional

import torch

from comfy.k_diffusion import sampling as k_sampling


Tensor = torch.Tensor
SamplerFunction = Callable[..., Tensor]


# Public names as they appear in ComfyUI's sampler dropdowns.
DISTILLED_REBUILD = "DOGMA_klein_distilled_REBUILD"
DISTILLED_BALANCED = "DOGMA_klein_distilled_BALANCED"
DISTILLED_DETAIL = "DOGMA_klein_distilled_DETAIL"
BASE_REBUILD = "DOGMA_klein_basemodel_REBUILD"
BASE_BALANCED = "DOGMA_klein_basemodel_BALANCED"
BASE_DETAIL = "DOGMA_klein_basemodel_DETAIL"


def _args(extra_args: Optional[dict]) -> dict:
    return {} if extra_args is None else extra_args


def _is_zero_sigma(sigma: Tensor) -> bool:
    """Robust scalar-zero check for CPU or GPU sigma tensors."""
    return bool(torch.all(sigma == 0).item())


def _emit_callback(callback, x: Tensor, i: int, sigma: Tensor, denoised: Tensor) -> None:
    if callback is not None:
        callback(
            {
                "x": x,
                "i": i,
                "sigma": sigma,
                "sigma_hat": sigma,
                "denoised": denoised,
            }
        )


def _eval(model, x: Tensor, sigma: Tensor, s_in: Tensor, extra_args: dict) -> Tensor:
    return model(x, sigma * s_in, **extra_args)


def _derivative(x: Tensor, sigma: Tensor, denoised: Tensor) -> Tensor:
    return k_sampling.to_d(x, sigma, denoised)


def _limit_direction(direction: Tensor, reference: Tensor, max_ratio: float) -> Tensor:
    """Limit only catastrophic derivative extrapolation, independently per batch.

    This is not ordinary gradient clipping. It keeps experimental momentum or
    over-relaxation from exploding when a hand-drawn sigma curve contains a very
    uneven interval.
    """
    dims = tuple(range(1, direction.ndim))
    d_rms = direction.float().square().mean(dim=dims, keepdim=True).sqrt()
    r_rms = reference.float().square().mean(dim=dims, keepdim=True).sqrt()
    scale = (max_ratio * r_rms / (d_rms + 1e-12)).clamp(max=1.0)
    return direction * scale.to(dtype=direction.dtype)


def _variable_ab2(
    current_d: Tensor,
    previous_d: Optional[Tensor],
    current_h: Tensor,
    previous_h: Optional[Tensor],
) -> Tensor:
    """Variable-step Adams-Bashforth 2 direction.

    For equal intervals this becomes 1.5*d_n - 0.5*d_(n-1). The step-ratio is
    clamped because user-drawn schedules can contain abrupt interval jumps for
    which unrestricted multistep extrapolation is unsafe.
    """
    if previous_d is None or previous_h is None:
        return current_d

    if bool(torch.all(previous_h == 0).item()):
        return current_d

    ratio = (current_h / previous_h).abs().clamp(min=0.25, max=4.0)
    return (1.0 + 0.5 * ratio) * current_d - (0.5 * ratio) * previous_d


def _ralston_step(
    model,
    x: Tensor,
    sigma: Tensor,
    sigma_next: Tensor,
    d1: Tensor,
    s_in: Tensor,
    extra_args: dict,
    predictor_gain: float = 1.0,
    output_gain: float = 1.0,
    limit_ratio: Optional[float] = None,
) -> Tensor:
    """Second-order Ralston RK step (stage at 2/3 of the interval)."""
    h = sigma_next - sigma
    c2 = 2.0 / 3.0
    sigma_2 = sigma + c2 * h
    x_2 = x + d1 * (c2 * h * predictor_gain)
    denoised_2 = _eval(model, x_2, sigma_2, s_in, extra_args)
    d2 = _derivative(x_2, sigma_2, denoised_2)
    direction = 0.25 * d1 + 0.75 * d2
    if limit_ratio is not None:
        direction = _limit_direction(direction, d1, limit_ratio)
    return x + direction * (h * output_gain)


def _heun_corrected_step(
    model,
    x: Tensor,
    sigma: Tensor,
    sigma_next: Tensor,
    predictor_direction: Tensor,
    current_d: Tensor,
    s_in: Tensor,
    extra_args: dict,
) -> Tensor:
    """Predict with a multistep direction, correct with a Heun trapezoid."""
    h = sigma_next - sigma
    x_predict = x + predictor_direction * h
    denoised_2 = _eval(model, x_predict, sigma_next, s_in, extra_args)
    d2 = _derivative(x_predict, sigma_next, denoised_2)
    return x + 0.5 * (current_d + d2) * h


@torch.no_grad()
def sample_DOGMA_klein_distilled_REBUILD(
    model,
    x: Tensor,
    sigmas: Tensor,
    extra_args=None,
    callback=None,
    disable=None,
    **kwargs,
) -> Tensor:
    """Few-step decisive sampler for T2I, strong edits, and damaged upscale tiles.

    Uses an over-relaxed Ralston predictor/corrector. The over-relaxation is
    strongest in the first half of the trajectory and fades to an ordinary
    second-order solve. Two model calls are used for every non-terminal step.
    """
    extra_args = _args(extra_args)
    s_in = x.new_ones([x.shape[0]])
    total = max(1, len(sigmas) - 1)

    for i in range(total):
        sigma, sigma_next = sigmas[i], sigmas[i + 1]
        denoised = _eval(model, x, sigma, s_in, extra_args)
        _emit_callback(callback, x, i, sigma, denoised)

        if _is_zero_sigma(sigma_next):
            x = denoised
            continue

        d1 = _derivative(x, sigma, denoised)
        progress = i / max(1, total - 1)
        early = max(0.0, 1.0 - progress / 0.60)
        predictor_gain = 1.0 + 0.10 * early
        output_gain = 1.0 + 0.055 * early
        x = _ralston_step(
            model,
            x,
            sigma,
            sigma_next,
            d1,
            s_in,
            extra_args,
            predictor_gain=predictor_gain,
            output_gain=output_gain,
            limit_ratio=1.75,
        )

    return x


@torch.no_grad()
def sample_DOGMA_klein_distilled_BALANCED(
    model,
    x: Tensor,
    sigmas: Tensor,
    extra_args=None,
    callback=None,
    disable=None,
    **kwargs,
) -> Tensor:
    """General-purpose few-step sampler for Klein distilled.

    A plain second-order Ralston solver: more accurate than Euler while avoiding
    the extra stage cost of a third-order method.
    """
    extra_args = _args(extra_args)
    s_in = x.new_ones([x.shape[0]])
    total = max(1, len(sigmas) - 1)

    for i in range(total):
        sigma, sigma_next = sigmas[i], sigmas[i + 1]
        denoised = _eval(model, x, sigma, s_in, extra_args)
        _emit_callback(callback, x, i, sigma, denoised)

        if _is_zero_sigma(sigma_next):
            x = denoised
            continue

        d1 = _derivative(x, sigma, denoised)
        x = _ralston_step(model, x, sigma, sigma_next, d1, s_in, extra_args)

    return x


@torch.no_grad()
def sample_DOGMA_klein_distilled_DETAIL(
    model,
    x: Tensor,
    sigmas: Tensor,
    extra_args=None,
    callback=None,
    disable=None,
    **kwargs,
) -> Tensor:
    """High-accuracy few-step sampler for soft edits and upscale refinement.

    Uses the three-stage, third-order Bogacki-Shampine main formula at non-final
    intervals. All internal stages remain above sigma zero. The terminal interval
    snaps to the model's denoised prediction to avoid residual noise.
    """
    extra_args = _args(extra_args)
    s_in = x.new_ones([x.shape[0]])
    total = max(1, len(sigmas) - 1)

    for i in range(total):
        sigma, sigma_next = sigmas[i], sigmas[i + 1]
        denoised_1 = _eval(model, x, sigma, s_in, extra_args)
        _emit_callback(callback, x, i, sigma, denoised_1)

        if _is_zero_sigma(sigma_next):
            x = denoised_1
            continue

        h = sigma_next - sigma
        k1 = _derivative(x, sigma, denoised_1)

        sigma_2 = sigma + 0.5 * h
        x_2 = x + 0.5 * h * k1
        denoised_2 = _eval(model, x_2, sigma_2, s_in, extra_args)
        k2 = _derivative(x_2, sigma_2, denoised_2)

        sigma_3 = sigma + 0.75 * h
        x_3 = x + 0.75 * h * k2
        denoised_3 = _eval(model, x_3, sigma_3, s_in, extra_args)
        k3 = _derivative(x_3, sigma_3, denoised_3)

        direction = (2.0 / 9.0) * k1 + (1.0 / 3.0) * k2 + (4.0 / 9.0) * k3
        x = x + h * direction

    return x


@torch.no_grad()
def sample_DOGMA_klein_basemodel_REBUILD(
    model,
    x: Tensor,
    sigmas: Tensor,
    extra_args=None,
    callback=None,
    disable=None,
    **kwargs,
) -> Tensor:
    """Fast, decisive many-step sampler for strong base-model reconstruction.

    Uses one model call per step and a variable-step AB2 momentum direction.
    A small early over-relaxation encourages movement away from malformed source
    detail; it fades completely before the second half of the trajectory.
    """
    extra_args = _args(extra_args)
    s_in = x.new_ones([x.shape[0]])
    total = max(1, len(sigmas) - 1)
    previous_d = None
    previous_h = None

    for i in range(total):
        sigma, sigma_next = sigmas[i], sigmas[i + 1]
        denoised = _eval(model, x, sigma, s_in, extra_args)
        _emit_callback(callback, x, i, sigma, denoised)

        if _is_zero_sigma(sigma_next):
            x = denoised
            continue

        h = sigma_next - sigma
        d = _derivative(x, sigma, denoised)
        direction = _variable_ab2(d, previous_d, h, previous_h)
        direction = _limit_direction(direction, d, 1.65)

        progress = i / max(1, total - 1)
        early = max(0.0, 1.0 - progress / 0.55)
        gain = 1.0 + 0.065 * early
        x = x + direction * (h * gain)

        previous_d = d
        previous_h = h

    return x


@torch.no_grad()
def sample_DOGMA_klein_basemodel_BALANCED(
    model,
    x: Tensor,
    sigmas: Tensor,
    extra_args=None,
    callback=None,
    disable=None,
    **kwargs,
) -> Tensor:
    """General-purpose base-model sampler with selective correction.

    Runs variable-step AB2 for efficiency, then performs a Heun correction every
    sixth interval and throughout the final 15 percent. This spends extra model
    calls where drift is most likely to become visible without doubling the cost
    of the whole 20-50 step trajectory.
    """
    extra_args = _args(extra_args)
    s_in = x.new_ones([x.shape[0]])
    total = max(1, len(sigmas) - 1)
    previous_d = None
    previous_h = None

    for i in range(total):
        sigma, sigma_next = sigmas[i], sigmas[i + 1]
        denoised = _eval(model, x, sigma, s_in, extra_args)
        _emit_callback(callback, x, i, sigma, denoised)

        if _is_zero_sigma(sigma_next):
            x = denoised
            continue

        h = sigma_next - sigma
        d = _derivative(x, sigma, denoised)
        predictor = _variable_ab2(d, previous_d, h, previous_h)
        predictor = _limit_direction(predictor, d, 1.55)

        progress = i / max(1, total - 1)
        use_corrector = ((i + 1) % 6 == 0) or (progress >= 0.85)
        if use_corrector:
            x = _heun_corrected_step(
                model,
                x,
                sigma,
                sigma_next,
                predictor,
                d,
                s_in,
                extra_args,
            )
        else:
            x = x + predictor * h

        previous_d = d
        previous_h = h

    return x


@torch.no_grad()
def sample_DOGMA_klein_basemodel_DETAIL(
    model,
    x: Tensor,
    sigmas: Tensor,
    extra_args=None,
    callback=None,
    disable=None,
    **kwargs,
) -> Tensor:
    """Fidelity/detail sampler for soft edits and already-good upscale tiles.

    Uses efficient variable-step AB2 while large-scale structure is established,
    then switches to second-order Ralston for the final 45 percent, concentrating
    extra evaluations in the low-sigma region where fine structure settles.
    """
    extra_args = _args(extra_args)
    s_in = x.new_ones([x.shape[0]])
    total = max(1, len(sigmas) - 1)
    previous_d = None
    previous_h = None

    for i in range(total):
        sigma, sigma_next = sigmas[i], sigmas[i + 1]
        denoised = _eval(model, x, sigma, s_in, extra_args)
        _emit_callback(callback, x, i, sigma, denoised)

        if _is_zero_sigma(sigma_next):
            x = denoised
            continue

        h = sigma_next - sigma
        d = _derivative(x, sigma, denoised)
        progress = i / max(1, total - 1)

        if progress < 0.55:
            direction = _variable_ab2(d, previous_d, h, previous_h)
            direction = _limit_direction(direction, d, 1.45)
            x = x + direction * h
        else:
            x = _ralston_step(model, x, sigma, sigma_next, d, s_in, extra_args)

        previous_d = d
        previous_h = h

    return x


SAMPLER_FUNCTIONS: Dict[str, SamplerFunction] = {
    DISTILLED_REBUILD: sample_DOGMA_klein_distilled_REBUILD,
    DISTILLED_BALANCED: sample_DOGMA_klein_distilled_BALANCED,
    DISTILLED_DETAIL: sample_DOGMA_klein_distilled_DETAIL,
    BASE_REBUILD: sample_DOGMA_klein_basemodel_REBUILD,
    BASE_BALANCED: sample_DOGMA_klein_basemodel_BALANCED,
    BASE_DETAIL: sample_DOGMA_klein_basemodel_DETAIL,
}

SAMPLER_NAMES = tuple(SAMPLER_FUNCTIONS.keys())

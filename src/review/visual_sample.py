"""C3's image budget (plan §13): "flagged scenes + 20% sample", never more
than a handful of images per run -- Gemini flash is cheap per call, not per
image, so the real cost driver here is keeping the request small and the
sample representative, not squeezing pennies.

Deterministic on purpose: which scenes get a human (or model) look should
never depend on RNG state, so the same run's own inputs always produce the
same sample -- reproducible for debugging and for tests.
"""
from __future__ import annotations

DEFAULT_MAX_IMAGES = 8
DEFAULT_SAMPLE_FRACTION = 0.2


def select_scenes_for_visual_audit(
    scene_ids_in_order: list[str],
    flagged_scene_ids: set[str],
    max_images: int = DEFAULT_MAX_IMAGES,
    sample_fraction: float = DEFAULT_SAMPLE_FRACTION,
) -> list[str]:
    """Every flagged scene (in plan order, capped at `max_images` on its own
    if flagged scenes alone exceed the budget -- a real render problem
    always outranks a representativeness sample), then a systematic
    (evenly-spaced-by-index, never `random.sample`) pick of the remaining
    unflagged scenes filling out whatever budget is left. The sample size
    targets `sample_fraction` of the WHOLE video (not just the unflagged
    remainder), matching plan §13's "flagged scenes + 20% sample" reading
    literally -- a short video with everything flagged already gets its
    full picture; a long clean video still gets a real spread checked.
    """
    flagged = [s for s in scene_ids_in_order if s in flagged_scene_ids][:max_images]
    remaining_budget = max_images - len(flagged)
    if remaining_budget <= 0:
        return flagged

    unflagged = [s for s in scene_ids_in_order if s not in flagged_scene_ids]
    if not unflagged:
        return flagged

    target_sample_size = round(len(scene_ids_in_order) * sample_fraction)
    sample_size = min(target_sample_size, remaining_budget, len(unflagged))
    if sample_size <= 0:
        return flagged

    step = len(unflagged) / sample_size
    sampled_indices = sorted({int(i * step) for i in range(sample_size)})
    sample = [unflagged[i] for i in sampled_indices]

    return flagged + sample

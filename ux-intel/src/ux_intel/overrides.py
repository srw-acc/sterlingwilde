"""Reviewer overrides: load, apply, and serialize human corrections.

The review HTML lets a reviewer suppress observations, edit fields, and mark
items as approved. Those edits are downloaded as `outputs/overrides.json` and
re-applied on the next `synthesize --apply-overrides` run.

Keeping this in its own module so both the CLI and the synthesize stage can
reach for it without importing each other.
"""

from __future__ import annotations

from pathlib import Path

from .schemas import Observation, ObservationOverride, ObservationSet, OverrideSet


def load_overrides(path: Path) -> OverrideSet:
    if not path.exists():
        return OverrideSet()
    return OverrideSet.model_validate_json(path.read_text())


def apply_overrides(obs_set: ObservationSet, overrides: OverrideSet) -> ObservationSet:
    """Return a new ObservationSet with overrides applied.

    Suppressed observations are dropped. Field-level overrides are merged onto
    the original observation. The original ObservationSet is not mutated.
    """
    by_id: dict[str, ObservationOverride] = {o.observation_id: o for o in overrides.overrides}
    kept: list[Observation] = []
    for obs in obs_set.observations:
        ov = by_id.get(obs.id)
        if ov is None:
            kept.append(obs)
            continue
        if ov.suppressed:
            continue
        kept.append(_merge(obs, ov))
    return ObservationSet(observations=kept)


def _merge(obs: Observation, ov: ObservationOverride) -> Observation:
    data = obs.model_dump()
    for field in ("kind", "sentiment", "summary", "confidence", "implementation_hint"):
        new_value = getattr(ov, field)
        if new_value is not None:
            data[field] = new_value
    return Observation.model_validate(data)


def summarize(overrides: OverrideSet) -> str:
    """Short human-readable summary for log output."""
    if not overrides.overrides:
        return "no overrides"
    suppressed = sum(1 for o in overrides.overrides if o.suppressed)
    edited = sum(
        1 for o in overrides.overrides
        if not o.suppressed
        and any(getattr(o, f) is not None for f in ("kind", "sentiment", "summary", "confidence", "implementation_hint"))
    )
    approved = sum(1 for o in overrides.overrides if o.approved and not o.suppressed)
    return f"{len(overrides.overrides)} overrides ({suppressed} suppressed, {edited} edited, {approved} approved)"

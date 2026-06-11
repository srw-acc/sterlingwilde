"""Stage 5: multimodal Claude analysis.

For each moment we make one Claude call:
  - system prompt is the (cached) extraction rubric
  - user content is the moment's transcript text + its primary frame image
  - the response is constrained to a JSON schema matching ObservationDraft

The system prompt is held byte-stable across all moments in a session, so
prompt caching dominates the spend after the first call.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path

import anthropic

from .prompts import OBSERVATION_SYSTEM_PROMPT, OBSERVATION_USER_PROMPT_TEMPLATE
from .schemas import (
    FeedbackKind,
    Moment,
    MomentSet,
    Observation,
    ObservationSet,
    Sentiment,
)
from .session import STAGE_ANALYZE, Session, write_json

MODEL = "claude-opus-4-7"

OBSERVATION_DRAFT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "kind": {"type": "string", "enum": [k.value for k in FeedbackKind]},
        "sentiment": {"type": "string", "enum": [s.value for s in Sentiment]},
        "summary": {"type": "string"},
        "likely_ui_element": {"type": ["string", "null"]},
        "likely_screen": {"type": ["string", "null"]},
        "interpretation_basis": {"type": "string"},
        "confidence": {"type": "number"},
        "implementation_hint": {"type": ["string", "null"]},
    },
    "required": [
        "kind", "sentiment", "summary",
        "likely_ui_element", "likely_screen",
        "interpretation_basis", "confidence", "implementation_hint",
    ],
}


def run(
    session: Session,
    model: str = MODEL,
    api_key: str | None = None,
    effort: str = "high",
) -> ObservationSet:
    session.require_dependencies(STAGE_ANALYZE)
    session.mark_running(STAGE_ANALYZE)
    try:
        client = anthropic.Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))
        moment_set = MomentSet.model_validate_json(session.moments_path.read_text())

        observations: list[Observation] = []
        for moment in moment_set.moments:
            obs = _analyze_moment(client, session.root, moment, model=model, effort=effort)
            observations.append(obs)

        obs_set = ObservationSet(observations=observations)
        write_json(session.observations_path, obs_set)
        session.mark_completed(STAGE_ANALYZE, notes=f"{len(observations)} observations")
        return obs_set
    except Exception as exc:
        session.mark_failed(STAGE_ANALYZE, str(exc))
        raise


def _analyze_moment(
    client: anthropic.Anthropic,
    session_root: Path,
    moment: Moment,
    model: str,
    effort: str,
) -> Observation:
    frame_b64, frame_media = _load_frame(session_root / moment.primary_frame)

    user_text = OBSERVATION_USER_PROMPT_TEMPLATE.format(
        moment_id=moment.id,
        t_start=moment.start,
        t_end=moment.end,
        transcript=moment.transcript,
    )

    response = client.messages.create(
        model=model,
        max_tokens=8000,
        thinking={"type": "adaptive"},
        output_config={
            "effort": effort,
            "format": {
                "type": "json_schema",
                "schema": OBSERVATION_DRAFT_SCHEMA,
            },
        },
        system=[
            {
                "type": "text",
                "text": OBSERVATION_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": frame_media,
                            "data": frame_b64,
                        },
                    },
                    {"type": "text", "text": user_text},
                ],
            }
        ],
    )

    text = next((b.text for b in response.content if b.type == "text"), "")
    draft = json.loads(text)

    return Observation(
        id=f"o{int(moment.id[1:]):04d}",
        moment_id=moment.id,
        quote=moment.transcript,
        t_start=moment.start,
        t_end=moment.end,
        frame_ref=moment.primary_frame,
        kind=FeedbackKind(draft["kind"]),
        sentiment=Sentiment(draft["sentiment"]),
        summary=draft["summary"],
        likely_ui_element=draft["likely_ui_element"],
        likely_screen=draft["likely_screen"],
        interpretation_basis=draft["interpretation_basis"],
        confidence=float(draft["confidence"]),
        implementation_hint=draft["implementation_hint"],
    )


def _load_frame(path: Path) -> tuple[str, str]:
    data = path.read_bytes()
    ext = path.suffix.lower()
    media = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }.get(ext, "image/jpeg")
    return base64.standard_b64encode(data).decode("utf-8"), media

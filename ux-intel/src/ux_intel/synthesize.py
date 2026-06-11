"""Stage 6: synthesis.

One Claude call ingests all observations and emits:
  - clusters (grouped themes)
  - draft issues for actionable clusters
  - a human-readable review document
  - a denser context cartridge tuned for AI agents

Streaming is on because the markdown outputs can be long (review +
cartridge + issue bodies easily exceed 16k tokens with `effort: high`).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import anthropic

from . import overrides as overrides_mod
from .prompts import CLUSTER_SYSTEM_PROMPT
from .schemas import (
    Cluster,
    FeedbackKind,
    IssueDraft,
    ObservationSet,
    SynthesisOutput,
)
from .session import STAGE_SYNTHESIZE, Session, write_json

MODEL = "claude-opus-4-7"

SYNTHESIS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "clusters": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string"},
                    "theme": {"type": "string"},
                    "summary": {"type": "string"},
                    "kind": {"type": "string", "enum": [k.value for k in FeedbackKind]},
                    "observation_ids": {"type": "array", "items": {"type": "string"}},
                    "severity": {"type": "string", "enum": ["low", "medium", "high"]},
                    "confidence": {"type": "number"},
                },
                "required": [
                    "id", "theme", "summary", "kind",
                    "observation_ids", "severity", "confidence",
                ],
            },
        },
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                    "body_markdown": {"type": "string"},
                    "labels": {"type": "array", "items": {"type": "string"}},
                    "cluster_id": {"type": "string"},
                    "evidence_observation_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": [
                    "id", "title", "body_markdown", "labels",
                    "cluster_id", "evidence_observation_ids",
                ],
            },
        },
        "review_markdown": {"type": "string"},
        "context_cartridge_markdown": {"type": "string"},
    },
    "required": [
        "clusters", "issues",
        "review_markdown", "context_cartridge_markdown",
    ],
}


def run_from_pack(session: Session, bundle_path: Path | None = None) -> SynthesisOutput:
    """Finalize the synthesize stage from a `synthesis.json` bundle produced
    by a Claude session (chat or CLI). No API call — just split the bundle
    into the four artifact files the rest of the pipeline expects.
    """
    session.require_dependencies(STAGE_SYNTHESIZE)
    bundle_path = bundle_path or (session.root / "outputs" / "synthesis.json")
    if not bundle_path.exists():
        raise FileNotFoundError(
            f"No synthesis bundle at {bundle_path}. Run `ux-intel pack <session> "
            "--stage synthesize`, hand the pack to a Claude instance, then write "
            "its output to that path."
        )
    session.mark_running(STAGE_SYNTHESIZE)
    try:
        result = json.loads(bundle_path.read_text())
        clusters = [Cluster.model_validate(c) for c in result["clusters"]]
        issues = [IssueDraft.model_validate(i) for i in result["issues"]]
        output = SynthesisOutput(
            clusters=clusters,
            issues=issues,
            review_markdown=result["review_markdown"],
            context_cartridge_markdown=result["context_cartridge_markdown"],
        )
        write_json(session.clusters_path, {"clusters": [c.model_dump() for c in clusters]})
        write_json(session.issues_path, {"issues": [i.model_dump() for i in issues]})
        session.review_path.write_text(output.review_markdown)
        session.cartridge_path.write_text(output.context_cartridge_markdown)
        session.mark_completed(
            STAGE_SYNTHESIZE,
            notes=f"{len(clusters)} clusters, {len(issues)} draft issues (from pack)",
        )
        return output
    except Exception as exc:
        session.mark_failed(STAGE_SYNTHESIZE, str(exc))
        raise


def run(
    session: Session,
    model: str = MODEL,
    api_key: str | None = None,
    effort: str = "high",
    apply_overrides: bool = False,
) -> SynthesisOutput:
    session.require_dependencies(STAGE_SYNTHESIZE)
    session.mark_running(STAGE_SYNTHESIZE)
    try:
        client = anthropic.Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))
        obs_set = ObservationSet.model_validate_json(session.observations_path.read_text())

        override_note = None
        if apply_overrides:
            overrides = overrides_mod.load_overrides(session.overrides_path)
            obs_set = overrides_mod.apply_overrides(obs_set, overrides)
            override_note = overrides_mod.summarize(overrides)

        if not obs_set.observations:
            raise RuntimeError("No observations to synthesize. Re-run the analyze stage.")

        payload = _build_user_payload(obs_set)

        with client.messages.stream(
            model=model,
            max_tokens=32000,
            thinking={"type": "adaptive"},
            output_config={
                "effort": effort,
                "format": {"type": "json_schema", "schema": SYNTHESIS_SCHEMA},
            },
            system=[
                {
                    "type": "text",
                    "text": CLUSTER_SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": payload}],
        ) as stream:
            final = stream.get_final_message()

        text = next((b.text for b in final.content if b.type == "text"), "")
        result = json.loads(text)

        clusters = [Cluster.model_validate(c) for c in result["clusters"]]
        issues = [IssueDraft.model_validate(i) for i in result["issues"]]
        output = SynthesisOutput(
            clusters=clusters,
            issues=issues,
            review_markdown=result["review_markdown"],
            context_cartridge_markdown=result["context_cartridge_markdown"],
        )

        write_json(session.clusters_path, {"clusters": [c.model_dump() for c in clusters]})
        write_json(session.issues_path, {"issues": [i.model_dump() for i in issues]})
        session.review_path.write_text(output.review_markdown)
        session.cartridge_path.write_text(output.context_cartridge_markdown)

        notes = f"{len(clusters)} clusters, {len(issues)} draft issues"
        if override_note is not None:
            notes += f"; {override_note}"
        session.mark_completed(STAGE_SYNTHESIZE, notes=notes)
        return output
    except Exception as exc:
        session.mark_failed(STAGE_SYNTHESIZE, str(exc))
        raise


def _build_user_payload(obs_set: ObservationSet) -> str:
    compact = [
        {
            "id": o.id,
            "moment_id": o.moment_id,
            "t": [round(o.t_start, 2), round(o.t_end, 2)],
            "kind": o.kind.value,
            "sentiment": o.sentiment.value,
            "summary": o.summary,
            "ui_element": o.likely_ui_element,
            "screen": o.likely_screen,
            "confidence": round(o.confidence, 2),
            "quote": o.quote,
            "implementation_hint": o.implementation_hint,
        }
        for o in obs_set.observations
    ]
    return (
        "Here are the observations from one walkthrough. Produce the four-part "
        "synthesis described in the system prompt.\n\n"
        "```json\n"
        + json.dumps(compact, indent=2)
        + "\n```"
    )

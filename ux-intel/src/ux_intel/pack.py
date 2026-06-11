"""Prompt packs: run analyze and synthesize *without* the Anthropic API.

The pack command emits a directory the user can hand to any Claude interface
(Claude Code, Claude.ai chat, the `claude` CLI) to do the LLM work locally.
The receiving Claude reads the rubric, the moments, and the frames, then
writes the next-stage JSON back to a known path. The rest of the pipeline
picks up from there.

Trade-off vs. the API path: requires manual handoff and no prompt caching,
but costs $0 in API spend and keeps interpretation in a steerable interactive
loop. Useful for early development and for users who want a human in front
of every observation.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from .prompts import CLUSTER_SYSTEM_PROMPT, OBSERVATION_SYSTEM_PROMPT
from .schemas import FeedbackKind, MomentSet, ObservationSet, Sentiment
from .session import Session


def pack_analyze(session: Session) -> Path:
    """Produce a self-contained directory for the analyze stage."""
    moments = MomentSet.model_validate_json(session.moments_path.read_text()).moments

    pack_dir = session.root / "outputs" / "packs" / "analyze"
    pack_dir.mkdir(parents=True, exist_ok=True)
    frames_dir = pack_dir / "frames"
    frames_dir.mkdir(exist_ok=True)

    # Copy referenced frames into the pack. Cheap (~30 × 50KB). Hardlink would
    # be faster but breaks cross-filesystem moves; copy keeps the pack portable.
    frame_map: dict[str, str] = {}
    for m in moments:
        src = session.root / m.primary_frame
        if not src.exists():
            continue
        dest_name = Path(m.primary_frame).name
        dest = frames_dir / dest_name
        if not dest.exists() or dest.stat().st_size != src.stat().st_size:
            shutil.copy2(src, dest)
        frame_map[m.id] = f"frames/{dest_name}"

    # moments.md — one section per moment with transcript and image reference.
    moments_md = _render_moments_md(moments, frame_map)
    (pack_dir / "moments.md").write_text(moments_md, encoding="utf-8")

    # README.md — instructions for whichever Claude picks this up.
    target_out = session.observations_path  # absolute path
    relative_out = "../../intermediates/observations.json"
    readme = _render_analyze_readme(
        session_id=session.state().session_id,
        n_moments=len(moments),
        target_path_relative=relative_out,
        target_path_absolute=str(target_out),
    )
    (pack_dir / "README.md").write_text(readme, encoding="utf-8")

    # rubric.md — the full extraction rubric. Kept separate so chat-only users
    # can paste it in one block.
    (pack_dir / "rubric.md").write_text(OBSERVATION_SYSTEM_PROMPT, encoding="utf-8")

    return pack_dir


def pack_synthesize(session: Session) -> Path:
    """Produce a self-contained directory for the synthesize stage."""
    obs_set = ObservationSet.model_validate_json(session.observations_path.read_text())

    pack_dir = session.root / "outputs" / "packs" / "synthesize"
    pack_dir.mkdir(parents=True, exist_ok=True)

    # Compact observations for the LLM (drop verbose fields not needed for clustering).
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
    (pack_dir / "observations.json").write_text(
        json.dumps({"observations": compact}, indent=2), encoding="utf-8"
    )

    (pack_dir / "rubric.md").write_text(CLUSTER_SYSTEM_PROMPT, encoding="utf-8")

    readme = _render_synthesize_readme(
        session_id=session.state().session_id,
        n_observations=len(compact),
        session_root=str(session.root),
    )
    (pack_dir / "README.md").write_text(readme, encoding="utf-8")

    return pack_dir


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------


def _render_moments_md(moments, frame_map: dict[str, str]) -> str:
    lines = [
        "# Moments",
        "",
        "Each moment is one chunk of narrated walkthrough audio paired with a screenshot",
        "taken near the middle of that chunk. For each moment, produce one observation.",
        "",
        "Copy the `moment_id`, `quote`, `t_start`, `t_end`, and `frame_ref` fields",
        "verbatim into your output — do not invent them.",
        "",
    ]
    for m in moments:
        frame_rel = frame_map.get(m.id, m.primary_frame)
        lines += [
            f"## moment_id: `{m.id}`",
            "",
            f"- **t_start:** {m.start:.2f}",
            f"- **t_end:** {m.end:.2f}",
            f"- **frame_ref:** `{m.primary_frame}`",
            "",
            "**Transcript (quote):**",
            "",
            f"> {m.transcript.strip()}",
            "",
            f"![frame for {m.id}]({frame_rel})",
            "",
            "---",
            "",
        ]
    return "\n".join(lines)


def _render_analyze_readme(
    session_id: str,
    n_moments: int,
    target_path_relative: str,
    target_path_absolute: str,
) -> str:
    kinds = ", ".join(k.value for k in FeedbackKind)
    sentiments = ", ".join(s.value for s in Sentiment)
    return f"""\
# Analyze pack — session `{session_id}`

This directory has everything you need to produce structured UX observations
from a narrated walkthrough. {n_moments} moments are queued for analysis.

## What to do

1. Read `rubric.md` — the full extraction rubric.
2. Read `moments.md` — the moments with transcripts and image references.
   Images are in `frames/` and are referenced relatively.
3. For each moment, produce one observation following the rubric.
4. Write your output as a single JSON file at:
   ```
   {target_path_relative}
   ```
   (absolute: `{target_path_absolute}`)

## Output format

```json
{{
  "observations": [
    {{
      "id": "o0000",
      "moment_id": "m0000",
      "quote": "<copy verbatim from moments.md>",
      "t_start": 0.0,
      "t_end": 12.4,
      "frame_ref": "intermediates/frames/frame-0000.jpg",
      "kind": "<one of: {kinds}>",
      "sentiment": "<one of: {sentiments}>",
      "summary": "1–2 sentence takeaway",
      "likely_ui_element": "string or null",
      "likely_screen": "string or null",
      "interpretation_basis": "1 sentence on how you arrived at this",
      "confidence": 0.0,
      "implementation_hint": "string or null"
    }}
  ]
}}
```

Important:
- `id` should be `o0000`, `o0001`, ... in moment order.
- `moment_id`, `quote`, `t_start`, `t_end`, `frame_ref` are copied from `moments.md` — don't invent.
- `confidence` is a float in [0.0, 1.0]. Use lower numbers freely; see rubric.

## When you're done

The next pipeline stage (`ux-intel synthesize`) will pick up
`intermediates/observations.json` automatically. Or you can run
`ux-intel pack <session-dir> --stage synthesize` to produce the synthesize pack.
"""


def _render_synthesize_readme(session_id: str, n_observations: int, session_root: str) -> str:
    return f"""\
# Synthesize pack — session `{session_id}`

{n_observations} observations are ready to be clustered and turned into a review.

## What to do

1. Read `rubric.md` — the synthesis rubric.
2. Read `observations.json` — the observations from the analyze stage.
3. Produce four artifacts as a single JSON file (see schema below).
4. Write your output to four files in the session's `outputs/` directory:
   - `clusters.json`
   - `issues.json`
   - `review.md` (the markdown content from `review_markdown`)
   - `context.md` (the markdown content from `context_cartridge_markdown`)

   Or, if it's easier, dump the entire bundle as `outputs/synthesis.json` and
   the next pipeline step will split it apart.

## Session root

```
{session_root}
```

## Output bundle shape

```json
{{
  "clusters": [
    {{
      "id": "cluster-0001",
      "theme": "...",
      "summary": "...",
      "kind": "...",
      "observation_ids": ["o0000", "o0001"],
      "severity": "low|medium|high",
      "confidence": 0.0
    }}
  ],
  "issues": [
    {{
      "id": "issue-0001",
      "title": "...",
      "body_markdown": "...",
      "labels": ["..."],
      "cluster_id": "cluster-0001",
      "evidence_observation_ids": ["o0000"]
    }}
  ],
  "review_markdown": "...",
  "context_cartridge_markdown": "..."
}}
```

After you've written the artifacts, run `ux-intel review <session-dir>` to
regenerate `review.html` against the synthesized outputs.
"""

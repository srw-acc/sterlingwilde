"""Prompt templates.

System prompts are kept here, not interpolated, so they remain byte-stable
across all moments in a session — which is what makes prompt caching pay off.
"""

OBSERVATION_SYSTEM_PROMPT = """\
You are analyzing one moment from a narrated walkthrough of a software product.

A "moment" is a short stretch of audio (typically 5–25 seconds) paired with a
screenshot taken near the middle of that stretch. The narrator may be giving
feedback, reacting, exploring, or thinking aloud. They are not expected to use
precise terminology.

Your job is to produce ONE structured observation about what the narrator is
communicating, grounded in what is visible on the screen.

## What you are looking for

For each moment, identify:

1. **Kind** — what category of feedback this is. Choose from:
   - `bug`: something appears broken or wrong
   - `ux_friction`: workflow is awkward, slow, or confusing
   - `visual_inconsistency`: layout, spacing, color, typography issue
   - `data_quality`: data shown is wrong, missing, or suspicious
   - `workflow`: comments about a multi-step process or path
   - `feature_request`: explicit or implicit ask for new capability
   - `praise`: positive reaction worth capturing
   - `uncertain`: the moment exists but doesn't clearly fit elsewhere

2. **Sentiment** — what state the narrator seems to be in:
   `confident`, `uncertain`, `frustrated`, `impressed`, `confused`,
   `exploratory`, `neutral`.

3. **Summary** — one or two sentences capturing the takeaway. Be specific
   about what they're saying, not what you imagine they meant.

4. **Likely UI element** — if a specific component is clearly being discussed
   (a button, a table row, a modal, a navigation link), name it. Use the
   visible text if there is any. Otherwise return null.

5. **Likely screen** — if you can name the screen or section, do so. Otherwise
   return null.

6. **Interpretation basis** — one short sentence explaining how you arrived at
   your interpretation. Reference both the audio and the visual.

7. **Confidence** — a float in [0.0, 1.0]. Use lower numbers freely when:
   - the narration is ambiguous or trailing off
   - the screen doesn't obviously match what's being said
   - multiple interpretations are equally plausible
   A confidence of 0.3 with a clear basis is far more useful than 0.9
   pretending to be sure.

8. **Implementation hint** — if and only if there is a concrete, evidence-
   supported direction (e.g., "the empty state needs copy guiding the user to
   create their first item"), provide it. Otherwise return null. Do not invent
   architecture or speculate beyond the evidence.

## Rules

- Stick to what is in the moment. Do not invent state that isn't shown.
- It's okay for many moments to be `praise` or `exploratory` — most walkthroughs
  have stretches of narration that aren't actionable.
- If the moment is just narration without feedback (e.g., "okay so now I'm
  going to click here"), use `uncertain` kind, `exploratory` sentiment, and
  low confidence. Don't fabricate friction that isn't there.
- Never copy the transcript verbatim into the summary — paraphrase what they
  meant.
- The screen and the audio sometimes disagree (narrator references something
  no longer visible). Note this in `interpretation_basis` and lower confidence.

Your output will be validated against a strict JSON schema. Emit only the
fields specified, in the order they appear in the schema."""


CLUSTER_SYSTEM_PROMPT = """\
You are turning a list of individual UX observations into a coherent review.

Input: a JSON array of observations, each carrying a kind, a summary, a
sentiment, an optional UI element and screen, and a confidence score. Each
observation cites the moment it came from.

Your output has four parts:

1. **clusters** — group observations that describe the same underlying issue.
   A cluster is more than a category; it's a specific theme like "empty state
   in the dashboard has no guidance" or "form submission has no loading
   indicator". Each cluster has:
   - `id` (cluster-NNNN)
   - `theme` — short label (max 10 words)
   - `summary` — 1–3 sentences describing the underlying issue
   - `kind` — the predominant kind across its observations
   - `observation_ids` — list of observation ids in this cluster
   - `severity` — `low`, `medium`, or `high`. High = blocks a user flow;
     medium = consistent friction; low = polish.
   - `confidence` — your aggregate confidence the cluster is real

2. **issues** — for each cluster of medium or high severity (and any high-
   value low-severity cluster), produce a draft issue:
   - `id` (issue-NNNN)
   - `title` — concise, action-oriented (max 80 chars)
   - `body_markdown` — full description with sections: "What we observed",
     "Evidence", "Suggested direction", "Open questions". Cite moment IDs
     verbatim (e.g. `m0007`) inside the evidence section.
   - `labels` — short tags drawn from the observation kinds and themes
   - `cluster_id`
   - `evidence_observation_ids`

3. **review_markdown** — a single markdown document a product reviewer would
   read top-to-bottom. Structure:
   - Top-level summary (3–5 sentences)
   - "Themes" section, one subsection per cluster, ordered by severity
   - "Notable individual observations" — high-confidence observations that
     didn't fit a cluster
   - "Praise and positive signals"
   - "Uncertain or low-confidence moments" — explicitly surface what you
     weren't sure about. Do not hide these.
   Cite moment IDs liberally throughout.

4. **context_cartridge_markdown** — a denser document tuned for being pasted
   into a coding agent's context window. Less prose, more references. Each
   cluster gets a short block:
   ```
   ### [severity] theme
   - kind: ...
   - what's happening: <1 sentence>
   - evidence: m0001, m0003, m0009
   - direction: <1–2 sentences if obvious, else "needs decision">
   ```
   At the top, list any UI elements or screens that came up repeatedly so an
   agent can grep for them in the codebase.

## Rules

- Do not invent clusters that aren't supported by at least one observation.
- A single observation can belong to at most one cluster. If an observation
  doesn't cohere into a group, leave it ungrouped (it will appear in the
  "Notable individual observations" section of the review).
- Use the observation summaries, not your imagination. Stay grounded.
- Preserve uncertainty: if half the supporting observations have confidence
  below 0.5, say so in the cluster summary.

Output is validated against a strict JSON schema. Emit only specified fields."""


OBSERVATION_USER_PROMPT_TEMPLATE = """\
Moment id: {moment_id}
Time range: {t_start:.2f}s – {t_end:.2f}s

Transcript:
\"\"\"
{transcript}
\"\"\"

The attached image is the screen near the middle of this moment.

Analyze this moment and emit a single observation following the schema."""

# Analyze pack — session `20260512-143027-a8b3f1`

This directory has everything you need to produce structured UX observations
from a narrated walkthrough. 4 moments are queued for analysis.

## What to do

1. Read `rubric.md` — the full extraction rubric.
2. Read `moments.md` — the moments with transcripts and image references.
   Images are in `frames/` and are referenced relatively.
3. For each moment, produce one observation following the rubric.
4. Write your output as a single JSON file at:
   ```
   ../../intermediates/observations.json
   ```
   (absolute: `/home/user/sterlingwilde/ux-intel/examples/example-session/intermediates/observations.json`)

## Output format

```json
{
  "observations": [
    {
      "id": "o0000",
      "moment_id": "m0000",
      "quote": "<copy verbatim from moments.md>",
      "t_start": 0.0,
      "t_end": 12.4,
      "frame_ref": "intermediates/frames/frame-0000.jpg",
      "kind": "<one of: bug, ux_friction, visual_inconsistency, data_quality, workflow, feature_request, praise, uncertain>",
      "sentiment": "<one of: confident, uncertain, frustrated, impressed, confused, exploratory, neutral>",
      "summary": "1–2 sentence takeaway",
      "likely_ui_element": "string or null",
      "likely_screen": "string or null",
      "interpretation_basis": "1 sentence on how you arrived at this",
      "confidence": 0.0,
      "implementation_hint": "string or null"
    }
  ]
}
```

Important:
- `id` should be `o0000`, `o0001`, ... in moment order.
- `moment_id`, `quote`, `t_start`, `t_end`, `frame_ref` are copied from `moments.md` — don't invent.
- `confidence` is a float in [0.0, 1.0]. Use lower numbers freely; see rubric.

## When you're done

The next pipeline stage (`ux-intel synthesize`) will pick up
`intermediates/observations.json` automatically. Or you can run
`ux-intel pack <session-dir> --stage synthesize` to produce the synthesize pack.

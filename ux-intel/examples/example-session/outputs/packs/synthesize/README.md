# Synthesize pack — session `20260512-143027-a8b3f1`

4 observations are ready to be clustered and turned into a review.

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
/home/user/sterlingwilde/ux-intel/examples/example-session
```

## Output bundle shape

```json
{
  "clusters": [
    {
      "id": "cluster-0001",
      "theme": "...",
      "summary": "...",
      "kind": "...",
      "observation_ids": ["o0000", "o0001"],
      "severity": "low|medium|high",
      "confidence": 0.0
    }
  ],
  "issues": [
    {
      "id": "issue-0001",
      "title": "...",
      "body_markdown": "...",
      "labels": ["..."],
      "cluster_id": "cluster-0001",
      "evidence_observation_ids": ["o0000"]
    }
  ],
  "review_markdown": "...",
  "context_cartridge_markdown": "..."
}
```

After you've written the artifacts, run `ux-intel review <session-dir>` to
regenerate `review.html` against the synthesized outputs.

# ux-intel

Turn a narrated screen recording into structured, traceable UX feedback.

Drop in a video of someone narrating their way through your app. Out the
other end: a session directory of raw evidence, intermediate artifacts, a
human-readable review document, draft issues, and a "context cartridge"
designed for pasting into a coding agent.

See [`DESIGN.md`](DESIGN.md) for the architecture and design decisions.

## Install

Python 3.10+ and `ffmpeg` on `PATH`.

```bash
cd ux-intel
pip install -e .                        # API-only install
# or, for on-device transcription with no API key:
pip install -e ".[local]"               # adds faster-whisper

export ANTHROPIC_API_KEY=sk-ant-...     # always required (analysis stage)
export OPENAI_API_KEY=sk-...            # only if you use the API transcribe backend
```

## Transcription backends

Two options for the `transcribe` stage:

- **OpenAI Whisper API** (default) — fast, accurate, ~$0.006/min, requires `OPENAI_API_KEY`.
- **`faster-whisper` on-device** — no API key, runs on your CPU/GPU. First run downloads the model (~250MB for `small`). Pass `--local` to opt in.

```bash
ux-intel run video.mp4 --local                          # uses faster-whisper, model=small
ux-intel run video.mp4 --local --whisper-model medium   # bigger / more accurate
ux-intel run video.mp4 --local --whisper-model large-v3-turbo  # if you've already cached this model
```

On Apple Silicon the local backend defaults to `device=cpu` and `compute_type=int8`
(the fast CTranslate2 path — Metal isn't supported directly). Elsewhere it
defaults to `device=auto` and `compute_type=default`. Override either:

```bash
ux-intel run video.mp4 --local --whisper-device cpu --whisper-compute-type int8
```

Model cache: faster-whisper honors `HF_HOME` / `HF_HUB_CACHE` env vars. To
keep weights off your system disk, point those at an external drive, or pass
`--whisper-cache /Volumes/External/ml-cache`.

## Running without any AI

The first four stages — ingest, transcribe, frames, align — produce everything
you need to *see* the recording (transcript, screenshots, time alignment) with
zero API calls and no Anthropic / OpenAI keys. After `align`, the pipeline
auto-generates `outputs/review.html` in preview mode: a browsable page with
the timeline, every moment's transcript, and the matching screenshot.

```bash
ux-intel ingest      sessions/<id>
ux-intel transcribe  sessions/<id> --local              # uses faster-whisper
ux-intel frames      sessions/<id>
ux-intel align       sessions/<id>                      # writes a preview review.html
open                 sessions/<id>/outputs/review.html
```

Decide from there whether to invest in AI analysis.

## Adding AI analysis without spending on the Anthropic API

The analyze and synthesize stages normally hit Claude's API. You can opt out
and drive those stages through a chat or local CLI session instead. The
`pack` command emits a self-contained directory you hand to any Claude
interface (Claude Code, Claude.ai chat, `claude` CLI). The receiving Claude
writes the next-stage JSON, and the pipeline picks up from there.

```bash
# 1. Pack the analyze stage
ux-intel pack sessions/<id> --stage analyze
# -> outputs/packs/analyze/{README.md, rubric.md, moments.md, frames/}

# 2. Hand the pack to a Claude session, e.g. from the pack directory:
#    `claude "Read README.md and do the task."`
#    or upload the files to Claude.ai chat.
#    Claude writes intermediates/observations.json.

# 3. Pack the synthesize stage
ux-intel pack sessions/<id> --stage synthesize
# -> outputs/packs/synthesize/{README.md, rubric.md, observations.json}

# 4. Same — hand to Claude, which writes outputs/synthesis.json.

# 5. Finalize without calling the API:
ux-intel synthesize sessions/<id> --from-pack
ux-intel review    sessions/<id>
```

The pack directory's README.md is the authoritative spec for the receiving
Claude — it explains the output schema, the output path, and the rubric. Any
Claude that can read files and produce JSON can drive this.

## Quick start

### One-shot

```bash
ux-intel run path/to/walkthrough.mp4
```

This creates `sessions/<timestamp>-<id>/` and runs the full pipeline:

```
ingest → transcribe → frames → align → analyze → synthesize → review
```

When it finishes you'll see:

```
sessions/20260512-143027-a8b3f1/
  raw/                      # original input + extracted audio
  intermediates/            # transcript, frames, moments, observations
  outputs/
    review.md               # human-readable review (markdown)
    review.html             # self-contained interactive review (timeline + edits)
    issues.json             # draft issues
    clusters.json           # grouped themes
    context.md              # cartridge for coding agents
```

Open `outputs/review.html` in a browser to see screenshots aligned with
transcripts, the moment timeline, clusters, and issue drafts. The page works
offline — embed thumbnails are inlined as base64.

### Watch a synced folder

For an iPhone capture loop (record → save to iCloud/Dropbox/Drive), point the
watcher at the synced folder:

```bash
ux-intel watch ~/Library/Mobile\ Documents/com~apple~CloudDocs/Recordings
```

The watcher polls the directory (default every 30s), waits until a new file's
size and mtime are stable across two polls (so partial cloud uploads don't
trigger early processing), then runs the pipeline end-to-end. Already-seen
files are tracked in `<sessions-root>/.processed.json` so the watcher won't
double-process if you restart it. Pass `--process-existing` to also pick up
files that were already in the folder when the watcher started.

### Human review and corrections

Open `outputs/review.html`. For each observation you can:

- change the kind/sentiment via dropdown
- edit the summary inline
- suppress noisy observations
- mark items as explicitly approved

Click **Download corrections**. Drop the resulting `overrides.json` into the
session's `outputs/` directory, then re-synthesize:

```bash
ux-intel synthesize sessions/<id> --apply-overrides
```

The clusters, issues, review markdown, and context cartridge get rebuilt
against the corrected observations — for the cost of one synthesis call (no
re-transcription, no re-analysis).

## Running stages individually

Useful when you want to iterate on the analyze prompt without paying for
transcription twice, or to swap in a different frame-extraction tuning.

```bash
ux-intel new path/to/walkthrough.mp4         # just creates the session
ux-intel ingest      sessions/<id>
ux-intel transcribe  sessions/<id>
ux-intel frames      sessions/<id> --sample-fps 1 --distance-threshold 8
ux-intel align       sessions/<id>
ux-intel analyze     sessions/<id> --effort high
ux-intel synthesize  sessions/<id> --effort high
ux-intel status      sessions/<id>
```

Each stage records its status in `session.json`. Re-running a stage overwrites
its artifact but leaves earlier stages untouched. A stage refuses to run if
its dependencies haven't completed.

## What each stage does

**ingest** — probes the video, extracts mono 16kHz audio. Writes
`video_metadata.json` and `raw/audio.wav`.

**transcribe** — sends audio to OpenAI Whisper with word-level timestamps.
Writes `transcript.json` and `transcript.txt`.

**frames** — samples the video at a low fixed rate, perceptual-hashes each
frame, keeps frames whose hash is far enough from the last kept frame (scene
change) or whose timestamp exceeds the interval floor (so static screens
still get periodic samples). Writes `frames.json` and `frames/frame-NNNN.jpg`.

**align** — groups transcript segments into "moments" using silence gaps,
topic-shift heuristics, and a max-duration ceiling. Each moment gets the
frame nearest to its midpoint. Writes `moments.json`.

**analyze** — one Claude call per moment. Sends the transcript text and the
primary frame to `claude-opus-4-7` with adaptive thinking and a JSON schema.
The system prompt is held byte-stable across all moments so prompt caching
amortizes the rubric. Writes `observations.json`.

**synthesize** — one Claude call ingests all observations and emits clusters,
draft issues, the review markdown, and the context cartridge. Streaming on
because outputs can be long. Writes `clusters.json`, `issues.json`,
`review.md`, `context.md`. Pass `--apply-overrides` to merge any reviewer
corrections from `overrides.json` before synthesizing.

**review** — generates `outputs/review.html`, a self-contained interactive
review surface. Auto-runs as part of `ux-intel run`; can also be invoked
standalone (`ux-intel review sessions/<id>`) to regenerate after edits.

## Customizing

- **Different transcription provider**: implement the `Transcriber` protocol
  in `transcribe.py` and pass an instance to `transcribe_stage.run()`.
- **Frame extraction tuning**: `--sample-fps`, `--distance-threshold`,
  `--interval-floor` on the `frames` subcommand.
- **Moment grouping**: tweak `DEFAULT_MAX_MOMENT_S`, `RESTART_PHRASES`, and
  the silence gap in `align.py`.
- **Prompts**: `prompts.py` — both system prompts are isolated there.

## Evidence preservation

Every observation carries `moment_id`, `frame_ref`, `quote`, and timestamps.
Every cluster cites its observation IDs. Every issue cites its evidence.
Nothing in the final outputs is disconnected from the raw transcript and the
specific frame that supports it.

## Cost expectations

A 5-minute walkthrough typically produces 15–30 moments. With prompt caching
the per-moment Claude call is dominated by the image (~1500 tokens) and the
fresh transcript snippet. Rough order-of-magnitude:

| Stage        | Cost     | Notes                                       |
|--------------|----------|---------------------------------------------|
| transcribe   | ~$0.03   | OpenAI Whisper at $0.006/min                |
| analyze      | ~$0.30   | 20 moments × ~$0.015 (Opus 4.7, cached)     |
| synthesize   | ~$0.30   | one call, larger output                     |

These will vary with effort level, narration density, and resolution.

## Limitations (MVP)

- Single narrator assumed. No diarization.
- English-tuned rubric. Whisper supports more languages but the prompts are
  English.
- Heuristic frame extraction — works well on screen-recording footage with
  natural transitions; less reliable on scrolling-heavy content.
- No GitHub/Linear integration. Issues are drafts in `issues.json`.
- The review experience lives in a static HTML page — corrections roundtrip
  through a download/re-run rather than a persistent server.

The architecture leaves clean room for each of these to grow — see the
"Future expansion" section of [`DESIGN.md`](DESIGN.md).

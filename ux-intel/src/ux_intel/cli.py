"""Command-line entry point.

A user-facing CLI that wraps the pipeline stages. Two ways to drive it:

    ux-intel run path/to/video.mp4         # run the whole pipeline
    ux-intel new path/to/video.mp4         # create the session, run nothing
    ux-intel ingest <session-dir>
    ux-intel transcribe <session-dir>
    ux-intel frames <session-dir>
    ux-intel align <session-dir>
    ux-intel analyze <session-dir>
    ux-intel synthesize <session-dir>
    ux-intel status <session-dir>

Per-stage commands exist so you can iterate (re-run analyze with a tweaked
prompt without paying for transcription twice).
"""

from __future__ import annotations

import logging
from pathlib import Path

import click

from . import align as align_stage
from . import analyze as analyze_stage
from . import frames as frames_stage
from . import ingest as ingest_stage
from . import pack as pack_mod
from . import review as review_mod
from . import synthesize as synthesize_stage
from . import transcribe as transcribe_stage
from . import watch as watch_mod
from .session import ALL_STAGES, Session, STAGE_DEPENDENCIES


@click.group()
def cli() -> None:
    """UX intelligence pipeline."""


@cli.command()
@click.argument("video", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--sessions-root", type=click.Path(path_type=Path), default=Path("sessions"))
def new(video: Path, sessions_root: Path) -> None:
    """Create a new session directory for VIDEO without running any stages."""
    session = Session.create(sessions_root, video)
    click.echo(session.root)


@cli.command()
@click.argument("video", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--sessions-root", type=click.Path(path_type=Path), default=Path("sessions"))
@click.option("--effort", default="high", type=click.Choice(["low", "medium", "high", "max", "xhigh"]))
@click.option("--local", "local_transcribe", is_flag=True, help="Use on-device faster-whisper instead of the OpenAI API.")
@click.option("--whisper-model", default=transcribe_stage.DEFAULT_LOCAL_MODEL,
              help="faster-whisper model size: tiny | base | small | medium | large-v3 | large-v3-turbo.")
@click.option("--whisper-device", default=None,
              help="faster-whisper device: cpu | cuda | auto. Defaults to cpu on Apple Silicon, auto elsewhere.")
@click.option("--whisper-compute-type", default=None,
              help="faster-whisper compute_type: int8 | float16 | float32 | default. Defaults to int8 on Apple Silicon.")
@click.option("--whisper-cache", default=None, type=click.Path(path_type=Path),
              help="Override the faster-whisper download cache directory. Otherwise HF_HOME / HF_HUB_CACHE env vars apply.")
def run(
    video: Path, sessions_root: Path, effort: str,
    local_transcribe: bool, whisper_model: str,
    whisper_device: str | None, whisper_compute_type: str | None, whisper_cache: Path | None,
) -> None:
    """Create a session for VIDEO and run the full pipeline end-to-end."""
    session = Session.create(sessions_root, video)
    click.echo(f"session: {session.root}")
    _run_full(
        session,
        effort=effort,
        local_transcribe=local_transcribe,
        whisper_model=whisper_model,
        whisper_device=whisper_device,
        whisper_compute_type=whisper_compute_type,
        whisper_cache=str(whisper_cache) if whisper_cache else None,
    )


@cli.command()
@click.argument("session_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
def ingest(session_dir: Path) -> None:
    session = Session.load(session_dir)
    metadata = ingest_stage.run(session)
    click.echo(f"ingest done: {metadata.duration_s:.1f}s @ {metadata.width}x{metadata.height}")


@cli.command()
@click.argument("session_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--local", "local_transcribe", is_flag=True, help="Use on-device faster-whisper instead of the OpenAI API.")
@click.option("--whisper-model", default=transcribe_stage.DEFAULT_LOCAL_MODEL,
              help="faster-whisper model size: tiny | base | small | medium | large-v3 | large-v3-turbo.")
@click.option("--whisper-device", default=None,
              help="faster-whisper device: cpu | cuda | auto. Defaults to cpu on Apple Silicon, auto elsewhere.")
@click.option("--whisper-compute-type", default=None,
              help="faster-whisper compute_type: int8 | float16 | float32 | default. Defaults to int8 on Apple Silicon.")
@click.option("--whisper-cache", default=None, type=click.Path(path_type=Path),
              help="Override the faster-whisper download cache directory. Otherwise HF_HOME / HF_HUB_CACHE env vars apply.")
def transcribe(
    session_dir: Path, local_transcribe: bool, whisper_model: str,
    whisper_device: str | None, whisper_compute_type: str | None, whisper_cache: Path | None,
) -> None:
    session = Session.load(session_dir)
    transcript = transcribe_stage.run(
        session,
        local=local_transcribe,
        local_model=whisper_model,
        device=whisper_device,
        compute_type=whisper_compute_type,
        download_root=str(whisper_cache) if whisper_cache else None,
    )
    click.echo(f"transcribe done: {len(transcript.segments)} segments")


@cli.command()
@click.argument("session_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--sample-fps", default=frames_stage.DEFAULT_SAMPLE_FPS, type=float)
@click.option("--distance-threshold", default=frames_stage.DEFAULT_HASH_DISTANCE_THRESHOLD, type=int)
@click.option("--interval-floor", default=frames_stage.DEFAULT_INTERVAL_FLOOR_S, type=float)
def frames(
    session_dir: Path,
    sample_fps: float,
    distance_threshold: int,
    interval_floor: float,
) -> None:
    session = Session.load(session_dir)
    frame_set = frames_stage.run(
        session,
        sample_fps=sample_fps,
        distance_threshold=distance_threshold,
        interval_floor_s=interval_floor,
    )
    click.echo(f"frames done: {len(frame_set.frames)} keyframes")


@cli.command()
@click.argument("session_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--no-preview", is_flag=True, help="Skip auto-generating the preview review.html.")
def align(session_dir: Path, no_preview: bool) -> None:
    session = Session.load(session_dir)
    moment_set = align_stage.run(session)
    click.echo(f"align done: {len(moment_set.moments)} moments")
    if not no_preview:
        path = review_mod.generate(session)
        click.echo(f"preview ready: {path}")
        click.echo("  open in a browser to see transcript + screenshots (no AI yet)")


@cli.command()
@click.argument("session_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--effort", default="high", type=click.Choice(["low", "medium", "high", "max", "xhigh"]))
def analyze(session_dir: Path, effort: str) -> None:
    session = Session.load(session_dir)
    obs_set = analyze_stage.run(session, effort=effort)
    click.echo(f"analyze done: {len(obs_set.observations)} observations")


@cli.command()
@click.argument("session_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--effort", default="high", type=click.Choice(["low", "medium", "high", "max", "xhigh"]))
@click.option(
    "--apply-overrides",
    is_flag=True,
    help="If outputs/overrides.json exists, apply reviewer corrections before synthesizing.",
)
@click.option(
    "--from-pack",
    is_flag=True,
    help="Skip the API call; instead, ingest outputs/synthesis.json produced by a Claude chat/CLI session.",
)
@click.option(
    "--bundle-path",
    default=None,
    type=click.Path(path_type=Path),
    help="Custom path to the synthesis bundle (when used with --from-pack). Defaults to outputs/synthesis.json.",
)
def synthesize(
    session_dir: Path, effort: str, apply_overrides: bool, from_pack: bool, bundle_path: Path | None,
) -> None:
    session = Session.load(session_dir)
    if from_pack:
        output = synthesize_stage.run_from_pack(session, bundle_path=bundle_path)
        click.echo(f"synthesize done (from pack): {len(output.clusters)} clusters, {len(output.issues)} issues")
    else:
        output = synthesize_stage.run(session, effort=effort, apply_overrides=apply_overrides)
        click.echo(f"synthesize done: {len(output.clusters)} clusters, {len(output.issues)} issues")
    click.echo(f"  review:    {session.review_path}")
    click.echo(f"  cartridge: {session.cartridge_path}")


@cli.command()
@click.argument("session_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option(
    "--stage",
    default="both",
    type=click.Choice(["analyze", "synthesize", "both"]),
    help="Which stage to pack. `both` requires observations.json to exist for the synthesize half.",
)
def pack(session_dir: Path, stage: str) -> None:
    """Export a prompt pack the user can hand to Claude Code, Claude.ai chat, or `claude` CLI.

    The pack is a self-contained directory under `outputs/packs/<stage>/`.
    Read its README.md to see what to do with it. The receiving Claude
    instance writes observations.json (for analyze) or synthesis.json (for
    synthesize), and the pipeline picks up from there.

    Use this when you don't want to spend on the Anthropic API and would rather
    drive the LLM work through a chat or local CLI session.
    """
    session = Session.load(session_dir)
    if stage in ("analyze", "both"):
        path = pack_mod.pack_analyze(session)
        click.echo(f"analyze pack: {path}")
        click.echo(f"  -> hand to a Claude session; it writes {session.observations_path}")
    if stage in ("synthesize", "both"):
        if not session.observations_path.exists():
            if stage == "both":
                click.echo("(skipping synthesize pack — no observations.json yet)")
                return
            raise click.ClickException(
                "No observations.json yet. Run the analyze pack first, or run `ux-intel analyze` with an API key."
            )
        path = pack_mod.pack_synthesize(session)
        click.echo(f"synthesize pack: {path}")
        click.echo(f"  -> hand to a Claude session; it writes {session.root}/outputs/synthesis.json")
        click.echo(f"  -> then run `ux-intel synthesize {session.root} --from-pack`")


@cli.command()
@click.argument("session_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
def review(session_dir: Path) -> None:
    """Generate (or regenerate) the self-contained review.html for SESSION_DIR.

    Works at any stage of the pipeline:
      - after `align`: shows transcript + screenshots ("preview" mode, no AI required)
      - after `synthesize`: adds observation cards, clusters, issues, edit controls
    """
    session = Session.load(session_dir)
    path = review_mod.generate(session)
    click.echo(f"review html: {path}")


@cli.command()
@click.argument("watch_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--sessions-root", type=click.Path(path_type=Path), default=Path("sessions"))
@click.option("--interval", default=watch_mod.DEFAULT_INTERVAL_S, type=float, help="Poll interval in seconds.")
@click.option("--effort", default="high", type=click.Choice(["low", "medium", "high", "max", "xhigh"]))
@click.option(
    "--process-existing",
    is_flag=True,
    help="By default, files already in WATCH_DIR are ignored on startup. Use this flag to process them too.",
)
def watch(watch_dir: Path, sessions_root: Path, interval: float, effort: str, process_existing: bool) -> None:
    """Watch WATCH_DIR for new screen recordings and process them automatically.

    Intended for syncing capture flows: drop your iPhone screen recording into
    a synced folder (Dropbox, iCloud, Google Drive) that points at WATCH_DIR
    and the pipeline runs end-to-end including review.html generation.
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    watcher = watch_mod.Watcher(
        watch_dir=watch_dir,
        sessions_root=sessions_root,
        interval_s=interval,
        effort=effort,
        process_existing=process_existing,
    )
    watcher.run()


@cli.command()
@click.argument("session_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
def status(session_dir: Path) -> None:
    """Print per-stage status for the session."""
    session = Session.load(session_dir)
    state = session.state()
    click.echo(f"session: {state.session_id}")
    click.echo(f"source:  {state.source_video}")
    click.echo(f"created: {state.created_at.isoformat()}")
    click.echo("")
    click.echo("stages:")
    for stage in ALL_STAGES:
        rec = state.stages.get(stage)
        if rec is None:
            click.echo(f"  {stage:14s}  unknown")
            continue
        marker = {"completed": "OK", "running": "..", "failed": "!!", "pending": "  "}.get(rec.status.value, "??")
        suffix = f"  ({rec.notes})" if rec.notes else ""
        if rec.error:
            suffix += f"  ERROR: {rec.error}"
        deps = STAGE_DEPENDENCIES[stage]
        dep_note = f"  deps={','.join(deps)}" if deps else ""
        click.echo(f"  {marker} {stage:14s}  {rec.status.value}{suffix}{dep_note}")


def _run_full(
    session: Session,
    effort: str,
    local_transcribe: bool = False,
    whisper_model: str = transcribe_stage.DEFAULT_LOCAL_MODEL,
    whisper_device: str | None = None,
    whisper_compute_type: str | None = None,
    whisper_cache: str | None = None,
) -> None:
    click.echo("-> ingest")
    ingest_stage.run(session)
    click.echo("-> transcribe")
    transcribe_stage.run(
        session,
        local=local_transcribe,
        local_model=whisper_model,
        device=whisper_device,
        compute_type=whisper_compute_type,
        download_root=whisper_cache,
    )
    click.echo("-> frames")
    frames_stage.run(session)
    click.echo("-> align")
    align_stage.run(session)
    click.echo("-> analyze")
    analyze_stage.run(session, effort=effort)
    click.echo("-> synthesize")
    synthesize_stage.run(session, effort=effort)
    click.echo("-> review")
    review_mod.generate(session)
    click.echo("")
    click.echo(f"done.")
    click.echo(f"  review.md:   {session.review_path}")
    click.echo(f"  review.html: {session.review_html_path}")
    click.echo(f"  cartridge:   {session.cartridge_path}")


if __name__ == "__main__":
    cli()

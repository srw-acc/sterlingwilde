"""Stage 1: ingest.

Probe video metadata, extract mono 16kHz audio for downstream transcription.
"""

from __future__ import annotations

from .ffmpeg_util import extract_audio, ffprobe_json
from .schemas import VideoMetadata
from .session import STAGE_INGEST, Session, write_json


def run(session: Session) -> VideoMetadata:
    session.mark_running(STAGE_INGEST)
    try:
        metadata = _probe(session.video_path())
        write_json(session.metadata_path, metadata)
        if metadata.has_audio:
            extract_audio(session.video_path(), session.audio_path)
        else:
            raise RuntimeError(
                "Video has no audio track. This pipeline assumes narrated walkthroughs."
            )
        session.mark_completed(
            STAGE_INGEST,
            notes=f"duration={metadata.duration_s:.1f}s, {metadata.width}x{metadata.height}@{metadata.fps:.1f}fps",
        )
        return metadata
    except Exception as exc:
        session.mark_failed(STAGE_INGEST, str(exc))
        raise


def _probe(video) -> VideoMetadata:
    data = ffprobe_json(video)
    streams = data.get("streams", [])
    video_stream = next((s for s in streams if s["codec_type"] == "video"), None)
    audio_stream = next((s for s in streams if s["codec_type"] == "audio"), None)
    if video_stream is None:
        raise RuntimeError("No video stream found.")

    fmt = data["format"]
    duration_s = float(fmt.get("duration") or video_stream.get("duration") or 0.0)

    return VideoMetadata(
        duration_s=duration_s,
        width=int(video_stream["width"]),
        height=int(video_stream["height"]),
        fps=_parse_fps(video_stream.get("r_frame_rate", "0/1")),
        has_audio=audio_stream is not None,
        container=fmt.get("format_name", "unknown"),
        codec_video=video_stream.get("codec_name", "unknown"),
        codec_audio=audio_stream.get("codec_name") if audio_stream else None,
    )


def _parse_fps(rate: str) -> float:
    if "/" not in rate:
        return float(rate)
    num, den = rate.split("/", 1)
    den_f = float(den)
    return float(num) / den_f if den_f else 0.0

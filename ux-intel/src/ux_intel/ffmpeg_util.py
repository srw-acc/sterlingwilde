"""Thin shell wrappers around ffmpeg and ffprobe.

We invoke the CLI binaries directly rather than depend on a Python binding —
keeps the dependency surface tight and the failure modes obvious.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


class FFmpegNotInstalled(RuntimeError):
    pass


def ensure_ffmpeg() -> None:
    for binary in ("ffmpeg", "ffprobe"):
        if shutil.which(binary) is None:
            raise FFmpegNotInstalled(
                f"`{binary}` not found on PATH. Install ffmpeg (e.g. `brew install ffmpeg`)."
            )


def ffprobe_json(video: Path) -> dict:
    ensure_ffmpeg()
    result = subprocess.run(
        [
            "ffprobe",
            "-v", "error",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            str(video),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def extract_audio(video: Path, dest: Path, sample_rate: int = 16000) -> None:
    """Mono 16k PCM WAV — the format Whisper handles best with the smallest payload."""
    ensure_ffmpeg()
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i", str(video),
            "-vn",
            "-ac", "1",
            "-ar", str(sample_rate),
            "-f", "wav",
            str(dest),
        ],
        check=True,
        capture_output=True,
    )

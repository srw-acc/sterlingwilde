"""Stage 3: extract keyframes.

Approach:
  1. Sample the video at a low fixed rate (default 1 fps).
  2. Walk forward, perceptual-hashing each frame; keep frames whose hash is
     "far enough" from the last kept frame (scene change) OR whose timestamp
     exceeds the interval floor (so static screens still get periodic samples).
  3. Discard the rejected raw frames; renumber and finalize the keepers.

This is intentionally heuristic. Narrated walkthroughs have soft scene
boundaries (modals, navigations) that perceptual hashing picks up cleanly, and
the analyze stage tolerates suboptimal frame selection because Claude reads
screens directly.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import imagehash
from PIL import Image

from .ffmpeg_util import ensure_ffmpeg
from .schemas import FrameRecord, FrameSet
from .session import STAGE_FRAMES, Session, write_json

DEFAULT_SAMPLE_FPS = 1.0
DEFAULT_HASH_DISTANCE_THRESHOLD = 8  # phash bits; 0=identical, 64=max distinct
DEFAULT_INTERVAL_FLOOR_S = 10.0


def run(
    session: Session,
    sample_fps: float = DEFAULT_SAMPLE_FPS,
    distance_threshold: int = DEFAULT_HASH_DISTANCE_THRESHOLD,
    interval_floor_s: float = DEFAULT_INTERVAL_FLOOR_S,
) -> FrameSet:
    session.require_dependencies(STAGE_FRAMES)
    session.mark_running(STAGE_FRAMES)
    try:
        session.frames_dir.mkdir(parents=True, exist_ok=True)
        for old in session.frames_dir.glob("frame-*.jpg"):
            old.unlink()

        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            _sample_frames(session.video_path(), tmp_dir, sample_fps)
            sampled = sorted(tmp_dir.glob("frame-*.jpg"))
            kept = _select_keyframes(
                sampled,
                sample_fps=sample_fps,
                distance_threshold=distance_threshold,
                interval_floor_s=interval_floor_s,
            )
            records = _finalize(kept, session.frames_dir)

        frame_set = FrameSet(
            fps_sampled=sample_fps,
            scene_threshold=float(distance_threshold),
            interval_floor_s=interval_floor_s,
            frames=records,
        )
        write_json(session.frames_json_path, frame_set)
        session.mark_completed(STAGE_FRAMES, notes=f"{len(records)} keyframes")
        return frame_set
    except Exception as exc:
        session.mark_failed(STAGE_FRAMES, str(exc))
        raise


def _sample_frames(video: Path, dest_dir: Path, sample_fps: float) -> None:
    ensure_ffmpeg()
    dest_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i", str(video),
            "-vf", f"fps={sample_fps}",
            "-qscale:v", "3",
            str(dest_dir / "frame-%06d.jpg"),
        ],
        check=True,
        capture_output=True,
    )


def _select_keyframes(
    sampled_paths: list[Path],
    sample_fps: float,
    distance_threshold: int,
    interval_floor_s: float,
) -> list[tuple[float, Path, str, str, float | None]]:
    """Returns tuples of (timestamp_s, source_path, phash, reason, scene_score)."""
    kept: list[tuple[float, Path, str, str, float | None]] = []
    last_hash = None
    last_kept_t = -interval_floor_s  # ensure the first frame is always kept
    seconds_per_frame = 1.0 / sample_fps

    for i, path in enumerate(sampled_paths):
        timestamp_s = i * seconds_per_frame
        with Image.open(path) as img:
            phash = imagehash.phash(img)
        phash_str = str(phash)

        distance = None
        reason: str = "interval_floor"
        if last_hash is None:
            kept.append((timestamp_s, path, phash_str, "interval_floor", None))
            last_hash = phash
            last_kept_t = timestamp_s
            continue

        distance = last_hash - phash
        time_since_last = timestamp_s - last_kept_t

        if distance >= distance_threshold:
            reason = "scene_change"
            kept.append((timestamp_s, path, phash_str, reason, float(distance)))
            last_hash = phash
            last_kept_t = timestamp_s
        elif time_since_last >= interval_floor_s:
            kept.append((timestamp_s, path, phash_str, "interval_floor", float(distance)))
            last_hash = phash
            last_kept_t = timestamp_s

    return kept


def _finalize(
    kept: list[tuple[float, Path, str, str, float | None]],
    dest_dir: Path,
) -> list[FrameRecord]:
    records: list[FrameRecord] = []
    for i, (ts, src, phash, reason, score) in enumerate(kept):
        dest = dest_dir / f"frame-{i:04d}.jpg"
        dest.write_bytes(src.read_bytes())
        # Path stored relative to session root for portability.
        rel_path = str(Path("intermediates") / "frames" / dest.name)
        records.append(
            FrameRecord(
                index=i,
                timestamp_s=ts,
                path=rel_path,
                phash=phash,
                scene_score=score,
                reason=reason,  # type: ignore[arg-type]
            )
        )
    return records

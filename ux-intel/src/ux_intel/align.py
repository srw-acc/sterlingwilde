"""Stage 4: align transcript into "moments" and attach frames.

A moment is the unit of analysis — roughly one coherent thought from the
narrator. We build moments by walking transcript segments and merging adjacent
ones unless we hit a boundary signal:

  - silence gap above a threshold (Whisper's segment boundaries already encode
    pauses, so we just check the time gap between consecutive segments),
  - a topic-shift restart phrase ("okay so", "now I'm going to", etc.),
  - hitting a max-duration ceiling so a single moment doesn't swallow the
    whole video.

Each moment is then assigned the keyframe nearest to its temporal midpoint as
its `primary_frame`, plus any other frames that fall within its time range as
`nearby_frames`.
"""

from __future__ import annotations

import re

from .schemas import FrameRecord, FrameSet, Moment, MomentSet, Transcript, TranscriptSegment
from .session import STAGE_ALIGN, Session, write_json

DEFAULT_MAX_MOMENT_S = 25.0
DEFAULT_MIN_MOMENT_S = 3.0
DEFAULT_SILENCE_GAP_S = 1.0

RESTART_PHRASES = re.compile(
    r"^\s*("
    r"okay so|ok so|alright|all right|now|next|so now|"
    r"let me|let's|i'm going to|i'll|here we|moving on|"
    r"actually|wait|hmm|um|uh"
    r")\b",
    re.IGNORECASE,
)


def run(
    session: Session,
    max_moment_s: float = DEFAULT_MAX_MOMENT_S,
    min_moment_s: float = DEFAULT_MIN_MOMENT_S,
    silence_gap_s: float = DEFAULT_SILENCE_GAP_S,
) -> MomentSet:
    session.require_dependencies(STAGE_ALIGN)
    session.mark_running(STAGE_ALIGN)
    try:
        transcript = Transcript.model_validate_json(session.transcript_path.read_text())
        frame_set = FrameSet.model_validate_json(session.frames_json_path.read_text())

        groups = _group_segments(
            transcript.segments,
            max_moment_s=max_moment_s,
            min_moment_s=min_moment_s,
            silence_gap_s=silence_gap_s,
        )

        moments = [
            _build_moment(idx, group, frame_set.frames)
            for idx, group in enumerate(groups)
        ]
        moment_set = MomentSet(moments=moments)
        write_json(session.moments_path, moment_set)
        session.mark_completed(
            STAGE_ALIGN,
            notes=f"{len(moments)} moments from {len(transcript.segments)} segments",
        )
        return moment_set
    except Exception as exc:
        session.mark_failed(STAGE_ALIGN, str(exc))
        raise


def _group_segments(
    segments: list[TranscriptSegment],
    max_moment_s: float,
    min_moment_s: float,
    silence_gap_s: float,
) -> list[list[TranscriptSegment]]:
    if not segments:
        return []

    groups: list[list[TranscriptSegment]] = [[segments[0]]]
    for prev, cur in zip(segments, segments[1:]):
        current = groups[-1]
        current_duration = current[-1].end - current[0].start
        gap = cur.start - prev.end

        should_break = False
        if current_duration >= max_moment_s:
            should_break = True
        elif current_duration >= min_moment_s and gap >= silence_gap_s:
            should_break = True
        elif current_duration >= min_moment_s and RESTART_PHRASES.match(cur.text):
            should_break = True

        if should_break:
            groups.append([cur])
        else:
            current.append(cur)
    return groups


def _build_moment(
    idx: int,
    group: list[TranscriptSegment],
    frames: list[FrameRecord],
) -> Moment:
    start = group[0].start
    end = group[-1].end
    text = " ".join(seg.text for seg in group).strip()
    midpoint = (start + end) / 2

    primary = _nearest_frame(frames, midpoint)
    nearby = [
        f.path for f in frames
        if f.timestamp_s >= start and f.timestamp_s <= end and f.path != primary
    ]

    return Moment(
        id=f"m{idx:04d}",
        start=start,
        end=end,
        transcript=text,
        segment_ids=[seg.id for seg in group],
        primary_frame=primary,
        nearby_frames=nearby,
    )


def _nearest_frame(frames: list[FrameRecord], t: float) -> str:
    if not frames:
        raise RuntimeError("No frames available to align to. Re-run the frames stage.")
    best = min(frames, key=lambda f: abs(f.timestamp_s - t))
    return best.path

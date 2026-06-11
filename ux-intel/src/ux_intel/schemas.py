"""Pydantic models for every artifact the pipeline emits.

Each stage reads and writes against these. The `schema_version` field on
session state tracks compatibility so a stage re-run on stale intermediates
fails loudly rather than silently producing garbage.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

SCHEMA_VERSION = 1


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------


class StageStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class StageRecord(BaseModel):
    status: StageStatus = StageStatus.PENDING
    started_at: datetime | None = None
    completed_at: datetime | None = None
    schema_version: int = SCHEMA_VERSION
    error: str | None = None
    notes: str | None = None


class SessionState(BaseModel):
    session_id: str
    created_at: datetime
    source_video: str
    schema_version: int = SCHEMA_VERSION
    stages: dict[str, StageRecord] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------


class VideoMetadata(BaseModel):
    duration_s: float
    width: int
    height: int
    fps: float
    has_audio: bool
    container: str
    codec_video: str
    codec_audio: str | None


# ---------------------------------------------------------------------------
# Transcript
# ---------------------------------------------------------------------------


class TranscriptWord(BaseModel):
    word: str
    start: float
    end: float


class TranscriptSegment(BaseModel):
    id: int
    start: float
    end: float
    text: str
    words: list[TranscriptWord] = Field(default_factory=list)


class Transcript(BaseModel):
    language: str
    duration_s: float
    segments: list[TranscriptSegment]
    full_text: str


# ---------------------------------------------------------------------------
# Frames
# ---------------------------------------------------------------------------


class FrameRecord(BaseModel):
    index: int
    timestamp_s: float
    path: str  # relative to session root
    phash: str
    scene_score: float | None = None
    reason: Literal["scene_change", "interval_floor"] = "interval_floor"


class FrameSet(BaseModel):
    fps_sampled: float
    scene_threshold: float
    interval_floor_s: float
    frames: list[FrameRecord]


# ---------------------------------------------------------------------------
# Moments (aligned transcript + frame)
# ---------------------------------------------------------------------------


class Moment(BaseModel):
    id: str
    start: float
    end: float
    transcript: str
    segment_ids: list[int]
    primary_frame: str  # relative path
    nearby_frames: list[str] = Field(default_factory=list)


class MomentSet(BaseModel):
    moments: list[Moment]


# ---------------------------------------------------------------------------
# Observations
# ---------------------------------------------------------------------------


class FeedbackKind(str, Enum):
    BUG = "bug"
    UX_FRICTION = "ux_friction"
    VISUAL_INCONSISTENCY = "visual_inconsistency"
    DATA_QUALITY = "data_quality"
    WORKFLOW = "workflow"
    FEATURE_REQUEST = "feature_request"
    PRAISE = "praise"
    UNCERTAIN = "uncertain"


class Sentiment(str, Enum):
    CONFIDENT = "confident"
    UNCERTAIN = "uncertain"
    FRUSTRATED = "frustrated"
    IMPRESSED = "impressed"
    CONFUSED = "confused"
    EXPLORATORY = "exploratory"
    NEUTRAL = "neutral"


class Observation(BaseModel):
    id: str
    moment_id: str
    quote: str
    t_start: float
    t_end: float
    frame_ref: str
    kind: FeedbackKind
    sentiment: Sentiment
    summary: str
    likely_ui_element: str | None = None
    likely_screen: str | None = None
    interpretation_basis: str
    confidence: float = Field(ge=0.0, le=1.0)
    implementation_hint: str | None = None


class ObservationSet(BaseModel):
    observations: list[Observation]


# ---------------------------------------------------------------------------
# Clusters and outputs
# ---------------------------------------------------------------------------


class Cluster(BaseModel):
    id: str
    theme: str
    summary: str
    kind: FeedbackKind
    observation_ids: list[str]
    severity: Literal["low", "medium", "high"]
    confidence: float = Field(ge=0.0, le=1.0)


class IssueDraft(BaseModel):
    id: str
    title: str
    body_markdown: str
    labels: list[str]
    cluster_id: str
    evidence_observation_ids: list[str]


class SynthesisOutput(BaseModel):
    clusters: list[Cluster]
    issues: list[IssueDraft]
    review_markdown: str
    context_cartridge_markdown: str


# ---------------------------------------------------------------------------
# Reviewer overrides
# ---------------------------------------------------------------------------


class ObservationOverride(BaseModel):
    """A reviewer's adjustment to a single observation.

    Any field left as `None` means "leave the original value alone". `suppressed`
    drops the observation entirely from synthesis. `approved` records explicit
    human verification — useful when a reviewer wants to mark something as
    correct without changing it.
    """

    observation_id: str
    suppressed: bool = False
    approved: bool = False
    kind: FeedbackKind | None = None
    sentiment: Sentiment | None = None
    summary: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    implementation_hint: str | None = None
    reviewer_note: str | None = None


class OverrideSet(BaseModel):
    overrides: list[ObservationOverride] = Field(default_factory=list)
    edited_at: datetime | None = None
    reviewer: str | None = None

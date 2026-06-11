"""Session directory layout, state file management, and stage gating."""

from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .schemas import SCHEMA_VERSION, SessionState, StageRecord, StageStatus

STAGE_INGEST = "ingest"
STAGE_TRANSCRIBE = "transcribe"
STAGE_FRAMES = "frames"
STAGE_ALIGN = "align"
STAGE_ANALYZE = "analyze"
STAGE_SYNTHESIZE = "synthesize"

STAGE_DEPENDENCIES: dict[str, list[str]] = {
    STAGE_INGEST: [],
    STAGE_TRANSCRIBE: [STAGE_INGEST],
    STAGE_FRAMES: [STAGE_INGEST],
    STAGE_ALIGN: [STAGE_TRANSCRIBE, STAGE_FRAMES],
    STAGE_ANALYZE: [STAGE_ALIGN],
    STAGE_SYNTHESIZE: [STAGE_ANALYZE],
}

ALL_STAGES = [
    STAGE_INGEST,
    STAGE_TRANSCRIBE,
    STAGE_FRAMES,
    STAGE_ALIGN,
    STAGE_ANALYZE,
    STAGE_SYNTHESIZE,
]


class StageNotReadyError(RuntimeError):
    """A stage was asked to run before its dependencies completed."""


class Session:
    """A pipeline session rooted at a directory on disk.

    The directory is the source of truth. The Session object is a thin handle
    that reads and writes state to `session.json` and exposes a few helpers for
    stage code.
    """

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.state_path = self.root / "session.json"

    # -- construction --------------------------------------------------------

    @classmethod
    def create(cls, sessions_root: Path, source_video: Path) -> Session:
        sessions_root = sessions_root.resolve()
        sessions_root.mkdir(parents=True, exist_ok=True)
        session_id = _new_session_id()
        root = sessions_root / session_id
        root.mkdir()
        (root / "raw").mkdir()
        (root / "intermediates").mkdir()
        (root / "intermediates" / "frames").mkdir()
        (root / "outputs").mkdir()

        dest_video = root / "raw" / source_video.name
        shutil.copy2(source_video, dest_video)

        state = SessionState(
            session_id=session_id,
            created_at=datetime.now(timezone.utc),
            source_video=str(dest_video.relative_to(root)),
            stages={s: StageRecord() for s in ALL_STAGES},
        )
        session = cls(root)
        session._write_state(state)
        return session

    @classmethod
    def load(cls, root: Path) -> Session:
        session = cls(root)
        if not session.state_path.exists():
            raise FileNotFoundError(f"No session.json at {session.state_path}")
        return session

    # -- state access --------------------------------------------------------

    def state(self) -> SessionState:
        return SessionState.model_validate_json(self.state_path.read_text())

    def _write_state(self, state: SessionState) -> None:
        self.state_path.write_text(state.model_dump_json(indent=2))

    def video_path(self) -> Path:
        return self.root / self.state().source_video

    def path(self, relative: str) -> Path:
        return self.root / relative

    def rel(self, absolute: Path) -> str:
        return str(absolute.resolve().relative_to(self.root))

    # -- stage gating --------------------------------------------------------

    def require_dependencies(self, stage: str) -> None:
        state = self.state()
        for dep in STAGE_DEPENDENCIES[stage]:
            rec = state.stages.get(dep)
            if rec is None or rec.status != StageStatus.COMPLETED:
                raise StageNotReadyError(
                    f"Stage '{stage}' requires '{dep}' to be completed first."
                )
            if rec.schema_version != SCHEMA_VERSION:
                raise StageNotReadyError(
                    f"Stage '{dep}' was run with schema_version={rec.schema_version}, "
                    f"current is {SCHEMA_VERSION}. Re-run '{dep}'."
                )

    def mark_running(self, stage: str) -> None:
        state = self.state()
        state.stages[stage] = StageRecord(
            status=StageStatus.RUNNING,
            started_at=datetime.now(timezone.utc),
            schema_version=SCHEMA_VERSION,
        )
        self._write_state(state)

    def mark_completed(self, stage: str, notes: str | None = None) -> None:
        state = self.state()
        rec = state.stages.get(stage) or StageRecord()
        rec.status = StageStatus.COMPLETED
        rec.completed_at = datetime.now(timezone.utc)
        rec.schema_version = SCHEMA_VERSION
        rec.error = None
        rec.notes = notes
        state.stages[stage] = rec
        self._write_state(state)

    def mark_failed(self, stage: str, error: str) -> None:
        state = self.state()
        rec = state.stages.get(stage) or StageRecord()
        rec.status = StageStatus.FAILED
        rec.completed_at = datetime.now(timezone.utc)
        rec.error = error
        state.stages[stage] = rec
        self._write_state(state)

    # -- artifact paths ------------------------------------------------------

    @property
    def audio_path(self) -> Path:
        return self.root / "raw" / "audio.wav"

    @property
    def transcript_path(self) -> Path:
        return self.root / "intermediates" / "transcript.json"

    @property
    def transcript_text_path(self) -> Path:
        return self.root / "intermediates" / "transcript.txt"

    @property
    def frames_dir(self) -> Path:
        return self.root / "intermediates" / "frames"

    @property
    def frames_json_path(self) -> Path:
        return self.root / "intermediates" / "frames.json"

    @property
    def moments_path(self) -> Path:
        return self.root / "intermediates" / "moments.json"

    @property
    def observations_path(self) -> Path:
        return self.root / "intermediates" / "observations.json"

    @property
    def review_path(self) -> Path:
        return self.root / "outputs" / "review.md"

    @property
    def issues_path(self) -> Path:
        return self.root / "outputs" / "issues.json"

    @property
    def clusters_path(self) -> Path:
        return self.root / "outputs" / "clusters.json"

    @property
    def cartridge_path(self) -> Path:
        return self.root / "outputs" / "context.md"

    @property
    def review_html_path(self) -> Path:
        return self.root / "outputs" / "review.html"

    @property
    def overrides_path(self) -> Path:
        return self.root / "outputs" / "overrides.json"

    @property
    def metadata_path(self) -> Path:
        return self.root / "intermediates" / "video_metadata.json"


def _new_session_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{ts}-{uuid.uuid4().hex[:6]}"


def write_json(path: Path, obj) -> None:
    """Pretty-printed JSON dump for any pydantic-or-dict payload."""
    if hasattr(obj, "model_dump_json"):
        path.write_text(obj.model_dump_json(indent=2))
    else:
        path.write_text(json.dumps(obj, indent=2, default=str))

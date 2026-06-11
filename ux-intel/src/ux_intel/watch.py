"""Folder watcher: auto-process new screen recordings dropped into a directory.

The intended capture flow is "iPhone screen recording → cloud sync folder →
this watcher picks it up." We don't trust filesystem events for that — cloud
syncs often write the file in pieces and inotify fires before the file is
actually complete. So this is a stat-based polling watcher that only processes
a file once its size and mtime have been stable across two polls.

State (which files have been processed) lives in `<sessions-root>/.processed.json`
so reruns of the watcher don't double-process. A processed entry stores enough
to identify the file even if it gets renamed (size + mtime).
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from . import align as align_stage
from . import analyze as analyze_stage
from . import frames as frames_stage
from . import ingest as ingest_stage
from . import review as review_mod
from . import synthesize as synthesize_stage
from . import transcribe as transcribe_stage
from .session import Session

VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".mkv", ".webm"}
DEFAULT_INTERVAL_S = 30.0
STABILITY_POLLS = 2  # require N stable polls before processing

log = logging.getLogger("ux_intel.watch")


class Watcher:
    def __init__(
        self,
        watch_dir: Path,
        sessions_root: Path,
        interval_s: float = DEFAULT_INTERVAL_S,
        effort: str = "high",
        process_existing: bool = False,
    ):
        self.watch_dir = watch_dir.resolve()
        self.sessions_root = sessions_root.resolve()
        self.interval_s = interval_s
        self.effort = effort
        self.process_existing = process_existing
        self.state_path = self.sessions_root / ".processed.json"
        self.sessions_root.mkdir(parents=True, exist_ok=True)
        self._processed = self._load_state()
        self._stability: dict[str, tuple[int, float, int]] = {}
        # path -> (size, mtime, consecutive_stable_polls)

    def run(self) -> None:
        log.info("watching %s -> %s (every %.0fs)", self.watch_dir, self.sessions_root, self.interval_s)
        if not self.process_existing:
            # On first start, mark anything already in the folder as already-seen
            # so we don't re-process a backlog. Caller can pass --process-existing
            # to opt in.
            for video in self._candidate_videos():
                key = self._key(video)
                if key not in self._processed:
                    self._processed[key] = {
                        "filename": video.name,
                        "skipped_existing": True,
                        "seen_at": _now_iso(),
                    }
            self._save_state()

        while True:
            try:
                self._tick()
            except KeyboardInterrupt:
                log.info("stopped by user")
                return
            except Exception:
                log.exception("error during poll; continuing")
            time.sleep(self.interval_s)

    # -- internals -----------------------------------------------------------

    def _tick(self) -> None:
        active_keys: set[str] = set()
        for video in self._candidate_videos():
            key = self._key(video)
            active_keys.add(key)
            if key in self._processed:
                continue
            if not self._is_stable(video):
                continue
            log.info("processing new video: %s", video.name)
            try:
                self._process(video)
            except Exception as exc:
                log.exception("failed to process %s", video.name)
                self._processed[key] = {
                    "filename": video.name,
                    "failed": True,
                    "error": str(exc),
                    "seen_at": _now_iso(),
                }
                self._save_state()

        # Garbage-collect stability counters for files no longer present
        for stale in list(self._stability):
            if stale not in active_keys:
                self._stability.pop(stale, None)

    def _candidate_videos(self) -> list[Path]:
        if not self.watch_dir.exists():
            return []
        return sorted(
            p for p in self.watch_dir.iterdir()
            if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS
        )

    def _is_stable(self, path: Path) -> bool:
        try:
            stat = path.stat()
        except FileNotFoundError:
            return False
        size, mtime = stat.st_size, stat.st_mtime
        key = str(path)
        prev = self._stability.get(key)
        if prev is None or prev[0] != size or prev[1] != mtime:
            self._stability[key] = (size, mtime, 1)
            return False
        new_count = prev[2] + 1
        self._stability[key] = (size, mtime, new_count)
        return new_count >= STABILITY_POLLS

    def _process(self, video: Path) -> None:
        session = Session.create(self.sessions_root, video)
        log.info("  session: %s", session.root.name)
        ingest_stage.run(session)
        log.info("  ingest done")
        transcribe_stage.run(session)
        log.info("  transcribe done")
        frames_stage.run(session)
        log.info("  frames done")
        align_stage.run(session)
        log.info("  align done")
        analyze_stage.run(session, effort=self.effort)
        log.info("  analyze done")
        synthesize_stage.run(session, effort=self.effort)
        log.info("  synthesize done")
        review_mod.generate(session)
        log.info("  review.html ready: %s", session.review_html_path)

        self._processed[self._key(video)] = {
            "filename": video.name,
            "session_id": session.state().session_id,
            "session_path": str(session.root),
            "processed_at": _now_iso(),
        }
        self._save_state()

    def _key(self, path: Path) -> str:
        try:
            stat = path.stat()
            return f"{path.name}:{stat.st_size}:{int(stat.st_mtime)}"
        except FileNotFoundError:
            return path.name

    def _load_state(self) -> dict[str, dict]:
        if not self.state_path.exists():
            return {}
        try:
            return json.loads(self.state_path.read_text())
        except json.JSONDecodeError:
            log.warning("could not parse %s; starting fresh", self.state_path)
            return {}

    def _save_state(self) -> None:
        self.state_path.write_text(json.dumps(self._processed, indent=2))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

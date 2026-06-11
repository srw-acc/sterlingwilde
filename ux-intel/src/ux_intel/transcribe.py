"""Stage 2: transcribe.

Two transcription backends:

  - `OpenAIWhisperTranscriber` — OpenAI Whisper API (`whisper-1`). Cheap and
    accurate, requires an API key.
  - `FasterWhisperTranscriber` — `faster-whisper`, runs entirely on-device
    (CPU or GPU). No API key, no per-minute cost; just downloads the model
    weights on first use.

Both implement the `Transcriber` protocol so the rest of the pipeline doesn't
care which one ran. Adding a third (Deepgram, AssemblyAI, local whisper.cpp)
is a new adapter and a CLI flag.
"""

from __future__ import annotations

import os
import platform
from pathlib import Path
from typing import Protocol

from .schemas import Transcript, TranscriptSegment, TranscriptWord
from .session import STAGE_TRANSCRIBE, Session

DEFAULT_LOCAL_MODEL = "small"


def _apple_silicon() -> bool:
    return platform.system() == "Darwin" and platform.machine() in ("arm64", "aarch64")


class Transcriber(Protocol):
    def transcribe(self, audio_path: Path) -> Transcript: ...


class OpenAIWhisperTranscriber:
    """`whisper-1` via the OpenAI API.

    Word-level timestamps are requested so the aligner can split moments on
    silence gaps with sub-second precision.
    """

    def __init__(self, model: str = "whisper-1", api_key: str | None = None):
        from openai import OpenAI  # imported lazily so the local backend doesn't pay the import cost
        self.model = model
        self.client = OpenAI(api_key=api_key or os.environ.get("OPENAI_API_KEY"))

    def transcribe(self, audio_path: Path) -> Transcript:
        with audio_path.open("rb") as f:
            response = self.client.audio.transcriptions.create(
                file=f,
                model=self.model,
                response_format="verbose_json",
                timestamp_granularities=["segment", "word"],
            )
        return _parse_whisper_response(response)


class FasterWhisperTranscriber:
    """Local transcription via `faster-whisper`.

    First call downloads the model to the HuggingFace cache. Pass
    `download_root` to override the cache location (otherwise faster-whisper
    honors `HF_HOME` / `HF_HUB_CACHE` env vars). On Apple Silicon, default
    `device="cpu"` + `compute_type="int8"` — CTranslate2 doesn't talk to
    Metal directly but int8-CPU is the fast Apple-Silicon-friendly path.
    """

    def __init__(
        self,
        model_size: str = DEFAULT_LOCAL_MODEL,
        device: str | None = None,
        compute_type: str | None = None,
        language: str | None = None,
        download_root: str | None = None,
    ):
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise ImportError(
                "faster-whisper is not installed. "
                "Reinstall with `pip install -e \".[local]\"` (or `pip install faster-whisper`)."
            ) from exc

        # Default to the Apple-Silicon-friendly config when we detect it.
        if device is None:
            device = "cpu" if _apple_silicon() else "auto"
        if compute_type is None:
            compute_type = "int8" if _apple_silicon() else "default"

        kwargs = {"device": device, "compute_type": compute_type}
        if download_root:
            kwargs["download_root"] = download_root
        self.model = WhisperModel(model_size, **kwargs)
        self.model_size = model_size
        self.language = language

    def transcribe(self, audio_path: Path) -> Transcript:
        segments_iter, info = self.model.transcribe(
            str(audio_path),
            word_timestamps=True,
            language=self.language,
        )
        segments: list[TranscriptSegment] = []
        full_parts: list[str] = []
        for i, seg in enumerate(segments_iter):
            words = [
                TranscriptWord(word=w.word, start=float(w.start), end=float(w.end))
                for w in (seg.words or [])
            ]
            text = seg.text.strip()
            segments.append(TranscriptSegment(
                id=i, start=float(seg.start), end=float(seg.end),
                text=text, words=words,
            ))
            full_parts.append(text)
        return Transcript(
            language=info.language,
            duration_s=float(info.duration),
            segments=segments,
            full_text=" ".join(full_parts),
        )


def run(
    session: Session,
    transcriber: Transcriber | None = None,
    *,
    local: bool = False,
    local_model: str = DEFAULT_LOCAL_MODEL,
    device: str | None = None,
    compute_type: str | None = None,
    download_root: str | None = None,
) -> Transcript:
    session.require_dependencies(STAGE_TRANSCRIBE)
    session.mark_running(STAGE_TRANSCRIBE)
    try:
        if transcriber is None:
            transcriber = _default_transcriber(
                local=local,
                local_model=local_model,
                device=device,
                compute_type=compute_type,
                download_root=download_root,
            )
        transcript = transcriber.transcribe(session.audio_path)
        session.transcript_path.write_text(transcript.model_dump_json(indent=2))
        session.transcript_text_path.write_text(transcript.full_text)
        session.mark_completed(
            STAGE_TRANSCRIBE,
            notes=f"{len(transcript.segments)} segments, lang={transcript.language}",
        )
        return transcript
    except Exception as exc:
        session.mark_failed(STAGE_TRANSCRIBE, str(exc))
        raise


def _default_transcriber(
    *,
    local: bool,
    local_model: str,
    device: str | None = None,
    compute_type: str | None = None,
    download_root: str | None = None,
) -> Transcriber:
    if local:
        return FasterWhisperTranscriber(
            model_size=local_model,
            device=device,
            compute_type=compute_type,
            download_root=download_root,
        )
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError(
            "No OPENAI_API_KEY set. Either export one, or re-run with --local "
            "to use the on-device faster-whisper backend "
            "(install with `pip install -e \".[local]\"` first)."
        )
    return OpenAIWhisperTranscriber()


def _parse_whisper_response(response) -> Transcript:
    raw = response.model_dump() if hasattr(response, "model_dump") else dict(response)
    raw_segments = raw.get("segments") or []
    raw_words = raw.get("words") or []

    words_by_segment: dict[int, list[TranscriptWord]] = {}
    if raw_words and raw_segments:
        # Whisper returns a flat word list; attach each word to the segment
        # whose [start, end] contains its midpoint.
        for w in raw_words:
            midpoint = (float(w["start"]) + float(w["end"])) / 2
            for i, seg in enumerate(raw_segments):
                if float(seg["start"]) <= midpoint <= float(seg["end"]):
                    words_by_segment.setdefault(i, []).append(
                        TranscriptWord(word=w["word"], start=float(w["start"]), end=float(w["end"]))
                    )
                    break

    segments = [
        TranscriptSegment(
            id=i,
            start=float(seg["start"]),
            end=float(seg["end"]),
            text=seg["text"].strip(),
            words=words_by_segment.get(i, []),
        )
        for i, seg in enumerate(raw_segments)
    ]

    return Transcript(
        language=raw.get("language", "en"),
        duration_s=float(raw.get("duration", segments[-1].end if segments else 0.0)),
        segments=segments,
        full_text=raw.get("text", " ".join(s.text for s in segments)),
    )

"""Local speech-to-text fallback for videos that ship no subtitles.

Roughly a third of a real Bilibili favourites folder has neither CC nor AI
subtitles, and those items previously indexed on title and description alone —
which is barely enough to retrieve on and useless for deep-linking. This module
closes that gap by pulling the audio track and transcribing it locally with
faster-whisper.

Three properties make this safe to leave switched on:

* **Adapter-agnostic.** It works from the item's URL, so it covers every source
  without either adapter knowing it exists. A third source gets it for free.
* **Local.** Audio never leaves the machine, which keeps the project's promise
  intact even for people who enable no API keys at all.
* **Budgeted.** Transcription is minutes per video, not milliseconds, so it is
  bounded by a per-item duration cap and a per-run wall-clock budget, and
  skipped entirely for items that already have subtitles.

Both dependencies are optional (``pip install -e ".[whisper]"``). Without them
the fallback reports itself as unavailable and ingest proceeds unchanged.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
import time
from pathlib import Path

from .config import WhisperConfig
from .models import SavedItem, Segment

log = logging.getLogger(__name__)


class TranscriptionUnavailable(RuntimeError):
    """Raised when the fallback cannot run at all (missing deps, no audio)."""


def _import_faster_whisper():
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise TranscriptionUnavailable(
            "faster-whisper is not installed — run: pip install -e \".[whisper]\""
        ) from exc
    return WhisperModel


def _import_ytdlp():
    try:
        import yt_dlp  # type: ignore
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise TranscriptionUnavailable(
            "yt-dlp is not installed — run: pip install -e \".[whisper]\""
        ) from exc
    return yt_dlp


class WhisperTranscriber:
    """Downloads an item's audio and transcribes it locally.

    The model is loaded lazily and kept for the life of the object: loading it
    costs seconds and several hundred megabytes, so a sync of forty videos must
    pay that once, not forty times.
    """

    def __init__(self, config: WhisperConfig) -> None:
        self.config = config
        self._model = None
        self._budget_started = 0.0
        self._budget_spent = 0.0

    # ------------------------------------------------------------ capability
    @property
    def available(self) -> bool:
        if not self.config.enabled:
            return False
        try:
            _import_faster_whisper()
            _import_ytdlp()
        except TranscriptionUnavailable:
            return False
        return True

    def setup_hint(self) -> str:
        if not self.config.enabled:
            return "Whisper fallback is disabled (set whisper.enabled = true)."
        try:
            _import_faster_whisper()
            _import_ytdlp()
        except TranscriptionUnavailable as exc:
            return str(exc)
        return ""

    # --------------------------------------------------------------- budget
    def start_run(self) -> None:
        """Reset the per-sync time budget. Called once per ingest run."""
        self._budget_started = time.monotonic()
        self._budget_spent = 0.0

    def _budget_exhausted(self) -> bool:
        if self.config.run_budget_seconds <= 0:
            return False
        return self._budget_spent >= self.config.run_budget_seconds

    # ---------------------------------------------------------------- model
    def _load_model(self):
        if self._model is None:
            WhisperModel = _import_faster_whisper()
            log.info(
                "loading whisper model %s (device=%s compute=%s)",
                self.config.model,
                self.config.device,
                self.config.compute_type,
            )
            self._model = WhisperModel(
                self.config.model,
                device=self.config.device,
                compute_type=self.config.compute_type,
            )
        return self._model

    # ----------------------------------------------------------- transcribe
    def should_transcribe(self, item: SavedItem) -> tuple[bool, str]:
        """Whether this item is worth spending minutes of CPU on."""
        if not self.config.enabled:
            return False, "whisper fallback disabled"
        if self._budget_exhausted():
            return False, "per-run transcription budget exhausted"
        if (
            item.duration
            and self.config.max_duration_seconds
            and item.duration > self.config.max_duration_seconds
        ):
            return False, (
                f"video is {item.duration // 60} min, over the "
                f"{self.config.max_duration_seconds // 60} min cap"
            )
        if not item.url:
            return False, "item has no url to pull audio from"
        return True, ""

    def transcribe(self, item: SavedItem) -> list[Segment]:
        ok, reason = self.should_transcribe(item)
        if not ok:
            raise TranscriptionUnavailable(reason)

        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="chekhovsgun-audio-") as workdir:
            audio_path = self._download_audio(item.url, Path(workdir))
            segments = self._run_model(audio_path)
        self._budget_spent += time.monotonic() - started
        log.info(
            "transcribed %s in %.0fs → %d segments",
            item.id,
            time.monotonic() - started,
            len(segments),
        )
        return segments

    def _download_audio(self, url: str, workdir: Path) -> Path:
        yt_dlp = _import_ytdlp()
        target = workdir / "audio.%(ext)s"
        options = {
            "format": "bestaudio/best",
            "outtmpl": str(target),
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "retries": 2,
            # Whisper resamples to 16 kHz mono anyway, so there is nothing to
            # gain from a high-bitrate download and plenty of time to lose.
            "postprocessors": [
                {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "64"}
            ]
            if shutil.which("ffmpeg")
            else [],
        }
        if self.config.cookies_from_browser:
            options["cookiesfrombrowser"] = (self.config.cookies_from_browser,)

        with yt_dlp.YoutubeDL(options) as downloader:
            downloader.download([url])

        files = sorted(workdir.glob("audio.*"))
        if not files:
            raise TranscriptionUnavailable(f"no audio downloaded for {url}")
        return files[0]

    def _run_model(self, audio_path: Path) -> list[Segment]:
        model = self._load_model()
        language = self.config.language or None
        raw, _info = model.transcribe(
            str(audio_path),
            language=language,
            beam_size=self.config.beam_size,
            vad_filter=True,  # drops long silences, which Whisper otherwise hallucinates over
            condition_on_previous_text=False,
        )
        segments: list[Segment] = []
        for row in raw:
            text = (row.text or "").strip()
            if text:
                segments.append(Segment(text=text, start=float(row.start), end=float(row.end)))
        return segments

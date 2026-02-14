"""FasterWhisper local transcriber (GPU/CPU fallback)."""

from __future__ import annotations

import io
import logging
import struct
import wave

from rpg_scribe.core.event_bus import EventBus
from rpg_scribe.core.events import AudioChunkEvent, TranscriptionEvent
from rpg_scribe.core.models import TranscriberConfig
from rpg_scribe.transcribers.base import BaseTranscriber

logger = logging.getLogger(__name__)


def _pcm_to_wav_bytes(
    pcm_data: bytes,
    sample_rate: int = 48000,
    sample_width: int = 2,
    channels: int = 1,
) -> bytes:
    """Convert raw PCM bytes to a WAV file in memory."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_data)
    return buf.getvalue()


class FasterWhisperTranscriber(BaseTranscriber):
    """Local transcriber using faster-whisper.

    Processes audio on local GPU (CUDA) or CPU.
    Same contract as OpenAITranscriber but runs offline.
    """

    def __init__(self, event_bus: EventBus, config: TranscriberConfig) -> None:
        super().__init__(event_bus, config)
        self._model: object | None = None

    def _get_model(self) -> object:
        """Lazy-load the faster-whisper model."""
        if self._model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError:
                raise RuntimeError(
                    "faster-whisper package is required for FasterWhisperTranscriber. "
                    "Install it with: pip install faster-whisper"
                )

            device = self.config.device
            if device == "auto":
                try:
                    import torch
                    device = "cuda" if torch.cuda.is_available() else "cpu"
                except ImportError:
                    device = "cpu"

            self._model = WhisperModel(
                self.config.local_model_size,
                device=device,
                compute_type=self.config.compute_type,
            )
            logger.info(
                "FasterWhisper model loaded: size=%s, device=%s",
                self.config.local_model_size,
                device,
            )
        return self._model

    async def transcribe(self, event: AudioChunkEvent) -> TranscriptionEvent:
        """Transcribe audio locally using faster-whisper."""
        import asyncio

        model = self._get_model()
        wav_data = _pcm_to_wav_bytes(event.audio_data)
        audio_file = io.BytesIO(wav_data)

        # faster-whisper is synchronous; run in executor to avoid blocking
        loop = asyncio.get_running_loop()
        segments, info = await loop.run_in_executor(
            None,
            lambda: model.transcribe(  # type: ignore[union-attr]
                audio_file,
                language=self.config.language,
                initial_prompt=self.config.prompt_hint or None,
            ),
        )

        # Collect all segments into a single text
        text_parts = []
        for segment in segments:
            text_parts.append(segment.text.strip())
        full_text = " ".join(text_parts)

        avg_logprob = getattr(info, "avg_logprob", None)
        confidence = min(1.0, max(0.0, 1.0 + (avg_logprob or -0.5))) if avg_logprob is not None else 0.8

        return TranscriptionEvent(
            session_id=event.session_id,
            speaker_id=event.speaker_id,
            speaker_name=event.speaker_name,
            text=full_text,
            timestamp=event.timestamp,
            confidence=confidence,
            is_partial=False,
        )

    async def start(self) -> None:
        """Start the transcriber, pre-loading the model."""
        self._get_model()
        await super().start()

    async def stop(self) -> None:
        """Stop the transcriber."""
        self._model = None
        await super().stop()

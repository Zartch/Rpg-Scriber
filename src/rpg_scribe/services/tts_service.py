"""Text-to-Speech orchestration."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_TTS_CHAR_LIMIT = 4096


class TTSService:
    def __init__(self, provider=None, config=None) -> None:
        self._provider = provider
        self._config = config

    @staticmethod
    def split_chunks(text: str, limit: int = _TTS_CHAR_LIMIT) -> list[str]:
        """Split text into chunks respecting sentence boundaries.

        Cuts at the last '.', then last ',', then last space before the limit.
        Recurses until every chunk fits.
        """
        if len(text) <= limit:
            return [text]
        # Try last sentence boundary
        for sep in (".", ",", " "):
            cut = text.rfind(sep, 0, limit)
            if cut != -1:
                head = text[: cut + 1].strip()
                tail = text[cut + 1 :].strip()
                return TTSService.split_chunks(head, limit) + TTSService.split_chunks(tail, limit)
        # Hard cut (should never happen with real prose)
        return [text[:limit]] + TTSService.split_chunks(text[limit:], limit)

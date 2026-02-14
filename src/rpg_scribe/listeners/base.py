"""Abstract base class for all audio listeners."""

from __future__ import annotations

from abc import ABC, abstractmethod

from rpg_scribe.core.event_bus import EventBus
from rpg_scribe.core.models import ListenerConfig


class BaseListener(ABC):
    """Interface that any listener must implement.

    A listener connects to an audio source, captures per-user audio,
    and emits AudioChunkEvent continuously via the event bus.
    """

    def __init__(self, event_bus: EventBus, config: ListenerConfig) -> None:
        self.event_bus = event_bus
        self.config = config

    @abstractmethod
    async def connect(self, session_id: str, **kwargs: object) -> None:
        """Connect to the audio source."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Disconnect cleanly."""
        ...

    @abstractmethod
    def is_connected(self) -> bool:
        """Return True if currently connected."""
        ...

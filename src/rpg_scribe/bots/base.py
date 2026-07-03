"""BaseBot ABC and dynamic discovery for voice-trigger bots."""

from __future__ import annotations

import importlib
import pkgutil
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from rpg_scribe.core.event_bus import EventBus
    from rpg_scribe.core.events import Citation
    from rpg_scribe.core.models import CampaignContext, RagCampaignConfig


@dataclass(frozen=True)
class BotResponse:
    """Retorno estructurado de ``BaseBot.handle``.

    ``spoken`` es lo que se sintetiza por TTS; ``written`` (si no es None) se
    publica como ``BotTextResponseEvent`` para el canal de texto.
    """

    spoken: str
    written: str | None = None
    citations: "list[Citation] | None" = None


@dataclass
class BotServices:
    """Dependencias que el framework inyecta a cada bot vía ``setup()``.

    Construido una sola vez en main.py reusando AppConfig. Los secretos
    (anthropic_api_key) viven solo aquí; el bot nunca lee env.
    """

    rag_db_path: str
    anthropic_api_key: str
    summarizer_model: str
    campaign: "CampaignContext | None"
    event_bus: "EventBus | None"
    rag: "RagCampaignConfig | None"


class BaseBot(ABC):
    """A keyword-activated bot.

    Subclasses live under ``rpg_scribe.bots`` and are discovered at startup
    by :func:`discover_bots`. Every subclass declares its activation
    ``keyword`` as a class attribute; ``TriggerWatcher`` matches that
    keyword against ``TranscriptionEvent.text`` and routes the captured
    command to :meth:`handle`.

    Adding a new bot
    ----------------
    1. Create ``src/rpg_scribe/bots/<name>_bot.py``. Any module dropped in
       this package is auto-imported at startup — no registration step.
    2. Subclass ``BaseBot`` and set at least ``keyword`` (lowercase, must
       be unique). Optional: ``name`` (label), ``voice`` (TTS voice id;
       ``None`` → default), ``close_word`` (immediate-finalize trigger,
       stripped from the command), ``timeout_s`` (silence-to-close,
       default 2.5 s).
    3. Implement ``async def handle(self, command, *, session_id,
       speaker_id, speaker_name) -> str | BotResponse``. Return the text
       to be spoken (a ``str``), or a ``BotResponse`` to also publish a
       written answer; an empty spoken string skips TTS. Raising is fine
       — the watcher logs and falls back to a generic apology.
    3b. For dependency injection (RAG index, API keys, campaign config),
       override ``async def setup(self, services)`` — called once at
       startup before the watcher reads keywords. Default is a no-op.
    4. For external dependencies (LLM client, RAG index, HTTP session),
       initialise them in ``__init__`` lazily — bots are instantiated
       once at startup; avoid blocking work there.
    5. Add ``tests/test_<name>_bot.py``. Instantiate the bot directly and
       call ``handle`` with synthetic kwargs; the watcher is covered
       separately in ``tests/test_trigger_watcher.py``.

    See ``echo_bot.py`` for a minimal reference implementation.
    """

    keyword: ClassVar[str] = ""
    name: ClassVar[str] = ""
    voice: ClassVar[str | None] = None
    close_word: ClassVar[str | None] = None
    timeout_s: ClassVar[float] = 2.5
    # Declared to fix the contract; not yet enforced in v1 — follow-up.
    include_in_feed: ClassVar[bool] = False
    include_in_summarizer: ClassVar[bool] = False

    async def setup(self, services: "BotServices") -> None:
        """Inyección de dependencias. Default: no-op (bots simples la ignoran)."""
        return None

    @abstractmethod
    async def handle(
        self,
        command: str,
        *,
        session_id: str,
        speaker_id: str,
        speaker_name: str,
    ) -> "str | BotResponse":
        """Process ``command`` and return text (str) or a structured BotResponse."""


def _all_subclasses(cls: type) -> set[type]:
    out: set[type] = set()
    stack = [cls]
    while stack:
        parent = stack.pop()
        for sub in parent.__subclasses__():
            if sub not in out:
                out.add(sub)
                stack.append(sub)
    return out


def _instantiate_bots(classes) -> list[BaseBot]:
    """Validate ``classes`` and return one instance per concrete subclass.

    Raises:
        ValueError: if any class declares an empty keyword, or if two
            classes share the same case-insensitive keyword.
    """
    seen: dict[str, BaseBot] = {}
    for cls in classes:
        if getattr(cls, "__abstractmethods__", None):
            continue
        if not cls.keyword:
            raise ValueError(f"{cls.__name__} has empty keyword")
        kw = cls.keyword.lower()
        if kw in seen:
            raise ValueError(
                f"Duplicate keyword '{kw}' on {cls.__name__} "
                f"(also on {type(seen[kw]).__name__})"
            )
        seen[kw] = cls()
    return list(seen.values())


def discover_bots() -> list[BaseBot]:
    """Import every submodule of ``rpg_scribe.bots`` and instantiate each
    concrete :class:`BaseBot` subclass declared inside that package.

    Subclasses declared in other modules (e.g. test files) are deliberately
    ignored so test fixtures don't contaminate the live registry.
    """
    import rpg_scribe.bots as pkg

    for _, modname, _ in pkgutil.iter_modules(pkg.__path__):
        importlib.import_module(f"{pkg.__name__}.{modname}")

    in_pkg = [
        cls
        for cls in _all_subclasses(BaseBot)
        if cls.__module__.startswith(f"{pkg.__name__}.")
    ]
    return _instantiate_bots(in_pkg)

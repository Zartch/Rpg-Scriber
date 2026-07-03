"""Tests for BaseBot and discover_bots."""

from __future__ import annotations

import pytest

from rpg_scribe.bots.base import BotResponse, BotServices
from rpg_scribe.bots.echo_bot import EchoBot


class TestBaseBotContract:
    """BaseBot is an ABC with a required async handle() method."""

    def test_baseBot_cannot_be_instantiated(self) -> None:
        from rpg_scribe.bots.base import BaseBot

        with pytest.raises(TypeError):
            BaseBot()  # type: ignore[abstract]

    def test_subclass_without_handle_cannot_be_instantiated(self) -> None:
        from rpg_scribe.bots.base import BaseBot

        class Incomplete(BaseBot):
            keyword = "foo"

        with pytest.raises(TypeError):
            Incomplete()  # type: ignore[abstract]

    def test_concrete_subclass_is_instantiable(self) -> None:
        from rpg_scribe.bots.base import BaseBot

        class Ok(BaseBot):
            keyword = "ok"

            async def handle(
                self, command, *, session_id, speaker_id, speaker_name
            ):
                return "fine"

        bot = Ok()
        assert bot.keyword == "ok"

    def test_default_attributes(self) -> None:
        """BaseBot exposes the agreed-upon class attributes with sane defaults."""
        from rpg_scribe.bots.base import BaseBot

        assert BaseBot.keyword == ""
        assert BaseBot.name == ""
        assert BaseBot.voice is None
        assert BaseBot.close_word is None
        assert BaseBot.timeout_s == 2.5
        assert BaseBot.include_in_feed is False
        assert BaseBot.include_in_summarizer is False

    @pytest.mark.asyncio
    async def test_handle_signature_uses_keyword_only_context(self) -> None:
        """handle() must accept command positional + 3 keyword-only context fields."""
        from rpg_scribe.bots.base import BaseBot

        class Captures(BaseBot):
            keyword = "x"
            received: dict | None = None

            async def handle(
                self, command, *, session_id, speaker_id, speaker_name
            ):
                self.received = {
                    "command": command,
                    "session_id": session_id,
                    "speaker_id": speaker_id,
                    "speaker_name": speaker_name,
                }
                return "ack"

        bot = Captures()
        result = await bot.handle(
            "hola",
            session_id="s1",
            speaker_id="u1",
            speaker_name="Alice",
        )
        assert result == "ack"
        assert bot.received == {
            "command": "hola",
            "session_id": "s1",
            "speaker_id": "u1",
            "speaker_name": "Alice",
        }


class TestDiscoverBots:
    """discover_bots() walks the rpg_scribe.bots package and instantiates bots."""

    def test_discover_finds_echo_bot(self) -> None:
        """The shipped EchoBot must be discoverable."""
        from rpg_scribe.bots.base import discover_bots

        bots = discover_bots()
        keywords = {b.keyword for b in bots}
        assert "echo" in keywords

    def test_discover_excludes_abstract_classes(self) -> None:
        """discover_bots must not instantiate BaseBot itself or partial subclasses."""
        from rpg_scribe.bots.base import BaseBot, discover_bots

        bots = discover_bots()
        for b in bots:
            assert not isinstance(b, type(BaseBot))  # not the class itself
            assert b.__class__ is not BaseBot

    def test_instantiate_raises_on_empty_keyword(self) -> None:
        """_instantiate_bots rejects a class with empty keyword."""
        from rpg_scribe.bots.base import BaseBot, _instantiate_bots

        class Broken(BaseBot):
            keyword = ""

            async def handle(
                self, command, *, session_id, speaker_id, speaker_name
            ):
                return ""

        with pytest.raises(ValueError, match="empty keyword"):
            _instantiate_bots([Broken])

    def test_instantiate_raises_on_duplicate_keyword(self) -> None:
        """Two classes with the same case-insensitive keyword must fail."""
        from rpg_scribe.bots.base import BaseBot, _instantiate_bots

        class A(BaseBot):
            keyword = "alpha"

            async def handle(self, command, *, session_id, speaker_id, speaker_name):
                return ""

        class B(BaseBot):
            keyword = "ALPHA"

            async def handle(self, command, *, session_id, speaker_id, speaker_name):
                return ""

        with pytest.raises(ValueError, match="[Dd]uplicate"):
            _instantiate_bots([A, B])


class TestEchoBot:
    """EchoBot returns 'Has dicho: <command>'."""

    @pytest.mark.asyncio
    async def test_echo_returns_command(self) -> None:
        from rpg_scribe.bots.echo_bot import EchoBot

        bot = EchoBot()
        result = await bot.handle(
            "hola mundo",
            session_id="s",
            speaker_id="u",
            speaker_name="Alice",
        )
        assert "hola mundo" in result

    def test_echo_attributes(self) -> None:
        from rpg_scribe.bots.echo_bot import EchoBot

        assert EchoBot.keyword == "echo"
        assert EchoBot.close_word is not None
        assert EchoBot.include_in_feed is True


def test_bot_response_defaults():
    r = BotResponse(spoken="hola")
    assert r.spoken == "hola"
    assert r.written is None
    assert r.citations is None


async def test_echo_bot_setup_is_noop():
    """El hook setup() por defecto no hace nada y no rompe bots existentes."""
    services = BotServices(
        rag_db_path="x.db",
        anthropic_api_key="",
        summarizer_model="m",
        campaign=None,
        event_bus=None,
        rag=None,
    )
    assert await EchoBot().setup(services) is None

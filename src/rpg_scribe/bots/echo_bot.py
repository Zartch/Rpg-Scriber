"""EchoBot: trivial verification bot that repeats the command it receives."""

from __future__ import annotations

from rpg_scribe.bots.base import BaseBot


class EchoBot(BaseBot):
    keyword = "echo"
    name = "Echo Bot"
    close_word = "fin"
    include_in_feed = True

    async def handle(
        self,
        command: str,
        *,
        session_id: str,
        speaker_id: str,
        speaker_name: str,
    ) -> str:
        return f"Has dicho: {command}"

"""In-memory state cache for the web layer."""
from __future__ import annotations

import time
from typing import Any


class WebState:
    """Shared mutable state for the web layer.

    Holds the latest snapshots of transcriptions, summaries, component
    statuses and questions so REST endpoints can serve them without
    requiring a database.
    """

    def __init__(self, max_transcriptions: int = 5000) -> None:
        self.transcriptions: list[dict[str, Any]] = []
        self.max_transcriptions = max(1, max_transcriptions)
        self.session_summary: str = ""
        self.session_chronology: str = ""
        self.campaign_summary: str = ""
        self.last_summary_update: float = 0.0
        self.component_status: dict[str, dict[str, Any]] = {}
        self.questions: list[dict[str, Any]] = []
        self.active_session_id: str | None = None
        self.active_campaign: dict[str, Any] | None = None

    def add_transcription(self, data: dict[str, Any]) -> None:
        self.transcriptions.append(data)
        overflow = len(self.transcriptions) - self.max_transcriptions
        if overflow > 0:
            del self.transcriptions[:overflow]

    def update_summary(self, data: dict[str, Any]) -> None:
        self.session_summary = data.get("session_summary", "")
        self.session_chronology = (
            data.get("session_chronology", "") or self.session_chronology
        )
        self.campaign_summary = data.get("campaign_summary", "")
        self.last_summary_update = data.get("last_updated", time.time())

    def update_component_status(self, data: dict[str, Any]) -> None:
        component = data.get("component", "unknown")
        self.component_status[component] = data

    def add_question(self, question_id: str, text: str) -> None:
        self.questions.append(
            {
                "id": question_id,
                "question": text,
                "answer": None,
                "status": "pending",
                "created_at": time.time(),
            }
        )

    def answer_question(self, question_id: str, answer: str) -> bool:
        for q in self.questions:
            if q["id"] == question_id and q["status"] == "pending":
                q["answer"] = answer
                q["status"] = "answered"
                q["answered_at"] = time.time()
                return True
        return False

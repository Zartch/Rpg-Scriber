"""Tests for the structured logging configuration."""

from __future__ import annotations

import logging

from rpg_scribe.logging_config import setup_logging


class TestSetupLogging:
    def test_sets_log_level(self) -> None:
        setup_logging(level="DEBUG")
        assert logging.getLogger().level == logging.DEBUG

    def test_info_level(self) -> None:
        setup_logging(level="INFO")
        assert logging.getLogger().level == logging.INFO

    def test_warning_level(self) -> None:
        setup_logging(level="WARNING")
        assert logging.getLogger().level == logging.WARNING

    def test_handler_configured(self) -> None:
        setup_logging(level="INFO")
        root = logging.getLogger()
        assert len(root.handlers) >= 1

    def test_json_output_mode(self) -> None:
        """JSON mode should not raise."""
        setup_logging(level="INFO", json_output=True)
        root = logging.getLogger()
        assert len(root.handlers) >= 1

    def test_noisy_loggers_suppressed(self) -> None:
        setup_logging(level="DEBUG")
        # Third-party loggers should be at WARNING or above
        for name in ("discord", "httpx", "openai"):
            lvl = logging.getLogger(name).level
            assert lvl >= logging.WARNING

"""Tests for resilience utilities: retry, circuit breaker, reconnection."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from rpg_scribe.core.resilience import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitOpenError,
    CircuitState,
    ReconnectConfig,
    ReconnectionManager,
    RetryConfig,
    retry_async,
)


class TestRetryAsync:
    async def test_success_first_attempt(self) -> None:
        fn = AsyncMock(return_value=42)
        result = await retry_async(fn)
        assert result == 42
        assert fn.call_count == 1

    async def test_retries_on_failure(self) -> None:
        fn = AsyncMock(side_effect=[ValueError("fail"), ValueError("fail"), 99])
        config = RetryConfig(max_attempts=3, base_delay_s=0.01)
        result = await retry_async(fn, config=config)
        assert result == 99
        assert fn.call_count == 3

    async def test_raises_after_max_attempts(self) -> None:
        fn = AsyncMock(side_effect=ValueError("always fails"))
        config = RetryConfig(max_attempts=2, base_delay_s=0.01)
        with pytest.raises(ValueError, match="always fails"):
            await retry_async(fn, config=config)
        assert fn.call_count == 2

    async def test_on_retry_callback(self) -> None:
        fn = AsyncMock(side_effect=[ValueError("err"), 1])
        callback = AsyncMock()
        config = RetryConfig(max_attempts=2, base_delay_s=0.01)
        await retry_async(fn, config=config, on_retry=callback)
        assert callback.call_count == 1
        # Should be called with (attempt_index, exception)
        args = callback.call_args[0]
        assert args[0] == 0
        assert isinstance(args[1], ValueError)

    async def test_passes_args_and_kwargs(self) -> None:
        fn = AsyncMock(return_value="ok")
        await retry_async(fn, "a", "b", config=RetryConfig(), key="val")
        fn.assert_called_once_with("a", "b", key="val")

    async def test_max_delay_cap(self) -> None:
        """Delay should not exceed max_delay_s."""
        fn = AsyncMock(side_effect=[ValueError(), ValueError(), 1])
        config = RetryConfig(
            max_attempts=3,
            base_delay_s=100.0,  # Very high base
            max_delay_s=0.01,  # But capped low
        )
        # This should finish quickly because max_delay caps the sleep
        result = await retry_async(fn, config=config)
        assert result == 1


class TestCircuitBreaker:
    def _make_breaker(self, **kwargs) -> CircuitBreaker:
        config = CircuitBreakerConfig(**kwargs)
        return CircuitBreaker("test", config)

    async def test_closed_on_success(self) -> None:
        cb = self._make_breaker()
        fn = AsyncMock(return_value="ok")
        result = await cb.call(fn)
        assert result == "ok"
        assert cb.state == CircuitState.CLOSED

    async def test_opens_after_threshold(self) -> None:
        cb = self._make_breaker(failure_threshold=3)
        fn = AsyncMock(side_effect=RuntimeError("fail"))

        for _ in range(3):
            with pytest.raises(RuntimeError):
                await cb.call(fn)

        assert cb.state == CircuitState.OPEN

    async def test_open_rejects_calls(self) -> None:
        cb = self._make_breaker(failure_threshold=1)
        fn = AsyncMock(side_effect=RuntimeError("fail"))

        with pytest.raises(RuntimeError):
            await cb.call(fn)

        assert cb.state == CircuitState.OPEN
        with pytest.raises(CircuitOpenError):
            await cb.call(fn)

    async def test_half_open_after_timeout(self) -> None:
        cb = self._make_breaker(failure_threshold=1, recovery_timeout_s=0.01)
        fn = AsyncMock(side_effect=RuntimeError("fail"))

        with pytest.raises(RuntimeError):
            await cb.call(fn)
        assert cb.state == CircuitState.OPEN

        await asyncio.sleep(0.02)
        assert cb.state == CircuitState.HALF_OPEN

    async def test_half_open_success_closes(self) -> None:
        cb = self._make_breaker(failure_threshold=1, recovery_timeout_s=0.01)
        failing_fn = AsyncMock(side_effect=RuntimeError("fail"))
        success_fn = AsyncMock(return_value="recovered")

        with pytest.raises(RuntimeError):
            await cb.call(failing_fn)

        await asyncio.sleep(0.02)
        result = await cb.call(success_fn)
        assert result == "recovered"
        assert cb.state == CircuitState.CLOSED

    async def test_half_open_failure_reopens(self) -> None:
        cb = self._make_breaker(failure_threshold=1, recovery_timeout_s=0.01)
        fn = AsyncMock(side_effect=RuntimeError("still failing"))

        with pytest.raises(RuntimeError):
            await cb.call(fn)

        await asyncio.sleep(0.02)
        with pytest.raises(RuntimeError):
            await cb.call(fn)
        assert cb._state == CircuitState.OPEN

    async def test_reset(self) -> None:
        cb = self._make_breaker(failure_threshold=1)
        fn = AsyncMock(side_effect=RuntimeError("fail"))

        with pytest.raises(RuntimeError):
            await cb.call(fn)
        assert cb.state == CircuitState.OPEN

        cb.reset()
        assert cb.state == CircuitState.CLOSED
        assert cb._failure_count == 0


class TestReconnectionManager:
    async def test_start_connects(self) -> None:
        connect_fn = AsyncMock()
        disconnect_fn = AsyncMock()
        is_connected = MagicMock(return_value=True)

        mgr = ReconnectionManager(
            "test", connect_fn, disconnect_fn, is_connected,
            config=ReconnectConfig(max_attempts=2, base_delay_s=0.01),
        )
        await mgr.start(session_id="s1")
        connect_fn.assert_called_once_with(session_id="s1")

        await mgr.stop()
        disconnect_fn.assert_called_once()

    async def test_reconnects_on_disconnect(self) -> None:
        connect_fn = AsyncMock()
        disconnect_fn = AsyncMock()
        call_count = 0

        def is_connected():
            nonlocal call_count
            call_count += 1
            # First check: not connected, triggers reconnect
            # After reconnect: connected
            return call_count > 1

        mgr = ReconnectionManager(
            "test", connect_fn, disconnect_fn, is_connected,
            config=ReconnectConfig(max_attempts=3, base_delay_s=0.01),
        )
        # Manually start without the monitor so we can control timing
        mgr._running = True
        mgr._connect_args = ()
        mgr._connect_kwargs = {"session_id": "s1"}
        await mgr._attempt_reconnect()

        assert connect_fn.call_count >= 1

    async def test_stop_cancels_monitor(self) -> None:
        connect_fn = AsyncMock()
        disconnect_fn = AsyncMock()
        is_connected = MagicMock(return_value=True)

        mgr = ReconnectionManager(
            "test", connect_fn, disconnect_fn, is_connected,
        )
        await mgr.start()
        assert mgr._monitor_task is not None
        await mgr.stop()
        assert not mgr._running

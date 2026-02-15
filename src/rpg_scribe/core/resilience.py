"""Resilience utilities: reconnection, circuit breaker, and retry logic.

Implements robust error handling as specified in architecture section 5.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


# ── Retry with exponential backoff ─────────────────────────────────


@dataclass
class RetryConfig:
    """Configuration for retry logic."""

    max_attempts: int = 3
    base_delay_s: float = 1.0
    max_delay_s: float = 60.0
    exponential_base: float = 2.0


async def retry_async(
    func: Callable[..., Awaitable[T]],
    *args: Any,
    config: RetryConfig | None = None,
    on_retry: Callable[[int, Exception], Awaitable[None]] | None = None,
    **kwargs: Any,
) -> T:
    """Execute an async function with exponential backoff retry.

    Args:
        func: The async callable to execute.
        config: Retry configuration (defaults to 3 attempts).
        on_retry: Optional callback called before each retry with (attempt, exc).

    Returns:
        The result of the function call.

    Raises:
        The last exception if all retries are exhausted.
    """
    cfg = config or RetryConfig()
    last_exc: Exception | None = None

    for attempt in range(cfg.max_attempts):
        try:
            return await func(*args, **kwargs)
        except Exception as exc:
            last_exc = exc
            if attempt < cfg.max_attempts - 1:
                delay = min(
                    cfg.base_delay_s * (cfg.exponential_base ** attempt),
                    cfg.max_delay_s,
                )
                logger.warning(
                    "Attempt %d/%d failed: %s — retrying in %.1fs",
                    attempt + 1,
                    cfg.max_attempts,
                    exc,
                    delay,
                )
                if on_retry:
                    await on_retry(attempt, exc)
                await asyncio.sleep(delay)

    raise last_exc  # type: ignore[misc]


# ── Circuit Breaker ────────────────────────────────────────────────


class CircuitState(Enum):
    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing — reject calls
    HALF_OPEN = "half_open"  # Testing recovery


@dataclass
class CircuitBreakerConfig:
    """Configuration for the circuit breaker."""

    failure_threshold: int = 5
    recovery_timeout_s: float = 30.0
    half_open_max_calls: int = 1


class CircuitBreaker:
    """Async circuit breaker pattern.

    Tracks consecutive failures and "opens" the circuit to prevent
    cascading failures. After a recovery timeout, it transitions to
    half-open to test if the downstream service has recovered.
    """

    def __init__(
        self, name: str, config: CircuitBreakerConfig | None = None
    ) -> None:
        self.name = name
        self.config = config or CircuitBreakerConfig()
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: float = 0.0
        self._half_open_calls = 0

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN:
            elapsed = time.time() - self._last_failure_time
            if elapsed >= self.config.recovery_timeout_s:
                self._state = CircuitState.HALF_OPEN
                self._half_open_calls = 0
                logger.info("Circuit %s transitioning to HALF_OPEN", self.name)
        return self._state

    async def call(
        self, func: Callable[..., Awaitable[T]], *args: Any, **kwargs: Any
    ) -> T:
        """Execute a function through the circuit breaker."""
        current_state = self.state

        if current_state == CircuitState.OPEN:
            raise CircuitOpenError(
                f"Circuit '{self.name}' is OPEN — call rejected"
            )

        if (
            current_state == CircuitState.HALF_OPEN
            and self._half_open_calls >= self.config.half_open_max_calls
        ):
            raise CircuitOpenError(
                f"Circuit '{self.name}' is HALF_OPEN — max test calls reached"
            )

        try:
            if current_state == CircuitState.HALF_OPEN:
                self._half_open_calls += 1

            result = await func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as exc:
            self._on_failure()
            raise exc

    def _on_success(self) -> None:
        if self._state == CircuitState.HALF_OPEN:
            logger.info("Circuit %s recovered — closing", self.name)
        self._state = CircuitState.CLOSED
        self._failure_count = 0

    def _on_failure(self) -> None:
        self._failure_count += 1
        self._last_failure_time = time.time()
        if self._failure_count >= self.config.failure_threshold:
            self._state = CircuitState.OPEN
            logger.warning(
                "Circuit %s OPEN after %d failures",
                self.name,
                self._failure_count,
            )

    def reset(self) -> None:
        """Manually reset the circuit breaker to closed state."""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._half_open_calls = 0


class CircuitOpenError(Exception):
    """Raised when a call is rejected because the circuit is open."""


# ── Reconnection Manager ──────────────────────────────────────────


@dataclass
class ReconnectConfig:
    """Configuration for automatic reconnection."""

    max_attempts: int = 10
    base_delay_s: float = 1.0
    max_delay_s: float = 120.0
    exponential_base: float = 2.0


class ReconnectionManager:
    """Manages automatic reconnection for components like Discord listeners.

    Wraps a connect/disconnect lifecycle and retries on failure.
    """

    def __init__(
        self,
        name: str,
        connect_fn: Callable[..., Awaitable[None]],
        disconnect_fn: Callable[..., Awaitable[None]],
        is_connected_fn: Callable[[], bool],
        config: ReconnectConfig | None = None,
    ) -> None:
        self.name = name
        self._connect = connect_fn
        self._disconnect = disconnect_fn
        self._is_connected = is_connected_fn
        self.config = config or ReconnectConfig()
        self._monitor_task: asyncio.Task[None] | None = None
        self._running = False
        self._connect_args: tuple[Any, ...] = ()
        self._connect_kwargs: dict[str, Any] = {}

    async def start(self, *args: Any, **kwargs: Any) -> None:
        """Start the connection and begin monitoring."""
        self._connect_args = args
        self._connect_kwargs = kwargs
        self._running = True
        await self._connect(*args, **kwargs)
        self._monitor_task = asyncio.create_task(
            self._monitor_loop(), name=f"reconnect-{self.name}"
        )

    async def stop(self) -> None:
        """Stop monitoring and disconnect."""
        self._running = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            self._monitor_task = None
        try:
            await self._disconnect()
        except Exception:
            pass

    async def _monitor_loop(self) -> None:
        """Periodically check connection and reconnect if needed."""
        while self._running:
            await asyncio.sleep(5.0)
            if not self._running:
                break
            if not self._is_connected():
                logger.warning("%s disconnected — attempting reconnection", self.name)
                await self._attempt_reconnect()

    async def _attempt_reconnect(self) -> None:
        """Try to reconnect with exponential backoff."""
        for attempt in range(self.config.max_attempts):
            if not self._running:
                return
            try:
                await self._connect(
                    *self._connect_args, **self._connect_kwargs
                )
                if self._is_connected():
                    logger.info(
                        "%s reconnected after %d attempt(s)",
                        self.name,
                        attempt + 1,
                    )
                    return
            except Exception as exc:
                delay = min(
                    self.config.base_delay_s
                    * (self.config.exponential_base ** attempt),
                    self.config.max_delay_s,
                )
                logger.warning(
                    "%s reconnect attempt %d/%d failed: %s — waiting %.1fs",
                    self.name,
                    attempt + 1,
                    self.config.max_attempts,
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)

        logger.error(
            "%s failed to reconnect after %d attempts",
            self.name,
            self.config.max_attempts,
        )

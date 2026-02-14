"""Tests for the async event bus."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from rpg_scribe.core.event_bus import EventBus


@dataclass
class FakeEventA:
    value: int


@dataclass
class FakeEventB:
    text: str


@pytest.fixture
def bus() -> EventBus:
    return EventBus()


@pytest.mark.asyncio
async def test_publish_calls_subscriber(bus: EventBus) -> None:
    received: list[FakeEventA] = []

    async def handler(event: FakeEventA) -> None:
        received.append(event)

    bus.subscribe(FakeEventA, handler)
    await bus.publish(FakeEventA(value=42))

    assert len(received) == 1
    assert received[0].value == 42


@pytest.mark.asyncio
async def test_multiple_subscribers(bus: EventBus) -> None:
    results: list[int] = []

    async def h1(event: FakeEventA) -> None:
        results.append(1)

    async def h2(event: FakeEventA) -> None:
        results.append(2)

    bus.subscribe(FakeEventA, h1)
    bus.subscribe(FakeEventA, h2)
    await bus.publish(FakeEventA(value=0))

    assert sorted(results) == [1, 2]


@pytest.mark.asyncio
async def test_subscribe_does_not_duplicate(bus: EventBus) -> None:
    count = 0

    async def handler(event: FakeEventA) -> None:
        nonlocal count
        count += 1

    bus.subscribe(FakeEventA, handler)
    bus.subscribe(FakeEventA, handler)  # duplicate
    await bus.publish(FakeEventA(value=0))

    assert count == 1


@pytest.mark.asyncio
async def test_unsubscribe(bus: EventBus) -> None:
    received: list[FakeEventA] = []

    async def handler(event: FakeEventA) -> None:
        received.append(event)

    bus.subscribe(FakeEventA, handler)
    bus.unsubscribe(FakeEventA, handler)
    await bus.publish(FakeEventA(value=1))

    assert received == []


@pytest.mark.asyncio
async def test_unsubscribe_nonexistent_is_noop(bus: EventBus) -> None:
    async def handler(event: FakeEventA) -> None:
        pass

    # Should not raise
    bus.unsubscribe(FakeEventA, handler)


@pytest.mark.asyncio
async def test_events_only_reach_matching_type(bus: EventBus) -> None:
    a_events: list[FakeEventA] = []
    b_events: list[FakeEventB] = []

    async def ha(event: FakeEventA) -> None:
        a_events.append(event)

    async def hb(event: FakeEventB) -> None:
        b_events.append(event)

    bus.subscribe(FakeEventA, ha)
    bus.subscribe(FakeEventB, hb)

    await bus.publish(FakeEventA(value=10))
    await bus.publish(FakeEventB(text="hello"))

    assert len(a_events) == 1
    assert len(b_events) == 1
    assert a_events[0].value == 10
    assert b_events[0].text == "hello"


@pytest.mark.asyncio
async def test_publish_no_subscribers_is_noop(bus: EventBus) -> None:
    # Should not raise
    await bus.publish(FakeEventA(value=99))


@pytest.mark.asyncio
async def test_handler_exception_does_not_block_others(bus: EventBus) -> None:
    results: list[str] = []

    async def bad_handler(event: FakeEventA) -> None:
        raise RuntimeError("boom")

    async def good_handler(event: FakeEventA) -> None:
        results.append("ok")

    bus.subscribe(FakeEventA, bad_handler)
    bus.subscribe(FakeEventA, good_handler)
    await bus.publish(FakeEventA(value=0))

    assert results == ["ok"]


@pytest.mark.asyncio
async def test_handlers_run_concurrently(bus: EventBus) -> None:
    order: list[str] = []

    async def slow(event: FakeEventA) -> None:
        await asyncio.sleep(0.05)
        order.append("slow")

    async def fast(event: FakeEventA) -> None:
        order.append("fast")

    bus.subscribe(FakeEventA, slow)
    bus.subscribe(FakeEventA, fast)
    await bus.publish(FakeEventA(value=0))

    # fast should finish before slow because they run concurrently
    assert order == ["fast", "slow"]

# Voice Receive Diagnostics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-connection diagnostics that identify whether Discord voice degradation occurs at packet ingress, DAVE decryption, Opus decoding, PCM delivery, or chunk publication without changing recovery behavior.

**Architecture:** A focused `VoiceReceiveDiagnostics` class owns thread-safe counters, DAVE state transitions, RMS aggregation, rate-limited warnings, and interval snapshots. `discord_listener.py` attaches one instance to each `VoiceRecvClient`; the decoder monkey-patch, sink callback, and chunk emitter record their boundary observations into it.

**Tech Stack:** Python 3.10+, standard-library `threading`, `time`, `math`, `struct`, pytest, pytest-asyncio.

**Constraint:** Do not commit. Do not change `ListenerRecoverRequestEvent`, recovery thresholds, cooldowns, or reconnect conditions.

---

### Task 1: Thread-safe diagnostic accumulator

**Files:**
- Create: `src/rpg_scribe/listeners/voice_diagnostics.py`
- Create: `tests/test_voice_diagnostics.py`

- [ ] **Step 1: Write failing tests**

Add tests that import `DaveState` and `VoiceReceiveDiagnostics` and assert:

```python
diagnostics.record_dave_failure(ValueError("bad key"), now=10.0)
diagnostics.record_dave_failure(ValueError("bad key"), now=10.1)
assert diagnostics.snapshot(now=11.0)["dave_fail"] == 2
assert diagnostics.snapshot(now=11.0)["dave_fail_streak"] == 2
assert diagnostics.snapshot(now=11.0)["dave_errors"] == {"ValueError": 2}

diagnostics.record_dave_success(now=12.0)
assert diagnostics.snapshot(now=12.0)["dave_fail_streak"] == 0
assert diagnostics.snapshot(now=12.0)["dave_fail_streak_max"] == 2

assert diagnostics.observe_dave_state(DaveState(True, 1, True)) is True
assert diagnostics.observe_dave_state(DaveState(True, 1, True)) is False
assert diagnostics.observe_dave_state(DaveState(True, 1, False)) is True

diagnostics.record_pcm(b"\x10\x00" * 100, user_id="42", now=20.0)
diagnostics.record_chunk(byte_count=200, duration_ms=1000, publish_s=0.2, now=21.0)
snapshot = diagnostics.snapshot(now=22.0)
assert snapshot["pcm_callbacks"] == 1
assert snapshot["pcm_rms_avg"] == 16
assert snapshot["active_users"] == 1
assert snapshot["chunks"] == 1
assert snapshot["last_pcm_age_s"] == 2.0
```

Also test interval deltas, empty RMS, ages before first activity, and warning decisions at streaks 50, 250, 500 while suppressing intervening packets.

- [ ] **Step 2: Verify RED**

Run: `py -m pytest tests/test_voice_diagnostics.py -q`

Expected: FAIL because `rpg_scribe.listeners.voice_diagnostics` does not exist.

- [ ] **Step 3: Implement the accumulator**

Create immutable `DaveState(present, protocol_version, ready)` and a `VoiceReceiveDiagnostics(session_id, generation, clock=time.monotonic)` class. Protect mutable state with `threading.Lock`. Implement:

```python
record_packet(now=None)
record_gap(now=None)
observe_dave_state(state) -> bool
record_dave_success(now=None)
record_dave_failure(exc, now=None) -> bool
record_opus_success(now=None)
record_opus_failure(exc, now=None)
record_fec_silence(now=None)
record_pcm(pcm, user_id, now=None)
record_chunk(byte_count, duration_ms, publish_s, now=None)
snapshot(now=None, reset_interval=False) -> dict[str, object]
```

`record_dave_failure` returns `True` only at streak 50 and then at multiples of
250 (250, 500, ...). RMS is calculated over PCM16 samples without retaining
PCM. Snapshots contain totals, interval deltas, rates, exception-class counts,
current/max failure streak, current DAVE state, active-user count,
average/min/max RMS, average/max publish latency, and optional activity ages.

- [ ] **Step 4: Verify GREEN**

Run: `py -m pytest tests/test_voice_diagnostics.py -q`

Expected: all new tests pass.

### Task 2: Decoder, PCM, and chunk integration

**Files:**
- Modify: `src/rpg_scribe/listeners/discord_listener.py`
- Modify: `tests/test_audio_listener.py`

- [ ] **Step 1: Write failing integration tests**

Add listener tests with a fake voice client carrying `_rpg_scribe_diagnostics` and assert:

```python
listener._record_pcm_diagnostics("user1", stereo_pcm)
assert listener._voice_diagnostics.snapshot()["pcm_callbacks"] == 1

await listener._emit_chunk("user1")
assert listener._voice_diagnostics.snapshot()["chunks"] == 1
```

Add a test for `_current_dave_state(voice_client)` covering no connection, no session, and a ready DAVE session. Add a test that `_log_voice_diagnostics()` emits one summary and resets interval counters without changing cumulative counters.

- [ ] **Step 2: Verify RED**

Run: `py -m pytest tests/test_audio_listener.py -q`

Expected: FAIL because the integration helpers do not exist.

- [ ] **Step 3: Integrate diagnostics without behavior changes**

In `discord_listener.py`:

- Import `DaveState` and `VoiceReceiveDiagnostics`.
- Add `_VOICE_DIAGNOSTICS_INTERVAL_S = 10.0` and a monotonic generation counter.
- Attach diagnostics to the `VoiceRecvClient` immediately after connection and before `listen()`.
- In `_patched_decode_packet`, record packet/gap, DAVE state, decrypt success/failure, Opus success/failure, and FEC silence. Keep the existing return values and exception handling unchanged.
- Log a rate-limited warning when `record_dave_failure()` returns true. Include session, generation, exception class, streak, protocol and ready state.
- Record PCM before stereo-to-mono conversion in the sink callback.
- Time `event_bus.publish(event)` and record chunk bytes, duration, and latency after it returns.
- Emit an INFO summary every 10 seconds from `_periodic_flush`, including interval/cumulative counts, DAVE state, RMS, active users, and activity ages.
- Emit one INFO line when DAVE state changes.
- Emit a final summary during disconnect before dropping the voice client.

- [ ] **Step 4: Verify GREEN**

Run: `py -m pytest tests/test_audio_listener.py tests/test_voice_diagnostics.py -q`

Expected: all listener and diagnostic tests pass.

### Task 3: Documentation and regression verification

**Files:**
- Modify: `docs/discord-voice.md`

- [ ] **Step 1: Document the markers**

Describe the `Voice RX diag` summary, `DAVE state changed`, and `DAVE decrypt failure streak` warnings. Add a decision table mapping observed counters to transport, DAVE, Opus, router/sink, PCM-silence, and downstream blocking causes. State explicitly that diagnostics do not trigger recovery.

- [ ] **Step 2: Run focused tests**

Run: `py -m pytest tests/test_voice_diagnostics.py tests/test_audio_listener.py tests/test_transcriber.py tests/test_discord_bot.py -q`

Expected: all focused tests pass.

- [ ] **Step 3: Run lint**

Run: `py -m ruff check src/rpg_scribe/listeners/voice_diagnostics.py src/rpg_scribe/listeners/discord_listener.py tests/test_voice_diagnostics.py tests/test_audio_listener.py`

Expected: no lint errors.

- [ ] **Step 4: Run full regression suite**

Run: `py -m pytest -q`

Expected: no new failures beyond failures already documented in `CLAUDE.md`.

- [ ] **Step 5: Inspect the final diff**

Run: `git diff --check` and `git diff -- src/rpg_scribe/listeners/voice_diagnostics.py src/rpg_scribe/listeners/discord_listener.py tests/test_voice_diagnostics.py tests/test_audio_listener.py docs/discord-voice.md`

Expected: no whitespace errors; recovery code is unchanged.

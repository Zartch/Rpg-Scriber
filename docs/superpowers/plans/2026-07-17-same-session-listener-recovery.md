# Same-Session Listener Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recover a stalled Discord voice listener automatically without ending the active session or rotating its `session_id`.

**Architecture:** The transcriber detects prolonged stalls and publishes a dedicated recovery request event. `ScribeCog` owns the active Discord listener and handles the request by recreating the listener connection against the same voice channel and the same `session_id`, guarded so an intentional disconnect during recovery does not finalize the session.

**Tech Stack:** Python 3.10+, asyncio, discord.py, pytest, EventBus dataclass events.

---

### Task 1: Recovery event + transcriber stall signal

**Files:**
- Modify: `src/rpg_scribe/core/events.py`
- Modify: `src/rpg_scribe/transcribers/base.py`
- Test: `tests/test_transcriber.py`

- [ ] **Step 1: Write the failing transcriber regression test**
- [ ] **Step 2: Run the focused test and confirm it fails for missing recovery event behavior**
- [ ] **Step 3: Add a typed `ListenerRecoverRequestEvent` and publish it when a stall crosses the threshold**
- [ ] **Step 4: Re-run the focused transcriber tests and confirm they pass**

### Task 2: Same-session listener recovery in Discord bot

**Files:**
- Modify: `src/rpg_scribe/discord_bot/commands.py`
- Test: `tests/test_discord_bot.py`

- [ ] **Step 1: Write failing tests for same-session recovery, suppression of accidental session finalization, and stop behavior during degraded listener state**
- [ ] **Step 2: Run the focused Discord bot tests and confirm they fail for the missing recovery path**
- [ ] **Step 3: Implement recovery request subscription, recovery guards, and listener recreation using the same `session_id` and voice channel**
- [ ] **Step 4: Re-run the focused Discord bot tests and confirm they pass**

### Task 3: Focused verification

**Files:**
- Modify: none
- Test: `tests/test_transcriber.py`
- Test: `tests/test_discord_bot.py`

- [ ] **Step 1: Run the two focused test modules together**
- [ ] **Step 2: Inspect the final diff for accidental session-lifecycle changes outside the recovery scope**

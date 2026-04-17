# Chronology Injection into Narrative Summary — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Inject `_session_chronology` as context into the narrative summary prompt when it exists, and generate the chronology first in `finalize_session()` so the final narrative can use it.

**Architecture:** Two prompt templates (`SESSION_UPDATE_USER`, `FINALIZE_USER`) get an optional `{chronology_block}` placeholder. `finalize_session()` inverts its order: chronology first, then narrative. `_update_summary()` injects the chronology if non-empty (useful for on-demand refreshes after a prior finalization).

**Tech Stack:** Python 3.10, anthropic SDK, pytest + pytest-asyncio

---

## Files

- Modify: `src/rpg_scribe/summarizers/prompts.py` — add `{chronology_block}` to `SESSION_UPDATE_USER` and `FINALIZE_USER`
- Modify: `src/rpg_scribe/summarizers/claude_summarizer.py` — pass `chronology_block` in all prompt format calls; invert order in `finalize_session()`
- Modify: `tests/test_summarizer.py` — update `test_finalize_multi_batch` side_effect order; update `test_finalize_single_batch` comment

---

### Task 1: SESSION_UPDATE_USER + _update_summary() chronology injection

**Files:**
- Modify: `src/rpg_scribe/summarizers/prompts.py`
- Modify: `src/rpg_scribe/summarizers/claude_summarizer.py`
- Test: `tests/test_summarizer.py`

- [ ] **Step 1: Write the failing test**

Add to the `TestSessionSummarizer` class in `tests/test_summarizer.py`:

```python
@pytest.mark.asyncio
async def test_update_summary_injects_chronology_when_present(
    self, summarizer, bus, mock_client
):
    """When _session_chronology is set, it should appear in the update prompt."""
    mock_client.messages.create = AsyncMock(
        return_value=_mock_anthropic_response("Updated summary with chronology context")
    )
    await summarizer.start("session-1")
    summarizer._session_chronology = "Escena 1: Los héroes entran a la taberna."
    summarizer._pending.append(
        TranscriptionEntry("u1", "Aelar", "Buscamos al mercader", time.time())
    )

    await summarizer._update_summary()

    call_kwargs = mock_client.messages.create.call_args.kwargs
    user_content = call_kwargs["messages"][0]["content"]
    assert "CRONOLOGÍA DE LA SESIÓN:" in user_content
    assert "Escena 1: Los héroes entran a la taberna." in user_content

@pytest.mark.asyncio
async def test_update_summary_no_chronology_block_when_empty(
    self, summarizer, bus, mock_client
):
    """When _session_chronology is empty, no CRONOLOGÍA block in the prompt."""
    mock_client.messages.create = AsyncMock(
        return_value=_mock_anthropic_response("Updated summary")
    )
    await summarizer.start("session-1")
    summarizer._pending.append(
        TranscriptionEntry("u1", "Aelar", "Hello", time.time())
    )

    await summarizer._update_summary()

    call_kwargs = mock_client.messages.create.call_args.kwargs
    user_content = call_kwargs["messages"][0]["content"]
    assert "CRONOLOGÍA DE LA SESIÓN:" not in user_content
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_summarizer.py::TestSessionSummarizer::test_update_summary_injects_chronology_when_present tests/test_summarizer.py::TestSessionSummarizer::test_update_summary_no_chronology_block_when_empty -v
```

Expected: FAIL (KeyError on `chronology_block` not in format string, or assertion failure)

- [ ] **Step 3: Update SESSION_UPDATE_USER in prompts.py**

In `src/rpg_scribe/summarizers/prompts.py`, replace `SESSION_UPDATE_USER`:

```python
SESSION_UPDATE_USER = """\
TRANSCRIPCIÓN RECIENTE:
{recent_transcriptions}
{chronology_block}\
RESUMEN ACTUAL DE LA SESIÓN:
{current_session_summary}
{user_answers_block}\
Actualiza el resumen incorporando la nueva transcripción. \
Devuelve ÚNICAMENTE el resumen actualizado, sin explicaciones adicionales."""
```

- [ ] **Step 4: Update _update_summary() in claude_summarizer.py**

In `src/rpg_scribe/summarizers/claude_summarizer.py`, inside `_update_summary()`, replace the `user_msg` construction (around line 368):

```python
chronology_block = (
    f"CRONOLOGÍA DE LA SESIÓN:\n{self._session_chronology}\n\n"
    if self._session_chronology
    else ""
)
user_msg = SESSION_UPDATE_USER.format(
    recent_transcriptions=self._format_transcriptions(entries),
    current_session_summary=self._session_summary or "(inicio de sesión)",
    user_answers_block=user_answers_block if user_answers_block else "\n",
    chronology_block=chronology_block,
)
```

- [ ] **Step 5: Add chronology_block="" to all other SESSION_UPDATE_USER.format() calls**

There are two other places in `claude_summarizer.py` that format `SESSION_UPDATE_USER`:

**In `finalize_session()` multi-batch intermediate (around line 589):**
```python
user_msg = SESSION_UPDATE_USER.format(
    recent_transcriptions=batch_text,
    current_session_summary=running_summary,
    user_answers_block="\n",
    chronology_block="",
)
```

**In `generate_session_summary_from_transcriptions()` intermediate batches (around line 686):**
```python
result = await self._call_api(
    system,
    SESSION_UPDATE_USER.format(
        recent_transcriptions=batch_text,
        current_session_summary=running_summary,
        user_answers_block="\n",
        chronology_block="",
    ),
    purpose=f"posthoc_session_summary_batch_{i + 1}",
)
```

- [ ] **Step 6: Run the new tests + full suite**

```bash
pytest tests/test_summarizer.py::TestSessionSummarizer::test_update_summary_injects_chronology_when_present tests/test_summarizer.py::TestSessionSummarizer::test_update_summary_no_chronology_block_when_empty -v
```

Expected: PASS

```bash
pytest tests/test_summarizer.py -v
```

Expected: all previously passing tests still pass

- [ ] **Step 7: Commit**

```bash
git add src/rpg_scribe/summarizers/prompts.py src/rpg_scribe/summarizers/claude_summarizer.py tests/test_summarizer.py
git commit -m "feat: inject session chronology into narrative update prompt when available"
```

---

### Task 2: FINALIZE_USER + finalize_session() order inversion

**Files:**
- Modify: `src/rpg_scribe/summarizers/prompts.py`
- Modify: `src/rpg_scribe/summarizers/claude_summarizer.py`
- Test: `tests/test_summarizer.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_summarizer.py` in the `TestSessionSummarizer` class:

```python
@pytest.mark.asyncio
async def test_finalize_generates_chronology_before_narrative(
    self, summarizer, bus, mock_client
):
    """Chronology must be generated before the final narrative so the narrative
    can receive it as context."""
    chronology_response = "Escena 1: La taberna. Escena 2: La mazmorra."
    finalize_response = (
        "---SESSION_SUMMARY---\nLos héroes exploraron la mazmorra.\n\n"
        "---CAMPAIGN_SUMMARY---\nLa campaña avanza."
    )
    mock_client.messages.create = AsyncMock(
        side_effect=[
            _mock_anthropic_response(chronology_response),
            _mock_anthropic_response(finalize_response),
        ]
    )
    await summarizer.start("session-1")
    summarizer._pending.append(
        TranscriptionEntry("u1", "Aelar", "Entramos a la mazmorra", time.time())
    )

    result = await summarizer.finalize_session()

    assert result == "Los héroes exploraron la mazmorra."
    # Chronology was generated first and stored
    assert summarizer._session_chronology == chronology_response
    # The second API call (finalize narrative) must contain the chronology
    finalize_call_kwargs = mock_client.messages.create.call_args_list[1].kwargs
    finalize_content = finalize_call_kwargs["messages"][0]["content"]
    assert "CRONOLOGÍA DE LA SESIÓN:" in finalize_content
    assert chronology_response in finalize_content

@pytest.mark.asyncio
async def test_finalize_chronology_failure_does_not_block_narrative(
    self, summarizer, bus, mock_client
):
    """If chronology generation fails, finalize_session continues without it."""
    finalize_response = (
        "---SESSION_SUMMARY---\nResumen sin cronología.\n\n"
        "---CAMPAIGN_SUMMARY---\nCampaña."
    )
    call_count = 0

    async def side_effect_fn(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("Chronology API failed")
        return _mock_anthropic_response(finalize_response)

    mock_client.messages.create = AsyncMock(side_effect=side_effect_fn)
    await summarizer.start("session-1")
    summarizer._pending.append(
        TranscriptionEntry("u1", "Aelar", "Algo pasa", time.time())
    )

    result = await summarizer.finalize_session()

    assert result == "Resumen sin cronología."
    assert summarizer._session_chronology == ""
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_summarizer.py::TestSessionSummarizer::test_finalize_generates_chronology_before_narrative tests/test_summarizer.py::TestSessionSummarizer::test_finalize_chronology_failure_does_not_block_narrative -v
```

Expected: FAIL

- [ ] **Step 3: Update FINALIZE_USER in prompts.py**

In `src/rpg_scribe/summarizers/prompts.py`, replace `FINALIZE_USER`:

```python
FINALIZE_USER = """\
La sesión ha terminado. A continuación tienes el resumen de sesión \
y la transcripción completa pendiente.

RESUMEN DE SESIÓN ACTUAL:
{session_summary}

TRANSCRIPCIÓN PENDIENTE:
{pending_transcriptions}
{chronology_block}\
Genera:
1. Un resumen final pulido de la sesión (narrativo, detallado).
2. Una actualización del resumen de campaña incorporando esta sesión.

Responde con el siguiente formato exacto:

---SESSION_SUMMARY---
(resumen final de la sesión)

---CAMPAIGN_SUMMARY---
(resumen actualizado de la campaña)
"""
```

- [ ] **Step 4: Invert order in finalize_session() and pass chronology_block**

In `src/rpg_scribe/summarizers/claude_summarizer.py`, replace the body of `finalize_session()` starting from after `system = self._build_system_prompt()` up through `self._session_summary = session_part`:

```python
async def finalize_session(self) -> str:
    # Gather all remaining pending transcriptions
    all_entries = list(self._pending)
    self._pending.clear()

    system = self._build_system_prompt()

    # --- Step 1: Generate chronology first so the narrative can use it ---
    if all_entries:
        try:
            self._session_chronology = await self.generate_chronology(
                entries=all_entries,
            )
            logger.info("Session chronology generated")
        except Exception as exc:
            logger.error("Chronology generation failed: %s", exc)
            self._session_chronology = ""

    chronology_block = (
        f"CRONOLOGÍA DE LA SESIÓN:\n{self._session_chronology}\n\n"
        if self._session_chronology
        else ""
    )

    # --- Step 2: Generate final narrative summary with chronology as context ---
    template_overhead = len(FINALIZE_USER) + len(self._session_summary or "") + 200
    max_chars_for_transcriptions = self.config.max_input_chars - template_overhead

    if max_chars_for_transcriptions < 1000:
        max_chars_for_transcriptions = 1000

    pending_text = self._format_transcriptions(all_entries) if all_entries else ""

    if not pending_text or len(pending_text) <= max_chars_for_transcriptions:
        result = await self._call_api(
            system,
            FINALIZE_USER.format(
                session_summary=self._session_summary or "(sin resumen todavía)",
                pending_transcriptions=pending_text or "(ninguna)",
                chronology_block=chronology_block,
            ),
            purpose="finalize_session",
        )
        session_part, campaign_part = self._parse_finalize_response(result)
    else:
        logger.info(
            "Transcriptions too large for single call (%d chars, max %d). "
            "Using batched finalization.",
            len(pending_text),
            max_chars_for_transcriptions,
        )
        batches = self._split_into_batches(
            all_entries, max_chars_for_transcriptions
        )
        logger.info("Split into %d batch(es)", len(batches))

        running_summary = self._session_summary or "(inicio de sesión)"
        session_part = running_summary
        campaign_part = ""

        for i, batch in enumerate(batches):
            batch_text = self._format_transcriptions(batch)
            is_last = i == len(batches) - 1

            if is_last:
                user_msg = FINALIZE_USER.format(
                    session_summary=running_summary,
                    pending_transcriptions=batch_text,
                    chronology_block=chronology_block,
                )
                result = await self._call_api(
                    system, user_msg, purpose="finalize_session_last_batch"
                )
                session_part, campaign_part = self._parse_finalize_response(result)
            else:
                user_msg = SESSION_UPDATE_USER.format(
                    recent_transcriptions=batch_text,
                    current_session_summary=running_summary,
                    user_answers_block="\n",
                    chronology_block="",
                )
                result = await self._call_api(
                    system, user_msg, purpose=f"finalize_session_batch_{i + 1}"
                )
                running_summary = result.strip()
                logger.info(
                    "Batch %d/%d processed (%d transcriptions)",
                    i + 1,
                    len(batches),
                    len(batch),
                )

    self._session_summary = session_part
    if campaign_part:
        self._campaign_summary = campaign_part

    await self._publish_summary("final")

    # Extract structured entities/relationships from the final summary
    await self._extract_entities()

    logger.info("Session finalized")
    return self._session_summary
```

- [ ] **Step 5: Add chronology_block="" to FINALIZE_USER calls in generate_session_summary_from_transcriptions()**

In `generate_session_summary_from_transcriptions()`, both `FINALIZE_USER.format()` calls (single batch and last batch) need `chronology_block=""`:

**Single batch (around line 659):**
```python
result = await self._call_api(
    system,
    FINALIZE_USER.format(
        session_summary="(inicio de sesión)",
        pending_transcriptions=pending_text,
        chronology_block="",
    ),
    purpose="posthoc_session_summary",
)
```

**Last batch (around line 675):**
```python
result = await self._call_api(
    system,
    FINALIZE_USER.format(
        session_summary=running_summary,
        pending_transcriptions=batch_text,
        chronology_block="",
    ),
    purpose="posthoc_session_summary_last_batch",
)
```

- [ ] **Step 6: Update test_finalize_multi_batch — reorder side_effect**

In `tests/test_summarizer.py`, `test_finalize_multi_batch`, reorder the `side_effect` list from `[intermediate_resp, final_resp, chronology_resp]` to `[chronology_resp, intermediate_resp, final_resp]`:

```python
summarizer._get_client().messages.create = AsyncMock(
    side_effect=[chronology_resp, intermediate_resp, final_resp]
)
```

Also update the comment to reflect the new order:
```python
# Should have made at least 3 API calls (chronology + intermediate + final)
assert summarizer._get_client().messages.create.call_count >= 3
```

And update `test_finalize_single_batch` comment:
```python
# Chronology + finalize = 2 API calls
assert summarizer._get_client().messages.create.call_count == 2
```

- [ ] **Step 7: Run the new tests**

```bash
pytest tests/test_summarizer.py::TestSessionSummarizer::test_finalize_generates_chronology_before_narrative tests/test_summarizer.py::TestSessionSummarizer::test_finalize_chronology_failure_does_not_block_narrative -v
```

Expected: PASS

- [ ] **Step 8: Run the full test suite**

```bash
pytest tests/test_summarizer.py -v
```

Expected: all previously passing tests still pass (known pre-existing failures excluded)

- [ ] **Step 9: Run linter**

```bash
ruff check src/rpg_scribe/summarizers/ tests/test_summarizer.py
```

Expected: no errors

- [ ] **Step 10: Commit**

```bash
git add src/rpg_scribe/summarizers/prompts.py src/rpg_scribe/summarizers/claude_summarizer.py tests/test_summarizer.py
git commit -m "feat: generate chronology first in finalize_session and inject into final narrative prompt"
```

"""rag_lib chunking logic — prose splitting, table formatting, heading detection."""
from __future__ import annotations

import hashlib
import logging
from typing import Any

import tiktoken

from rag_lib.types import ParsedPage, ProseBlock, TableBlock, TocEntry

logger = logging.getLogger(__name__)

_ENC = tiktoken.get_encoding("cl100k_base")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def gfm_table(rows: list[list[str]]) -> str:
    """Serialize a table (list of rows) as a GFM Markdown table string."""
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    # Normalize each cell: strip whitespace, replace newlines, escape pipes
    def clean(cell: str) -> str:
        return cell.replace("\n", " ").replace("|", r"\|").strip()

    norm = [[clean(cell) for cell in row] + [""] * (width - len(row)) for row in rows]
    header, *body = norm
    sep = ["---"] * width
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(sep) + " |",
        *("| " + " | ".join(row) + " |" for row in body),
    ]
    return "\n".join(lines)


def should_merge_across_pages(last_text: str, next_text: str) -> bool:
    """Return True if the prose in next_text appears to continue last_text across a page boundary.

    Decision criteria (your domain knowledge matters here):
    - If last_text is empty or next_text is empty → False (nothing to merge)
    - If last_text ends with a sentence terminator → False (idea is complete)
    - If next_text starts with an uppercase letter → False (new sentence/paragraph)
    - Otherwise → True (paragraph likely continues)

    Sentence terminators to consider for RPG manuals (Spanish + English):
      ., !, ?, …  and their Spanish variants ¡ ¿ do NOT terminate — they open sentences.
      Consider also: ), ], », :, ; — are these terminators for your domain?

    TODO: Implement this function (5-10 lines).
    The implementation below is a placeholder that always returns False.
    Replace it with your decision logic.
    """
    if not last_text or not next_text:
        return False
    last_char = last_text.rstrip()[-1]
    next_first = next_text.lstrip()[0]
    # ':' included — RPG lists often start "Ataque: ..." with the list on the next page
    TERMINATORS = {'.', '!', '?', '…', ':'}
    return last_char not in TERMINATORS and not next_first.isupper()


def _toc_path_at(page: int, toc: list[TocEntry]) -> str | None:
    """Return the active hierarchical TOC path for a given page number.

    Scans the TOC in order. Entries with page > given page stop the scan.
    When a new entry appears at level N, all levels deeper than N are cleared.
    Assumes toc is sorted by page ascending (guaranteed by extract_toc).
    """
    active: dict[int, str] = {}
    for entry in toc:
        if entry.page > page:
            break
        active[entry.level] = entry.title
        for deeper in [lvl for lvl in active if lvl > entry.level]:
            del active[deeper]
    if not active:
        return None
    return " / ".join(active[lvl] for lvl in sorted(active))


def run_chunker(
    pages: list[ParsedPage],
    *,
    token_target: int = 500,
    overlap: int = 75,
    toc: list[TocEntry] | None = None,
) -> list[dict[str, Any]]:
    """Process ParsedPages into chunk dicts ready for DB insertion.

    Each returned dict has keys: seq, chunk_type, page, page_end, section_path,
    text, text_hash, token_count.
    """
    # Pass 1: collect all ProseBlock fontsizes to compute p90.
    # This threshold is always computed.  What changes with TOC presence is what
    # we DO with large-font blocks (see main loop below).
    all_fontsizes = [
        b.fontsize_avg
        for p in pages
        for b in p.blocks
        if isinstance(b, ProseBlock)
    ]
    heading_threshold = _compute_p90(all_fontsizes)
    logger.debug("Heading threshold (p90 fontsize): %.1f", heading_threshold)
    # When a TOC is available it covers the full hierarchy.  Large-font blocks
    # are decorative elements (chapter art, background titles) that must be
    # discarded rather than used for section_path or body text.
    use_fontsize_headings = not toc

    # State
    chunks: list[dict[str, Any]] = []
    seq = 0
    section_stack: list[tuple[float, str]] = []  # (fontsize, heading_text)
    prose_buffer = ""
    buffer_page_start: int | None = None
    buffer_page_end: int | None = None
    last_prose_text: str = ""
    last_page: int | None = None

    # ------------------------------------------------------------------
    # Helpers (closures over state above)
    # ------------------------------------------------------------------

    def current_section_path(page: int | None = None) -> str | None:
        actual_page = page or buffer_page_start or 1
        toc_base = _toc_path_at(actual_page, toc) if toc else None
        fontsize_part = " / ".join(text for _, text in section_stack) if section_stack else None
        if toc_base and fontsize_part:
            return toc_base + " / " + fontsize_part
        return toc_base or fontsize_part

    def _make_hash(text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()

    def _emit(text: str, chunk_type: str, page: int, page_end: int | None, section_path: str | None) -> None:
        nonlocal seq
        text = text.strip()
        if not text:
            return
        tokens = _ENC.encode(text)
        chunks.append({
            "seq": seq,
            "chunk_type": chunk_type,
            "page": page,
            "page_end": page_end,
            "section_path": section_path,
            "text": text,
            "text_hash": _make_hash(text),
            "token_count": len(tokens),
        })
        seq += 1

    def _flush_buffer() -> None:
        nonlocal prose_buffer, buffer_page_start, buffer_page_end
        if prose_buffer.strip():
            _emit(
                prose_buffer,
                "prose",
                buffer_page_start or 1,
                buffer_page_end if buffer_page_end != buffer_page_start else None,
                current_section_path(),
            )
        prose_buffer = ""
        buffer_page_start = None
        buffer_page_end = None

    def _split_oversized_buffer() -> None:
        """Emit complete chunks from buffer while it exceeds token_target, keeping overlap."""
        nonlocal prose_buffer
        while True:
            tokens = _ENC.encode(prose_buffer)
            if len(tokens) <= token_target:
                break
            # Decode up to token_target tokens, trim to word boundary
            prefix = _ENC.decode(tokens[:token_target])
            last_space = prefix.rfind(" ")
            if last_space > 0:
                prefix = prefix[:last_space]
            _emit(
                prefix,
                "prose",
                buffer_page_start or 1,
                buffer_page_end if buffer_page_end != buffer_page_start else None,
                current_section_path(),
            )
            # Overlap: carry last `overlap` tokens into next buffer
            overlap_tokens = tokens[max(0, token_target - overlap):token_target]
            overlap_text = _ENC.decode(overlap_tokens)
            remainder = prose_buffer[len(prefix):].lstrip()
            prose_buffer = (overlap_text + " " + remainder).strip()

    def _add_prose(text: str, page: int) -> None:
        nonlocal prose_buffer, buffer_page_start, buffer_page_end
        if buffer_page_start is None:
            buffer_page_start = page
        buffer_page_end = page
        prose_buffer = (prose_buffer + " " + text).strip()

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    for page in pages:
        for block in page.blocks:
            if isinstance(block, TableBlock):
                # Flush any pending prose
                _split_oversized_buffer()
                _flush_buffer()
                # Build table chunk text
                sp = current_section_path(block.page)
                parts = []
                if sp:
                    parts.append(f"[{sp}]")
                if block.caption:
                    parts.append(f"Tabla: {block.caption}")
                parts.append("")  # blank line before table
                parts.append(gfm_table(block.rows))
                _emit("\n".join(parts), "table", block.page, None, sp)

            elif isinstance(block, ProseBlock):
                if _is_toc_noise(block.text):
                    continue

                # Non-TOC: strictly greater than p90 to avoid flagging body text when all
                # fontsizes are uniform (p90 == body fontsize).
                # TOC mode: >= catches decorative blocks sitting exactly at the p90 boundary
                # (e.g. 19pt art titles when threshold == 19.0).
                if use_fontsize_headings:
                    is_large_font = heading_threshold > 0 and block.fontsize_avg > heading_threshold
                else:
                    is_large_font = heading_threshold > 0 and block.fontsize_avg >= heading_threshold

                if is_large_font and use_fontsize_headings:
                    # No TOC: treat as structural heading → update section_stack
                    _split_oversized_buffer()
                    _flush_buffer()
                    while section_stack and section_stack[-1][0] <= block.fontsize_avg:
                        section_stack.pop()
                    section_stack.append((block.fontsize_avg, block.text.strip()))
                elif is_large_font:
                    # TOC mode: large-font block is decorative art → discard entirely
                    _split_oversized_buffer()
                    _flush_buffer()
                else:
                    # Body text
                    if last_page is not None and block.page != last_page and prose_buffer:
                        try:
                            merge = should_merge_across_pages(last_prose_text, block.text)
                        except NotImplementedError:
                            merge = False
                        if not merge:
                            _split_oversized_buffer()
                            _flush_buffer()

                    _add_prose(block.text, block.page)
                    _split_oversized_buffer()
                    last_prose_text = block.text
                    last_page = block.page

    # Flush any remaining prose
    _split_oversized_buffer()
    _flush_buffer()

    return chunks


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _is_toc_noise(text: str) -> bool:
    """True if block looks like a table-of-contents line (dot leaders + page numbers)."""
    if len(text) < 20:
        return False
    return text.count(".") / len(text) > 0.30


def _compute_p90(values: list[float]) -> float:
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    idx = int(len(sorted_vals) * 0.9)
    return sorted_vals[min(idx, len(sorted_vals) - 1)]

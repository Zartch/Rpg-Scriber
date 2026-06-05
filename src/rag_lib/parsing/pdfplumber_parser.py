"""PdfParser implementation using pdfplumber."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import pdfplumber
from pdfminer.pdfdocument import PDFNoOutlines
from pdfminer.pdftypes import PDFObjRef

from rag_lib.errors import PdfParseError
from rag_lib.parsing.base import PdfParser
from rag_lib.types import ParsedPage, ProseBlock, TableBlock

if TYPE_CHECKING:
    import pdfplumber.page

logger = logging.getLogger(__name__)

_CAPTION_LOOKAHEAD_PT = 40.0

# Fuentes small-caps decorativas (flavor sidebars) cuyo texto sale scrambled —
# se descartan en la ingesta porque son ambientación, no reglas.
_DECORATIVE_FONT_MARKERS = ("SC700",)

_MIN_GUTTER_PT = 10.0
_GUTTER_CENTRAL_BAND = (0.30, 0.70)
_GUTTER_MIN_SIDE_FRAC = 0.15


def _dedup_and_drop(chars: list[dict]) -> list[dict]:
    """Drop decorative-font chars and de-duplicate chars at the same (x0, top, text).

    PDFs decorativos renderizan glifos dos veces en coordenadas idénticas; los
    sidebars de flavor usan fuentes *SC700* que salen ilegibles. Ambos son ruido.
    """
    seen: set[tuple[float, float, str | None]] = set()
    kept: list[dict] = []
    for c in chars:
        font = c.get("fontname", "")
        if any(marker in font for marker in _DECORATIVE_FONT_MARKERS):
            continue
        key = (round(float(c["x0"]), 1), round(float(c["top"]), 1), c.get("text"))
        if key in seen:
            continue
        seen.add(key)
        kept.append(c)
    return kept


def _group_lines(chars: list[dict]) -> list[list[dict]]:
    """Group chars into visual lines by top coordinate (±2pt), top→bottom."""
    chars_sorted = sorted(chars, key=lambda c: (round(float(c["top"]) / 2) * 2, float(c["x0"])))
    lines: list[list[dict]] = []
    for ch in chars_sorted:
        if lines and abs(float(lines[-1][0]["top"]) - float(ch["top"])) <= 2.0:
            lines[-1].append(ch)
        else:
            lines.append([ch])
    return lines


def _body_chars(chars: list[dict]) -> list[dict]:
    """Chars at body fontsize (≤1.5× the page's 10th-percentile size).

    Excludes large spanning titles so they don't fill the column gutter.
    """
    sizes = sorted(float(c["size"]) for c in chars if c.get("size") and float(c["size"]) > 0)
    if not sizes:
        return chars
    p10 = sizes[max(0, int(len(sizes) * 0.1))]
    limit = max(p10, 6.0) * 1.5
    return [c for c in chars if float(c.get("size", p10)) <= limit]


def _strip_overlay(lines: list[list[dict]]) -> list[list[dict]]:
    """Step 2.5 — drop decorative overlay chars from mixed-fontsize lines."""
    cleaned: list[list[dict]] = []
    for line in lines:
        sizes = sorted(float(c["size"]) for c in line if c.get("size") and float(c["size"]) > 0)
        if not sizes:
            cleaned.append(line)
            continue
        p10 = sizes[max(0, int(len(sizes) * 0.1))]
        limit = max(p10, 6.0) * 1.5
        kept = [c for c in line if float(c.get("size", p10)) <= limit]
        cleaned.append(kept if kept else line)
    return cleaned


def _line_fontsize(line: list[dict]) -> float:
    sizes = [float(c["size"]) for c in line if c.get("size")]
    return sum(sizes) / len(sizes) if sizes else 11.0


def _line_text(line: list[dict]) -> str:
    return "".join(c.get("text", "") for c in sorted(line, key=lambda c: float(c["x0"])))


def _lines_to_blocks(lines: list[list[dict]]) -> list[tuple[str, float]]:
    """Step 3 — group adjacent lines with similar fontsize (±1pt) into blocks.

    Preserves input order (does NOT re-sort by top): callers establish reading
    order beforehand (single-column lines arrive top-sorted from _group_lines;
    two-column lines arrive in reading order from _segment_reading_order).
    """
    blocks: list[tuple[str, float]] = []
    current_lines: list[list[dict]] = []
    current_fs: float | None = None

    for line in lines:
        fs = _line_fontsize(line)
        if current_fs is None or abs(fs - current_fs) <= 1.0:
            if current_fs is None:
                current_fs = fs
            current_lines.append(line)
        else:
            text = " ".join(_line_text(ln) for ln in current_lines).strip()
            if text:
                blocks.append((text, current_fs))
            current_lines = [line]
            current_fs = fs

    if current_lines:
        text = " ".join(_line_text(ln) for ln in current_lines).strip()
        if text:
            blocks.append((text, current_fs or 11.0))
    return blocks


def _detect_gutter(body_chars: list[dict], page_width: float) -> float | None:
    """Return the x of a vertical gutter splitting two columns, or None.

    Proyecta los intervalos [x0, x1] de los body chars sobre el eje X y busca
    la banda contigua de cobertura cero más ancha en la región central. Acepta
    si es ≥ _MIN_GUTTER_PT y hay ≥15% de chars a cada lado.
    """
    import math

    if not body_chars or page_width <= 0:
        return None
    width = int(math.ceil(page_width))
    coverage = [0] * (width + 1)
    for c in body_chars:
        x0 = int(max(0.0, float(c["x0"])))
        x1 = int(min(float(width), float(c.get("x1", c["x0"]))))
        if x1 < x0:
            x1 = x0
        for x in range(x0, x1 + 1):
            coverage[x] += 1

    lo = int(width * _GUTTER_CENTRAL_BAND[0])
    hi = int(width * _GUTTER_CENTRAL_BAND[1])
    best_start = best_len = 0
    run_start: int | None = None
    for x in range(lo, hi + 1):
        if coverage[x] == 0:
            if run_start is None:
                run_start = x
            if x - run_start + 1 > best_len:
                best_len = x - run_start + 1
                best_start = run_start
        else:
            run_start = None

    if best_len < _MIN_GUTTER_PT:
        return None
    gutter = best_start + best_len / 2.0
    left = sum(1 for c in body_chars if float(c["x0"]) < gutter)
    right = len(body_chars) - left
    threshold = _GUTTER_MIN_SIDE_FRAC * len(body_chars)
    if left < threshold or right < threshold:
        return None
    return gutter


def _segment_reading_order(
    lines: list[list[dict]], gutter_x: float, tol: float = 2.0
) -> list[list[dict]]:
    """Reorder line-clusters into two-column reading order.

    Cada línea cruda (cluster por top) se clasifica:
      - cruza el canalón (algún char ocupa [gutter_x±tol]) → ancho completo,
        separa bandas y se emite entera en orden documental.
      - no lo cruza → columnar: se parte en sub-línea izquierda/derecha por
        el centro del char.
    Orden final: por bandas delimitadas por líneas full-width; dentro de cada
    banda todas las sub-líneas izquierdas (top↑) y luego las derechas (top↑).
    """
    def crosses(line: list[dict]) -> bool:
        return any(
            float(c["x0"]) < gutter_x + tol and float(c.get("x1", c["x0"])) > gutter_x - tol
            for c in line
        )

    ordered: list[list[dict]] = []
    left_buf: list[list[dict]] = []
    right_buf: list[list[dict]] = []

    def flush() -> None:
        ordered.extend(left_buf)
        ordered.extend(right_buf)
        left_buf.clear()
        right_buf.clear()

    for line in lines:
        if crosses(line):
            flush()
            ordered.append(line)
            continue
        left = [c for c in line if (float(c["x0"]) + float(c.get("x1", c["x0"]))) / 2.0 < gutter_x]
        right = [c for c in line if (float(c["x0"]) + float(c.get("x1", c["x0"]))) / 2.0 >= gutter_x]
        if left:
            left_buf.append(left)
        if right:
            right_buf.append(right)
    flush()
    return ordered


def _reading_order_blocks(chars: list[dict], page_width: float) -> list[tuple[str, float]]:
    """Core: chars → (text, fontsize) blocks in reading order (1 o 2 columnas)."""
    chars = [c for c in chars if c.get("size") and float(c["size"]) > 0 and c.get("text", "")]
    if not chars:
        return []
    lines = _group_lines(chars)
    gutter = _detect_gutter(_body_chars(chars), page_width)
    if gutter is not None:
        lines = _segment_reading_order(lines, gutter)
    lines = _strip_overlay(lines)
    return _lines_to_blocks(lines)


class PdfplumberParser(PdfParser):
    def parse(self, pdf_path: str | Path) -> list[ParsedPage]:
        try:
            pdf = pdfplumber.open(str(pdf_path))
        except FileNotFoundError as exc:
            raise PdfParseError(f"File not found: {pdf_path}") from exc
        except Exception as exc:
            raise PdfParseError(f"Cannot open PDF: {exc}") from exc

        pages: list[ParsedPage] = []
        try:
            for page_obj in pdf.pages:
                try:
                    pages.append(self._parse_page(page_obj))
                except Exception as exc:
                    logger.warning(
                        "rag_lib: page %d parse failed (%s); falling back to empty",
                        page_obj.page_number, exc,
                    )
                    pages.append(ParsedPage(page_num=page_obj.page_number, blocks=[]))
        finally:
            pdf.close()

        return pages

    def extract_toc(self, pdf_path: str | Path) -> list:
        """Extract the PDF outline/bookmarks as a list of TocEntry, sorted by page.

        Returns [] if the PDF has no digital outline or if parsing fails.
        Uses pdfminer (already installed via pdfplumber) — no new dependencies.
        """
        from rag_lib.types import TocEntry

        try:
            pdf = pdfplumber.open(str(pdf_path))
        except Exception:
            return []

        try:
            doc = pdf.doc
            pageid_map: dict[int, int] = {
                p.page_obj.pageid: p.page_number for p in pdf.pages
            }

            try:
                raw_outlines = list(doc.get_outlines())
            except PDFNoOutlines:
                return []
            except Exception:
                return []

            entries: list[TocEntry] = []
            for level, title, dest, action, _se in raw_outlines:
                # Some PDFs use GoTo actions instead of direct destinations
                page_num = self._resolve_dest_page(dest if dest is not None else action, pageid_map, doc)
                if page_num is None:
                    continue
                entries.append(TocEntry(level=level, title=str(title), page=page_num))

            return sorted(entries, key=lambda e: e.page)
        finally:
            pdf.close()

    def _resolve_dest_page(
        self, dest: object, pageid_map: dict[int, int], doc: object
    ) -> int | None:
        """Resolve a pdfminer destination object to a 1-based page number.

        Handles direct destinations (list/named), GoTo action dicts, and
        PDFObjRef indirections (e.g. PDFs created with InDesign/iLovePDF).
        """
        try:
            if isinstance(dest, PDFObjRef):
                resolved = dest.resolve()
                if isinstance(resolved, dict):
                    # GoTo action: {'S': /GoTo, 'D': destination}
                    d = resolved.get(b"D") or resolved.get("D")
                    if d is not None:
                        return self._resolve_dest_page(d, pageid_map, doc)
                return self._resolve_dest_page(resolved, pageid_map, doc)
            if isinstance(dest, list) and dest:
                ref = dest[0]
                if isinstance(ref, PDFObjRef):
                    return pageid_map.get(ref.objid)
            elif isinstance(dest, (bytes, str)):
                resolved = doc.get_dest(dest)
                return self._resolve_dest_page(resolved, pageid_map, doc)
        except Exception:
            pass
        return None

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _deduped_page(self, page_obj: pdfplumber.page.Page):
        """Return a FilteredPage with decorative fonts dropped and positional
        duplicates removed, so tables, captions and prose share clean chars."""
        kept_ids = {id(c) for c in _dedup_and_drop(page_obj.chars)}

        def keep(obj: dict) -> bool:
            return obj.get("object_type") != "char" or id(obj) in kept_ids

        return page_obj.filter(keep)

    def _parse_page(self, page_obj: pdfplumber.page.Page) -> ParsedPage:
        page_num: int = page_obj.page_number  # pdfplumber is 1-indexed
        page = self._deduped_page(page_obj)
        blocks: list[ProseBlock | TableBlock] = []

        # find_tables() internally crops to detected table bboxes with strict=True;
        # some PDFs have objects with coords slightly outside the page (e.g. x0 < 0)
        # which makes that crop raise ValueError. Catch and skip affected tables.
        try:
            found_tables = page.find_tables()
        except ValueError:
            found_tables = []

        table_bboxes = []
        for ft in found_tables:
            try:
                rows_raw = ft.extract() or []
            except ValueError:
                logger.debug("rag_lib: page %d — skipping table with out-of-bounds bbox", page_num)
                continue
            rows = [[cell or "" for cell in row] for row in rows_raw]
            caption = self._extract_caption(page, ft.bbox)
            blocks.append(TableBlock(rows=rows, page=page_num, caption=caption))
            table_bboxes.append(ft.bbox)

        for text, fontsize in self._extract_prose_groups(page, table_bboxes):
            blocks.append(ProseBlock(text=text, page=page_num, fontsize_avg=fontsize))

        return ParsedPage(page_num=page_num, blocks=blocks)

    def _extract_caption(
        self, page_obj: pdfplumber.page.Page, table_bbox: tuple
    ) -> str | None:
        x0, top, x1, _bottom = table_bbox
        # Clamp to page bounds — table bboxes can extend slightly outside
        x0 = max(0.0, x0)
        x1 = min(float(page_obj.width), x1)
        top_clamped = max(0.0, top)
        if x1 <= x0 or top_clamped <= 0.0:
            return None
        try:
            region = page_obj.crop(
                (x0, max(0.0, top_clamped - _CAPTION_LOOKAHEAD_PT), x1, top_clamped)
            )
            blocks = _reading_order_blocks(list(region.chars), float(page_obj.width))
        except ValueError:
            return None
        text = " ".join(t for t, _ in blocks)
        return text.strip() if text.strip() else None

    def _chars_outside_tables(
        self, page_obj: pdfplumber.page.Page, table_bboxes: list[tuple]
    ) -> list[dict]:
        """Step 1 — chars del page que no caen dentro de ninguna table bbox."""
        if table_bboxes:
            def outside_tables(obj: dict) -> bool:
                if obj.get("object_type") != "char":
                    return True
                for tb in table_bboxes:
                    if (
                        obj.get("x0", 0) >= tb[0] - 1
                        and obj.get("x1", 0) <= tb[2] + 1
                        and obj.get("top", 0) >= tb[1] - 1
                        and obj.get("bottom", 0) <= tb[3] + 1
                    ):
                        return False
                return True
            filtered = page_obj.filter(outside_tables)
        else:
            filtered = page_obj
        return [
            c for c in filtered.chars
            if c.get("size") and float(c["size"]) > 0 and c.get("text", "")
        ]

    def _extract_prose_groups(
        self, page_obj: pdfplumber.page.Page, table_bboxes: list[tuple]
    ) -> list[tuple[str, float]]:
        """Return prose text grouped by fontsize — one (text, fontsize_avg) per block."""
        chars = self._chars_outside_tables(page_obj, table_bboxes)
        return _reading_order_blocks(chars, float(page_obj.width))


"""PdfParser implementation using pdfplumber."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import pdfplumber

from rag_lib.errors import PdfParseError
from rag_lib.parsing.base import PdfParser
from rag_lib.types import ParsedPage, ProseBlock, TableBlock

if TYPE_CHECKING:
    import pdfplumber.page

logger = logging.getLogger(__name__)

_CAPTION_LOOKAHEAD_PT = 40.0


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

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _parse_page(self, page_obj: pdfplumber.page.Page) -> ParsedPage:
        page_num: int = page_obj.page_number  # pdfplumber is 1-indexed
        blocks: list[ProseBlock | TableBlock] = []

        # find_tables() internally crops to detected table bboxes with strict=True;
        # some PDFs have objects with coords slightly outside the page (e.g. x0 < 0)
        # which makes that crop raise ValueError. Catch and skip affected tables.
        try:
            found_tables = page_obj.find_tables()
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
            caption = self._extract_caption(page_obj, ft.bbox)
            blocks.append(TableBlock(rows=rows, page=page_num, caption=caption))
            table_bboxes.append(ft.bbox)

        for text, fontsize in self._extract_prose_groups(page_obj, table_bboxes):
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
            text = region.extract_text()
        except ValueError:
            return None
        return text.strip() if text and text.strip() else None

    def _extract_prose_groups(
        self, page_obj: pdfplumber.page.Page, table_bboxes: list[tuple]
    ) -> list[tuple[str, float]]:
        """Return prose text grouped by fontsize — one (text, fontsize_avg) per visual block.

        Algorithm:
        1. Filter chars outside table bboxes.
        2. Group chars into lines by vertical proximity (±2pt).
        3. Group adjacent lines with similar fontsize (±1pt) into blocks.
        4. Return (block_text, fontsize_avg) pairs sorted top→bottom.
        """
        # Step 1: filter chars
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

        chars = [
            c for c in filtered.chars
            if c.get("size") and float(c["size"]) > 0 and c.get("text", "").strip()
        ]
        if not chars:
            return []

        # Step 2: group chars into lines by top coordinate (±2pt tolerance)
        chars_sorted = sorted(chars, key=lambda c: (round(float(c["top"]) / 2) * 2, float(c["x0"])))
        lines: list[list[dict]] = []
        for ch in chars_sorted:
            placed = False
            for line in lines:
                if abs(float(ch["top"]) - float(line[0]["top"])) <= 2.0:
                    line.append(ch)
                    placed = True
                    break
            if not placed:
                lines.append([ch])

        # Step 3: group adjacent lines with similar fontsize (±1pt) into blocks
        def _line_fontsize(line: list[dict]) -> float:
            sizes = [float(c["size"]) for c in line if c.get("size")]
            return sum(sizes) / len(sizes) if sizes else 11.0

        def _line_text(line: list[dict]) -> str:
            return "".join(c.get("text", "") for c in sorted(line, key=lambda c: float(c["x0"])))

        blocks: list[tuple[str, float]] = []
        current_lines: list[list[dict]] = []
        current_fs: float | None = None

        for line in sorted(lines, key=lambda ln: float(ln[0]["top"])):
            fs = _line_fontsize(line)
            if current_fs is None or abs(fs - current_fs) <= 1.0:
                current_lines.append(line)
                sizes_all = [float(c["size"]) for ln in current_lines for c in ln if c.get("size")]
                current_fs = sum(sizes_all) / len(sizes_all) if sizes_all else fs
            else:
                # Flush current block
                text = " ".join(_line_text(ln) for ln in current_lines).strip()
                if text:
                    blocks.append((text, current_fs))
                current_lines = [line]
                current_fs = fs

        # Flush last block
        if current_lines:
            sizes_all = [float(c["size"]) for ln in current_lines for c in ln if c.get("size")]
            fs_final = sum(sizes_all) / len(sizes_all) if sizes_all else 11.0
            text = " ".join(_line_text(ln) for ln in current_lines).strip()
            if text:
                blocks.append((text, fs_final))

        return blocks

    def _extract_prose(
        self, page_obj: pdfplumber.page.Page, table_bboxes: list[tuple]
    ) -> tuple[str, float]:
        if table_bboxes:
            # Keep only chars outside every table bbox
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

        text = filtered.extract_text() or ""
        chars = filtered.chars
        sizes = [float(c["size"]) for c in chars if c.get("size") and float(c["size"]) > 0]
        fontsize_avg = sum(sizes) / len(sizes) if sizes else 11.0

        return text, fontsize_avg

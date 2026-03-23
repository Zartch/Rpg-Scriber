"""Session export bundle generation for the web UI."""

from __future__ import annotations

import csv
import html
import re
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import Any


_EXPORT_CSS = """\
:root {
  --bg: #060816;
  --bg-alt: #0a0f24;
  --surface: rgba(10, 15, 36, 0.88);
  --surface-strong: rgba(16, 23, 52, 0.96);
  --surface-soft: rgba(12, 18, 40, 0.72);
  --border: rgba(58, 236, 255, 0.18);
  --border-strong: rgba(255, 63, 181, 0.32);
  --text: #e6f4ff;
  --muted: #89a0c7;
  --accent: #3aecff;
  --accent-2: #ff3fb5;
  --accent-3: #b7ff3c;
  --shadow: 0 22px 90px rgba(0, 0, 0, 0.45);
}

* { box-sizing: border-box; }

html {
  scroll-behavior: smooth;
}

body {
  margin: 0;
  color: var(--text);
  font-family: "Segoe UI", Tahoma, Geneva, Verdana, sans-serif;
  background:
    radial-gradient(circle at top left, rgba(58, 236, 255, 0.15), transparent 28%),
    radial-gradient(circle at top right, rgba(255, 63, 181, 0.16), transparent 22%),
    radial-gradient(circle at 80% 120%, rgba(183, 255, 60, 0.08), transparent 24%),
    linear-gradient(180deg, #060816 0%, #070b1a 50%, #05070f 100%);
}

body::before {
  content: "";
  position: fixed;
  inset: 0;
  pointer-events: none;
  background-image:
    linear-gradient(rgba(58, 236, 255, 0.04) 1px, transparent 1px),
    linear-gradient(90deg, rgba(58, 236, 255, 0.04) 1px, transparent 1px);
  background-size: 34px 34px;
  opacity: 0.35;
}

.shell {
  position: relative;
  width: min(1240px, calc(100% - 32px));
  margin: 18px auto 36px;
}

.command-deck {
  display: grid;
  grid-template-columns: minmax(0, 1.45fr) minmax(0, 0.95fr);
  gap: 16px;
  margin-bottom: 16px;
}

.panel {
  background: linear-gradient(180deg, rgba(15, 22, 48, 0.94), rgba(8, 13, 30, 0.9));
  border: 1px solid var(--border);
  border-radius: 24px;
  box-shadow: var(--shadow);
  backdrop-filter: blur(10px);
}

.masthead {
  padding: 22px 24px;
  position: relative;
  overflow: hidden;
}

.masthead::after {
  content: "";
  position: absolute;
  right: -40px;
  top: -40px;
  width: 180px;
  height: 180px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(255, 63, 181, 0.2), transparent 70%);
  pointer-events: none;
}

.eyebrow {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
  padding: 6px 10px;
  border-radius: 999px;
  border: 1px solid rgba(58, 236, 255, 0.28);
  background: rgba(58, 236, 255, 0.08);
  color: var(--accent);
  font-size: 0.72rem;
  font-weight: 800;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}

.masthead-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 18px;
}

.masthead-copy h1 {
  margin: 0 0 8px;
  font-size: clamp(1.5rem, 3vw, 2.35rem);
  line-height: 0.98;
  letter-spacing: -0.04em;
}

.masthead-copy p {
  margin: 0;
  max-width: 560px;
  color: var(--muted);
  font-size: 0.95rem;
  line-height: 1.45;
}

.session-chip {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  margin-top: 14px;
  padding: 7px 10px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.08);
  color: var(--muted);
  font-size: 0.82rem;
}

.session-chip code {
  color: var(--text);
  font-family: "Consolas", "Courier New", monospace;
}

.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  justify-content: flex-end;
  min-width: 200px;
}

.actions a {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 132px;
  padding: 10px 14px;
  border-radius: 14px;
  border: 1px solid rgba(58, 236, 255, 0.22);
  background: rgba(255, 255, 255, 0.04);
  color: var(--text);
  text-decoration: none;
  font-weight: 700;
  font-size: 0.88rem;
  transition: transform 0.15s ease, border-color 0.15s ease, background 0.15s ease;
}

.actions a:hover {
  transform: translateY(-1px);
  border-color: var(--accent);
  background: rgba(58, 236, 255, 0.08);
}

.actions a.primary {
  border-color: rgba(255, 63, 181, 0.34);
  background: linear-gradient(90deg, rgba(58, 236, 255, 0.18), rgba(255, 63, 181, 0.16));
}

.overview {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  padding: 18px;
}

.metric {
  border-radius: 18px;
  padding: 16px 14px;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.04), rgba(255, 255, 255, 0.02));
  border: 1px solid rgba(255, 255, 255, 0.08);
}

.metric strong {
  display: block;
  color: var(--muted);
  font-size: 0.72rem;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  margin-bottom: 6px;
}

.metric span {
  display: block;
  font-size: 1.35rem;
  font-weight: 800;
}

.meta-strip {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin-top: 10px;
}

.meta-cell {
  border-radius: 16px;
  padding: 12px 14px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.06);
}

.meta-cell strong {
  display: block;
  margin-bottom: 5px;
  color: var(--muted);
  font-size: 0.68rem;
  text-transform: uppercase;
  letter-spacing: 0.12em;
}

.meta-cell span {
  display: block;
  font-size: 0.9rem;
  font-weight: 700;
}

.workspace {
  padding: 18px;
}

.tab-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 16px;
}

.tab-btn {
  appearance: none;
  border: 1px solid rgba(255, 255, 255, 0.08);
  background: rgba(255, 255, 255, 0.03);
  color: var(--muted);
  border-radius: 14px;
  padding: 10px 14px;
  font-size: 0.86rem;
  font-weight: 800;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  cursor: pointer;
}

.tab-btn.active {
  color: var(--text);
  border-color: rgba(58, 236, 255, 0.36);
  background: linear-gradient(90deg, rgba(58, 236, 255, 0.12), rgba(255, 63, 181, 0.1));
  box-shadow: inset 0 0 0 1px rgba(58, 236, 255, 0.14);
}

.tab-panel {
  display: none;
  border-radius: 20px;
  padding: 20px;
  background: linear-gradient(180deg, rgba(8, 13, 30, 0.72), rgba(10, 16, 36, 0.84));
  border: 1px solid rgba(58, 236, 255, 0.12);
}

.tab-panel.active {
  display: block;
}

.panel-header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
}

.panel-header h2 {
  margin: 0;
  font-size: 1.3rem;
  letter-spacing: -0.03em;
}

.panel-header span {
  color: var(--muted);
  font-size: 0.88rem;
}

.summary-block {
  white-space: pre-wrap;
  line-height: 1.74;
  font-size: 1rem;
  color: #dfe9ff;
}

.empty {
  padding: 18px;
  border-radius: 16px;
  border: 1px dashed rgba(255, 255, 255, 0.14);
  background: rgba(255, 255, 255, 0.03);
  color: var(--muted);
  font-style: italic;
}

.transcript-table-wrap {
  overflow-x: auto;
}

table {
  width: 100%;
  border-collapse: collapse;
  min-width: 760px;
}

thead th {
  text-align: left;
  font-size: 0.72rem;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  color: var(--muted);
  padding: 0 0 12px;
  border-bottom: 1px solid rgba(58, 236, 255, 0.16);
}

tbody td {
  padding: 14px 0;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  vertical-align: top;
}

tbody tr:last-child td {
  border-bottom: none;
}

.speaker {
  font-weight: 700;
  color: var(--text);
}

.badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 4px 8px;
  border-radius: 999px;
  font-size: 0.68rem;
  font-weight: 800;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.badge.meta {
  color: #ff9bd9;
  background: rgba(255, 63, 181, 0.14);
  border: 1px solid rgba(255, 63, 181, 0.2);
}

.badge.ingame {
  color: #6af5ff;
  background: rgba(58, 236, 255, 0.12);
  border: 1px solid rgba(58, 236, 255, 0.22);
}

.mono {
  font-family: "Consolas", "Courier New", monospace;
  font-size: 0.85rem;
  color: #c7daff;
}

@media (max-width: 960px) {
  .command-deck {
    grid-template-columns: 1fr;
  }

  .masthead-row {
    flex-direction: column;
  }

  .actions {
    justify-content: flex-start;
  }

  .overview,
  .meta-strip {
    grid-template-columns: 1fr;
  }
}
"""


def _sanitize_path_segment(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
    text = text.strip(".-")
    return text or "session"


def _format_epoch(value: Any) -> str:
    if value in (None, ""):
        return "-"
    try:
        dt = datetime.fromtimestamp(float(value))
    except (TypeError, ValueError, OSError):
        return str(value)
    return dt.strftime("%d/%m/%Y %H:%M:%S")


def _display_export_date(dt: datetime) -> str:
    return dt.strftime("%d/%m/%Y")


def _filename_export_date(dt: datetime) -> str:
    return dt.strftime("%d-%m-%Y")


def _timestamp_slug(dt: datetime) -> str:
    return dt.strftime("%H%M%S")


def _normalize_bool(value: Any) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    return ""


def _derive_meta_label(value: Any) -> str:
    if value is True:
        return "In Game"
    if value is False:
        return "Meta"
    return ""


def _derive_is_meta(value: Any) -> str:
    if value is True:
        return "false"
    if value is False:
        return "true"
    return ""


def _render_markdown_document(title: str, session_id: str, export_date: str, body: str) -> str:
    content = body.strip()
    if not content:
        content = "_No disponible en el momento del export._"
    return (
        f"# {title}\n\n"
        f"- Session ID: `{session_id}`\n"
        f"- Export Date: {export_date}\n\n"
        f"{content}\n"
    )


def _csv_text(transcriptions: list[dict[str, Any]]) -> str:
    buf = StringIO()
    writer = csv.DictWriter(
        buf,
        fieldnames=[
            "id",
            "session_id",
            "timestamp",
            "speaker_id",
            "speaker_name",
            "text",
            "is_ingame",
            "is_meta",
            "confidence",
        ],
    )
    writer.writeheader()
    for row in transcriptions:
        is_ingame = row.get("is_ingame")
        writer.writerow(
            {
                "id": row.get("id", ""),
                "session_id": row.get("session_id", ""),
                "timestamp": row.get("timestamp", ""),
                "speaker_id": row.get("speaker_id", ""),
                "speaker_name": row.get("speaker_name", ""),
                "text": row.get("text", ""),
                "is_ingame": _normalize_bool(is_ingame),
                "is_meta": _derive_is_meta(is_ingame),
                "confidence": row.get("confidence", ""),
            }
        )
    return buf.getvalue()


def _render_transcript_rows(transcriptions: list[dict[str, Any]]) -> str:
    if not transcriptions:
        return (
            '<tr><td colspan="5"><div class="empty">No transcriptions were available '
            "for this export.</div></td></tr>"
        )

    rows: list[str] = []
    for row in transcriptions:
        ts_label = _format_epoch(row.get("timestamp"))
        speaker = html.escape(str(row.get("speaker_name", "") or "Unknown"))
        text = html.escape(str(row.get("text", "") or ""))
        confidence = row.get("confidence", "")
        badge_label = _derive_meta_label(row.get("is_ingame"))
        badge_html = ""
        if badge_label:
            badge_class = "ingame" if badge_label == "In Game" else "meta"
            badge_html = f'<span class="badge {badge_class}">{html.escape(badge_label)}</span>'
        rows.append(
            "<tr>"
            f'<td class="mono">{html.escape(ts_label)}</td>'
            f'<td><span class="speaker">{speaker}</span></td>'
            f"<td>{badge_html}</td>"
            f"<td>{text}</td>"
            f'<td class="mono">{html.escape(str(confidence))}</td>'
            "</tr>"
        )
    return "".join(rows)


def _render_summary_block(text: str) -> str:
    if text.strip():
        return f'<div class="summary-block">{html.escape(text)}</div>'
    return '<div class="empty">No content was available for this section at export time.</div>'


def _count_unique_speakers(transcriptions: list[dict[str, Any]]) -> int:
    return len(
        {
            str(row.get("speaker_name", "")).strip().casefold()
            for row in transcriptions
            if str(row.get("speaker_name", "")).strip()
        }
    )


def _count_meta_lines(transcriptions: list[dict[str, Any]]) -> int:
    return sum(1 for row in transcriptions if row.get("is_ingame") is False)


def _render_html(
    *,
    session_id: str,
    export_date: str,
    session_started_at: str,
    session_ended_at: str,
    status: str,
    session_summary: str,
    session_chronology: str,
    transcriptions: list[dict[str, Any]],
) -> str:
    line_count = len(transcriptions)
    speaker_count = _count_unique_speakers(transcriptions)
    meta_count = _count_meta_lines(transcriptions)
    transcript_rows = _render_transcript_rows(transcriptions)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Session Export</title>
  <link rel="stylesheet" href="./export.css" />
</head>
<body>
  <div class="shell">
    <div class="command-deck">
      <section class="panel masthead">
        <div class="eyebrow">Neural Archive</div>
        <div class="masthead-row">
          <div class="masthead-copy">
            <h1>Session Export</h1>
            <p>Compact offline bundle with summary, chronology and full transcript, styled for fast review instead of raw archive browsing.</p>
            <div class="session-chip">Session <code>{html.escape(session_id)}</code></div>
          </div>
          <div class="actions">
            <a class="primary" href="./index.html">Overview</a>
            <a href="./transcriptions.csv">CSV</a>
            <a href="./session-summary.md">Summary</a>
            <a href="./session-chronology.md">Chronology</a>
          </div>
        </div>
      </section>

      <section class="panel overview">
        <div class="metric"><strong>Lines</strong><span>{line_count}</span></div>
        <div class="metric"><strong>Speakers</strong><span>{speaker_count}</span></div>
        <div class="metric"><strong>Meta</strong><span>{meta_count}</span></div>
        <div class="meta-strip" style="grid-column: 1 / -1;">
          <div class="meta-cell"><strong>Export Date</strong><span>{html.escape(export_date)}</span></div>
          <div class="meta-cell"><strong>Session Start</strong><span>{html.escape(session_started_at)}</span></div>
          <div class="meta-cell"><strong>Status</strong><span>{html.escape(status or "-")}</span></div>
        </div>
      </section>
    </div>

    <section class="panel workspace">
      <div class="tab-bar">
        <button class="tab-btn active" type="button" data-tab="summary">Narrative</button>
        <button class="tab-btn" type="button" data-tab="chronology">Chronology</button>
        <button class="tab-btn" type="button" data-tab="transcript">Transcriptions</button>
      </div>

      <section class="tab-panel active" data-panel="summary">
        <div class="panel-header">
          <h2>Narrative Summary</h2>
          <span>Stored session summary</span>
        </div>
        {_render_summary_block(session_summary)}
      </section>

      <section class="tab-panel" data-panel="chronology">
        <div class="panel-header">
          <h2>Chronology</h2>
          <span>Ordered recap of the session</span>
        </div>
        {_render_summary_block(session_chronology)}
      </section>

      <section class="tab-panel" data-panel="transcript">
        <div class="panel-header">
          <h2>Transcriptions</h2>
          <span>Rendered snapshot of the exported CSV</span>
        </div>
        <div class="transcript-table-wrap">
          <table>
            <thead>
              <tr>
                <th>Timestamp</th>
                <th>Speaker</th>
                <th>Kind</th>
                <th>Text</th>
                <th>Confidence</th>
              </tr>
            </thead>
            <tbody>{transcript_rows}</tbody>
          </table>
        </div>
      </section>
    </section>
  </div>
  <script>
    (function () {{
      var buttons = document.querySelectorAll(".tab-btn");
      var panels = document.querySelectorAll(".tab-panel");
      function activateTab(name) {{
        buttons.forEach(function (button) {{
          button.classList.toggle("active", button.getAttribute("data-tab") === name);
        }});
        panels.forEach(function (panel) {{
          panel.classList.toggle("active", panel.getAttribute("data-panel") === name);
        }});
      }}
      buttons.forEach(function (button) {{
        button.addEventListener("click", function () {{
          activateTab(button.getAttribute("data-tab"));
        }});
      }});
    }})();
  </script>
</body>
</html>
"""


@dataclass
class SessionExportData:
    """Normalized data needed to render an export bundle."""

    session_id: str
    transcriptions: list[dict[str, Any]]
    session_summary: str
    session_chronology: str
    started_at: Any = ""
    ended_at: Any = ""
    status: str = ""


class SessionExportService:
    """Builds and lists immutable session export bundles."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _session_prefix(self, session_id: str) -> str:
        return f"session-export-{_sanitize_path_segment(session_id)}-"

    def _next_export_path(self, session_id: str, now: datetime) -> tuple[str, Path]:
        root = self._root

        date_part = _filename_export_date(now)
        time_part = _timestamp_slug(now)
        base_export_id = f"export-{date_part}-{time_part}"
        export_id = base_export_id
        index = 1
        while (root / f"{self._session_prefix(session_id)}{export_id.replace('export-', '')}.zip").exists():
            export_id = f"{base_export_id}-{index:02d}"
            index += 1

        zip_name = f"{self._session_prefix(session_id)}{export_id.replace('export-', '')}.zip"
        zip_path = root / zip_name
        return zip_name, zip_path

    def build_export(self, data: SessionExportData) -> dict[str, Any]:
        now = datetime.now()
        export_date_display = _display_export_date(now)
        zip_name, zip_path = self._next_export_path(data.session_id, now)
        export_id = zip_path.stem

        with tempfile.TemporaryDirectory(prefix="rpg-export-", dir=str(self._root)) as tmp_dir:
            temp_root = Path(tmp_dir)
            csv_path = temp_root / "transcriptions.csv"
            summary_path = temp_root / "session-summary.md"
            chronology_path = temp_root / "session-chronology.md"
            html_path = temp_root / "index.html"
            css_path = temp_root / "export.css"

            csv_path.write_text(_csv_text(data.transcriptions), encoding="utf-8", newline="")
            summary_path.write_text(
                _render_markdown_document(
                    "Session Summary",
                    data.session_id,
                    export_date_display,
                    data.session_summary,
                ),
                encoding="utf-8",
            )
            chronology_path.write_text(
                _render_markdown_document(
                    "Session Chronology",
                    data.session_id,
                    export_date_display,
                    data.session_chronology,
                ),
                encoding="utf-8",
            )
            html_path.write_text(
                _render_html(
                    session_id=data.session_id,
                    export_date=export_date_display,
                    session_started_at=_format_epoch(data.started_at),
                    session_ended_at=_format_epoch(data.ended_at),
                    status=data.status,
                    session_summary=data.session_summary,
                    session_chronology=data.session_chronology,
                    transcriptions=data.transcriptions,
                ),
                encoding="utf-8",
            )
            css_path.write_text(_EXPORT_CSS, encoding="utf-8")

            with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                for path in sorted(temp_root.iterdir()):
                    zf.write(path, arcname=path.name)

        return {
            "session_id": data.session_id,
            "export_id": export_id,
            "created_at": now.isoformat(),
            "display_date": export_date_display,
            "status": data.status,
            "export_dir": str(self._root),
            "zip_path": str(zip_path),
            "zip_name": zip_name,
            "files": [
                "transcriptions.csv",
                "session-summary.md",
                "session-chronology.md",
                "index.html",
                "export.css",
            ],
        }

    def list_exports(self, session_id: str) -> list[dict[str, Any]]:
        exports: list[dict[str, Any]] = []
        prefix = self._session_prefix(session_id)
        for zip_path in self._root.glob(f"{prefix}*.zip"):
            if not zip_path.is_file():
                continue
            created = datetime.fromtimestamp(zip_path.stat().st_mtime)
            exports.append(
                {
                    "session_id": session_id,
                    "export_id": zip_path.stem,
                    "created_at": created.isoformat(),
                    "display_date": _display_export_date(created),
                    "status": "",
                    "zip_name": zip_path.name,
                    "zip_path": str(zip_path),
                    "files": [
                        "transcriptions.csv",
                        "session-summary.md",
                        "session-chronology.md",
                        "index.html",
                        "export.css",
                    ],
                }
            )

        exports.sort(key=lambda item: str(item.get("created_at", "")), reverse=True)
        return exports

    def get_export_zip(self, session_id: str, export_id: str) -> Path | None:
        if not export_id.strip():
            return None
        export_name = f"{export_id}.zip"
        zip_path = (self._root / export_name).resolve()
        if self._root not in zip_path.parents or not zip_path.is_file():
            return None
        if not zip_path.name.startswith(self._session_prefix(session_id)):
            return None
        return zip_path

    def clear_session_exports(self, session_id: str) -> None:
        """Test helper to remove all ZIP exports for one session."""
        prefix = self._session_prefix(session_id)
        for zip_path in self._root.glob(f"{prefix}*.zip"):
            if zip_path.is_file():
                zip_path.unlink()

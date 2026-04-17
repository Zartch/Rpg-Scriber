"""Campaign export bundle generation for the browse UI."""

from __future__ import annotations

import json
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from rpg_scribe.services.export_service import (
    _csv_text,
    _display_export_date,
    _filename_export_date,
    _format_epoch,
    _render_markdown_document,
    _sanitize_path_segment,
    _timestamp_slug,
)


@dataclass
class CampaignExportSessionData:
    session_id: str
    title: str
    started_at: Any
    ended_at: Any
    status: str
    session_summary: str
    session_chronology: str
    transcriptions: list[dict[str, Any]]


@dataclass
class CampaignExportData:
    campaign_id: str
    name: str
    game_system: str
    language: str
    description: str
    campaign_summary: str
    dm_speaker_id: str
    players: list[dict[str, Any]]
    npcs: list[dict[str, Any]]
    locations: list[dict[str, Any]]
    entities: list[dict[str, Any]]
    relationship_types: list[dict[str, Any]]
    relationships: list[dict[str, Any]]
    merged_npcs_by_parent: dict[str, list[dict[str, Any]]]
    merged_locations_by_parent: dict[str, list[dict[str, Any]]]
    merged_entities_by_parent: dict[str, list[dict[str, Any]]]
    sessions: list[CampaignExportSessionData]


class CampaignExportService:
    """Builds and lists immutable campaign export bundles."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _campaign_prefix(self, campaign_id: str) -> str:
        return f"campaign-export-{_sanitize_path_segment(campaign_id)}-"

    def _assets_root(self) -> Path:
        return Path(__file__).resolve().parent

    def _static_root(self) -> Path:
        return Path(__file__).resolve().parents[1] / "web" / "static"

    def _next_export_path(
        self, campaign_name: str, campaign_id: str, now: datetime
    ) -> tuple[str, Path]:
        root = self._root
        date_part = _filename_export_date(now)
        time_part = _timestamp_slug(now)
        base_export_id = f"export-{date_part}-{time_part}"
        export_id = base_export_id
        index = 1
        while any(
            root.glob(
                f"*{self._campaign_prefix(campaign_id)}{export_id.replace('export-', '')}.zip"
            )
        ):
            export_id = f"{base_export_id}-{index:02d}"
            index += 1

        safe_name = _sanitize_path_segment(campaign_name) if campaign_name else "campaign"
        zip_name = (
            f"{safe_name}-{self._campaign_prefix(campaign_id)}"
            f"{export_id.replace('export-', '')}.zip"
        )
        return zip_name, root / zip_name

    def _campaign_export_css(self) -> str:
        static_root = self._static_root()
        css_parts = []
        for rel_path in [
            "css/variables.css",
            "css/layout.css",
            "css/components.css",
            "css/features/campaign.css",
            "css/features/entities.css",
            "css/features/relationships.css",
            "css/features/summary.css",
        ]:
            css_parts.append((static_root / rel_path).read_text(encoding="utf-8"))
        css_parts.append(
            (self._assets_root() / "campaign_export_template.css").read_text(
                encoding="utf-8"
            )
        )
        return "\n".join(css_parts)

    def _classic_utils_js(self) -> str:
        source = (
            self._static_root() / "js" / "utils.js"
        ).read_text(encoding="utf-8")
        lines = []
        globals_to_export: list[str] = []
        for line in source.splitlines():
            if line.startswith("export function "):
                name = line[len("export function "):].split("(", 1)[0].strip()
                globals_to_export.append(name)
                lines.append(line.replace("export function ", "function ", 1))
            else:
                lines.append(line)
        lines.append("")
        lines.append("(function () {")
        for name in globals_to_export:
            lines.append(f"  window.{name} = {name};")
        lines.append("})();")
        lines.append("")
        return "\n".join(lines)

    def _classic_graph_js(self) -> str:
        source = (
            self._static_root() / "js" / "relationships" / "graph-3d.js"
        ).read_text(encoding="utf-8")
        lines = []
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith("import "):
                continue
            if stripped.startswith("export "):
                continue
            lines.append(line)
        lines.append("")
        lines.append("window.createRelationshipGraph3D = createRelationshipGraph3D;")
        lines.append("")
        return "\n".join(lines)

    def _json_text(self, payload: dict[str, Any], *, pretty: bool) -> str:
        if pretty:
            return json.dumps(payload, ensure_ascii=False, indent=2)
        return json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")

    def _duration_minutes(self, started_at: Any, ended_at: Any) -> float | None:
        if started_at in (None, "") or ended_at in (None, ""):
            return None
        try:
            return round((float(ended_at) - float(started_at)) / 60, 1)
        except (TypeError, ValueError):
            return None

    def _summary_preview(self, text: str, limit: int = 150) -> str:
        preview = text[:limit]
        if len(text) > limit:
            preview += "..."
        return preview

    def _kind_label(self, is_ingame: Any) -> str:
        if is_ingame is True:
            return "In Game"
        if is_ingame is False:
            return "Meta"
        return ""

    def _campaign_markdown_document(
        self,
        title: str,
        campaign_id: str,
        export_date: str,
        body: str,
    ) -> str:
        content = body.strip() or "_Not available at export time._"
        return (
            f"# {title}\n\n"
            f"- Campaign ID: `{campaign_id}`\n"
            f"- Export Date: {export_date}\n\n"
            f"{content}\n"
        )

    def build_export(self, data: CampaignExportData) -> dict[str, Any]:
        now = datetime.now()
        export_date_display = _display_export_date(now)
        zip_name, zip_path = self._next_export_path(data.name, data.campaign_id, now)
        export_id = zip_path.stem

        with tempfile.TemporaryDirectory(
            prefix="rpg-campaign-export-", dir=str(self._root)
        ) as tmp_dir:
            temp_root = Path(tmp_dir)
            assets_dir = temp_root / "assets"
            data_dir = temp_root / "data"
            sessions_dir = data_dir / "sessions"
            assets_dir.mkdir(parents=True, exist_ok=True)
            sessions_dir.mkdir(parents=True, exist_ok=True)

            assets_root = self._assets_root()
            (assets_dir / "export.css").write_text(
                self._campaign_export_css(),
                encoding="utf-8",
            )
            (assets_dir / "export.js").write_text(
                (assets_root / "campaign_export_template.js").read_text(
                    encoding="utf-8"
                ),
                encoding="utf-8",
            )
            (assets_dir / "utils.js").write_text(
                self._classic_utils_js(),
                encoding="utf-8",
            )
            (assets_dir / "graph-3d.js").write_text(
                self._classic_graph_js(),
                encoding="utf-8",
            )

            sessions_index: list[dict[str, Any]] = []
            session_payloads: dict[str, Any] = {}
            for session in data.sessions:
                session_dir_name = _sanitize_path_segment(session.session_id)
                session_dir = sessions_dir / session_dir_name
                session_dir.mkdir(parents=True, exist_ok=True)
                transcript_path = session_dir / "transcript.csv"
                summary_path = session_dir / "summary.md"
                chronology_path = session_dir / "chronology.md"

                transcript_path.write_text(
                    _csv_text(session.transcriptions),
                    encoding="utf-8",
                    newline="",
                )
                summary_path.write_text(
                    _render_markdown_document(
                        "Session Summary",
                        session.session_id,
                        export_date_display,
                        session.session_summary,
                    ),
                    encoding="utf-8",
                )
                chronology_path.write_text(
                    _render_markdown_document(
                        "Session Chronology",
                        session.session_id,
                        export_date_display,
                        session.session_chronology,
                    ),
                    encoding="utf-8",
                )

                duration = self._duration_minutes(session.started_at, session.ended_at)
                session_index = {
                    "id": session.session_id,
                    "title": session.title,
                    "started_at": session.started_at,
                    "ended_at": session.ended_at,
                    "duration_minutes": duration,
                    "status": session.status,
                    "summary_preview": self._summary_preview(
                        session.session_summary or ""
                    ),
                    "has_summary": bool((session.session_summary or "").strip()),
                    "files": {
                        "transcript_csv": f"./data/sessions/{session_dir_name}/transcript.csv",
                        "summary_md": f"./data/sessions/{session_dir_name}/summary.md",
                        "chronology_md": f"./data/sessions/{session_dir_name}/chronology.md",
                    },
                }
                sessions_index.append(session_index)
                session_payloads[session.session_id] = {
                    **session_index,
                    "session_summary": session.session_summary,
                    "session_chronology": session.session_chronology,
                    "transcriptions": [
                        {
                            **row,
                            "timestamp_label": _format_epoch(row.get("timestamp")),
                            "kind_label": self._kind_label(row.get("is_ingame")),
                        }
                        for row in session.transcriptions
                    ],
                }

            campaign_json = {
                "id": data.campaign_id,
                "name": data.name,
                "game_system": data.game_system,
                "language": data.language,
                "description": data.description,
                "campaign_summary": data.campaign_summary,
                "dm_speaker_id": data.dm_speaker_id,
                "players": data.players,
                "npcs": data.npcs,
                "locations": data.locations,
                "entities": data.entities,
                "relationship_types": data.relationship_types,
                "relationships": data.relationships,
                "merged_npcs_by_parent": data.merged_npcs_by_parent,
                "merged_locations_by_parent": data.merged_locations_by_parent,
                "merged_entities_by_parent": data.merged_entities_by_parent,
                "sessions": sessions_index,
            }
            (data_dir / "campaign.json").write_text(
                self._json_text(campaign_json, pretty=True),
                encoding="utf-8",
            )
            (data_dir / "campaign-summary.md").write_text(
                self._campaign_markdown_document(
                    "Campaign Summary",
                    data.campaign_id,
                    export_date_display,
                    data.campaign_summary,
                ),
                encoding="utf-8",
            )
            (sessions_dir / "index.json").write_text(
                self._json_text({"sessions": sessions_index}, pretty=True),
                encoding="utf-8",
            )

            html_payload = {
                "export_date": export_date_display,
                "generated_at": now.isoformat(),
                "campaign": campaign_json,
                "sessions": sessions_index,
                "session_payloads": session_payloads,
            }
            html_template = (assets_root / "campaign_export_template.html").read_text(
                encoding="utf-8"
            )
            (temp_root / "index.html").write_text(
                html_template.replace(
                    "__PAYLOAD__", self._json_text(html_payload, pretty=False)
                ),
                encoding="utf-8",
            )

            with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                for path in sorted(temp_root.rglob("*")):
                    if path.is_file():
                        zf.write(path, arcname=path.relative_to(temp_root).as_posix())

        return {
            "campaign_id": data.campaign_id,
            "export_id": export_id,
            "created_at": now.isoformat(),
            "display_date": export_date_display,
            "zip_name": zip_name,
            "zip_path": str(zip_path),
            "files": [
                "index.html",
                "assets/export.css",
                "assets/export.js",
                "data/campaign.json",
                "data/campaign-summary.md",
                "data/sessions/index.json",
            ],
        }

    def list_exports(self, campaign_id: str) -> list[dict[str, Any]]:
        exports: list[dict[str, Any]] = []
        prefix = self._campaign_prefix(campaign_id)
        for zip_path in self._root.glob(f"*{prefix}*.zip"):
            if not zip_path.is_file():
                continue
            created = datetime.fromtimestamp(zip_path.stat().st_mtime)
            exports.append(
                {
                    "campaign_id": campaign_id,
                    "export_id": zip_path.stem,
                    "created_at": created.isoformat(),
                    "display_date": _display_export_date(created),
                    "zip_name": zip_path.name,
                    "zip_path": str(zip_path),
                    "files": [
                        "index.html",
                        "assets/export.css",
                        "assets/export.js",
                        "data/campaign.json",
                        "data/campaign-summary.md",
                        "data/sessions/index.json",
                    ],
                }
            )
        exports.sort(key=lambda item: str(item.get("created_at", "")), reverse=True)
        return exports

    def get_export_zip(self, campaign_id: str, export_id: str) -> Path | None:
        if not export_id.strip():
            return None
        zip_path = (self._root / f"{export_id}.zip").resolve()
        if self._root not in zip_path.parents or not zip_path.is_file():
            return None
        if self._campaign_prefix(campaign_id) not in zip_path.name:
            return None
        return zip_path

"""rag_lib CLI (argparse). Commands: ingest, list, delete, show."""
from __future__ import annotations

import argparse
import asyncio
import sys

import rag_lib


def _build_parser() -> argparse.ArgumentParser:
    db_parent = argparse.ArgumentParser(add_help=False)
    db_parent.add_argument("--db", default="data/rag.db", metavar="PATH", help="SQLite DB path")

    parser = argparse.ArgumentParser(prog="rag_lib", description="RAG Library CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_ingest = sub.add_parser("ingest", parents=[db_parent], help="Ingest a PDF into the RAG index")
    p_ingest.add_argument("pdf", help="Path to the PDF file")
    p_ingest.add_argument("--name", required=True, help="Human-readable name for this manual")

    sub.add_parser("list", parents=[db_parent], help="List all ingested manuals")

    p_del = sub.add_parser("delete", parents=[db_parent], help="Delete a manual and its chunks")
    p_del.add_argument("manual_id", type=int)

    p_show = sub.add_parser("show", parents=[db_parent], help="Show chunks of a manual")
    p_show.add_argument("manual_id", type=int)
    p_show.add_argument("--page", type=int, default=None, help="Filter by page number")
    p_show.add_argument("--limit", type=int, default=20)

    return parser


def main() -> None:
    args = _build_parser().parse_args()
    try:
        asyncio.run(_dispatch(args))
    except KeyboardInterrupt:
        sys.exit(0)


async def _dispatch(args: argparse.Namespace) -> None:
    if args.cmd == "ingest":
        result = await rag_lib.ingest_pdf(args.pdf, manual_name=args.name, db_path=args.db)
        if result.was_already_ingested:
            print(f"Already ingested as manual_id={result.manual_id} (same SHA256). No changes.")
        else:
            print(f"Ingested {result.chunks_created} chunks as manual_id={result.manual_id}.")

    elif args.cmd == "list":
        manuals = await rag_lib.list_manuals(db_path=args.db)
        if not manuals:
            print("No manuals ingested yet.")
            return
        print(f"{'ID':<4} {'Name':<30} {'Pages':>6} {'Chunks':>7} {'Size':>10}  Ingested")
        print("-" * 70)
        for m in manuals:
            size_mb = m.file_size / 1_000_000
            print(f"{m.id:<4} {m.name:<30} {m.page_count:>6} {m.chunk_count:>7} {size_mb:>9.1f}M  {m.ingested_at[:19]}")

    elif args.cmd == "delete":
        deleted = await rag_lib.delete_manual(args.manual_id, db_path=args.db)
        if deleted:
            print(f"Deleted manual_id={args.manual_id}.")
        else:
            print(f"Error: manual_id={args.manual_id} not found.", file=sys.stderr)
            sys.exit(1)

    elif args.cmd == "show":
        chunks = await rag_lib.list_chunks(args.manual_id, db_path=args.db, limit=args.limit)
        if args.page is not None:
            chunks = [c for c in chunks if c.page == args.page]
        if not chunks:
            print("No chunks found.")
            return
        for c in chunks:
            page_str = f"p.{c.page}" + (f"-{c.page_end}" if c.page_end else "")
            sp = f"[{c.section_path}]" if c.section_path else ""
            preview = c.text[:80].replace("\n", " ")
            print(f"  #{c.seq:<4} {page_str:<6} {c.chunk_type:<6} {sp:<30} {preview!r} ({c.token_count} tok)")

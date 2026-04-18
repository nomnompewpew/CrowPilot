"""
services/zim_indexer.py — ZIM file indexing for the Project Nomad integration.

Reads a ZIM archive (Kiwix/Wikipedia format), strips article HTML to plain
text, chunks it, and feeds everything into the BACKGROUND embed queue so
it ends up in memory_chunks for semantic search.

Indexing is deliberately slow and polite: it yields to the asyncio event
loop between batches so the server stays responsive during long runs.
Setting overnight mode (set_overnight_mode(True)) allows the embed worker
to drain without inter-job delays, which is the right approach for a 28GB
Wikipedia ZIM running overnight.
"""
from __future__ import annotations

import asyncio
import logging
from html.parser import HTMLParser
from pathlib import Path

from ..chunking import split_into_chunks
from ..config import settings
from ..services.memory import enqueue_message, BACKGROUND
from ..state import g

log = logging.getLogger(__name__)


# ── HTML stripping ─────────────────────────────────────────────────────────────

_SKIP_TAGS = frozenset({"script", "style", "nav", "header", "footer", "sup", "figure"})


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._skip_depth: int = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            stripped = data.strip()
            if stripped:
                self._parts.append(stripped)

    def get_text(self) -> str:
        return " ".join(self._parts)


def _strip_html(html: str) -> str:
    extractor = _TextExtractor()
    try:
        extractor.feed(html)
    except Exception:
        pass
    return " ".join(extractor.get_text().split())


# ── Core indexer ───────────────────────────────────────────────────────────────

_ARTICLE_BATCH = 50   # articles per batch before yielding to event loop
_MIN_TEXT_LEN = 100   # skip stubs shorter than this after HTML stripping


async def index_zim_file(zim_file_id: int, zim_path: str) -> None:
    """
    Background coroutine: walk a ZIM archive and enqueue all article text as
    BACKGROUND-priority embed jobs.

    Intended to run as an asyncio task spawned by the nomad router. Progress
    and status are persisted to the zim_files row so the UI can poll it.
    """
    try:
        import libzim
    except ImportError:
        _fail(zim_file_id, "libzim not installed — run: pip install libzim")
        return

    try:
        archive = libzim.Archive(zim_path)
    except Exception as exc:
        _fail(zim_file_id, f"Cannot open ZIM file: {exc}")
        return

    searcher = libzim.Searcher(archive)
    query = libzim.Query().set_query("")
    search = searcher.search(query)
    total = search.getEstimatedMatches()

    if total == 0:
        # Fall back: some ZIM files without full-text index still have articles
        # accessible by path. Mark as indexed with 0 to indicate empty or
        # non-searchable archive.
        _mark_done(zim_file_id, 0)
        return

    # Store article count estimate
    g.db.execute(
        "UPDATE zim_files SET article_count = ?, status = 'indexing', updated_at = datetime('now') WHERE id = ?",
        (total, zim_file_id),
    )
    g.db.commit()

    chunk_counter = 0   # global chunk index within this ZIM file
    article_count = 0
    offset = 0

    log.info("ZIM indexer: starting %s (%d estimated articles)", zim_path, total)

    while offset < total:
        batch_size = min(_ARTICLE_BATCH, total - offset)
        result_set = search.getResults(offset, batch_size)
        offset += batch_size

        for path in result_set:
            try:
                entry = archive.get_entry_by_path(path)
                if entry.is_redirect():
                    continue
                item = entry.get_item()
                if "html" not in item.mimetype.lower():
                    continue

                raw_html = bytes(item.content).decode("utf-8", errors="ignore")
                text = _strip_html(raw_html)
                if len(text) < _MIN_TEXT_LEN:
                    continue

                title = entry.title or path
                labelled_text = f"{title}\n{text}"
                chunks = split_into_chunks(
                    labelled_text,
                    settings.chunk_size,
                    settings.chunk_overlap,
                )
                for chunk in chunks:
                    enqueue_message(chunk, "zim", zim_file_id, chunk_counter, BACKGROUND)
                    chunk_counter += 1

                article_count += 1
            except Exception as exc:
                log.debug("ZIM indexer: skipping %s — %s", path, exc)
                continue

        # Persist progress and yield to event loop
        g.db.execute(
            "UPDATE zim_files SET indexed_chunks = ?, updated_at = datetime('now') WHERE id = ?",
            (chunk_counter, zim_file_id),
        )
        g.db.commit()
        await asyncio.sleep(0)

    _mark_done(zim_file_id, article_count)
    log.info("ZIM indexer: finished %s — %d articles, %d chunks", zim_path, article_count, chunk_counter)


def _fail(zim_file_id: int, error: str) -> None:
    log.error("ZIM indexer: %s", error)
    g.db.execute(
        "UPDATE zim_files SET status = 'error', last_error = ?, updated_at = datetime('now') WHERE id = ?",
        (error, zim_file_id),
    )
    g.db.commit()


def _mark_done(zim_file_id: int, article_count: int) -> None:
    g.db.execute(
        """UPDATE zim_files
           SET status = 'indexed', article_count = ?, updated_at = datetime('now')
           WHERE id = ?""",
        (article_count, zim_file_id),
    )
    g.db.commit()

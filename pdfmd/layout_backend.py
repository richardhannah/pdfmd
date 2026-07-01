"""High-quality layout/table extraction backend (optional, non-commercial).

Wraps ``pymupdf4llm`` + ``pymupdf-layout`` to produce Markdown with proper
reading order and reconstructed tables. On dense, multi-column, borderless-table
layouts — the BECMI-era D&D sourcebooks this fork targets — it is dramatically
better than the native pipeline, which linearises such pages and destroys their
table structure.

LICENSING — READ THIS. ``pymupdf-layout`` is dual-licensed **Polyform
Noncommercial** / Artifex Commercial. This backend is opt-in (the ``[layout]``
extra) precisely because of that restriction. Do **not** use it for commercial
purposes without an Artifex commercial license. The native backend has no such
restriction.
"""
from __future__ import annotations

from typing import Callable, List, Optional

from .models import Options
from .extract import _open_pdf_with_password


def layout_available() -> bool:
    """True when the optional layout backend dependencies are importable."""
    try:
        import pymupdf4llm  # noqa: F401

        return True
    except Exception:
        return False


def render_with_layout(
    input_pdf: str,
    options: Options,
    log_cb: Optional[Callable[[str], None]] = None,
    pdf_password: Optional[str] = None,
) -> str:
    """Convert a PDF to Markdown via pymupdf4llm + pymupdf-layout.

    Honors ``options.preview_only`` (first 3 pages) and ``options.insert_page_breaks``.
    Raises ``RuntimeError`` with an install hint if the extra is missing.
    """
    try:
        import pymupdf4llm
    except Exception as e:  # optional dependency not installed
        raise RuntimeError(
            "The 'layout' backend requires the optional layout extra "
            "(pymupdf4llm + pymupdf-layout). Install it — non-commercial use "
            "only — with: pip install .[layout]"
        ) from e

    # Password-aware open, shared with the native path so behavior matches.
    doc = _open_pdf_with_password(input_pdf, pdf_password)
    try:
        pages: Optional[List[int]] = None
        if options.preview_only:
            pages = list(range(min(3, doc.page_count)))

        if log_cb:
            log_cb("[layout] Running pymupdf4llm + layout analysis…")

        if options.insert_page_breaks:
            chunks = pymupdf4llm.to_markdown(doc, pages=pages, page_chunks=True)
            md = "\n\n---\n\n".join(
                (c.get("text", "") if isinstance(c, dict) else str(c)).strip()
                for c in chunks
            )
        else:
            md = pymupdf4llm.to_markdown(doc, pages=pages)

        return md if md.endswith("\n") else md + "\n"
    finally:
        doc.close()


__all__ = ["layout_available", "render_with_layout"]

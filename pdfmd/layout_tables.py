"""Coordinate-aware, column-isolated table extraction for pdfmd.

The default pdfmd pipeline flattens each page to a linear text model, which
destroys the 2-D structure of *borderless* tables — the norm in BECMI-era
D&D sourcebooks (e.g. the Rules Cyclopedia): saving-throw charts, experience
tables, weapon lists, monster stats. Those pages also use a dense 2-3 column
magazine layout, so simply running PyMuPDF's ``find_tables`` on the whole page
mis-reads the prose columns as one giant table.

This module works directly on ``fitz.Page`` geometry instead:

  1. :func:`detect_columns` finds the page's main text columns by locating the
     vertical whitespace gutters between words.
  2. :func:`extract_page_tables` clips ``find_tables(strategy="text")`` to each
     column (so the column layout can't be mistaken for a table), then cleans
     the recovered grids into GitHub-flavored Markdown.

Requires PyMuPDF. Every entry point degrades gracefully (returns ``[]``) when
``fitz`` is unavailable, matching the rest of the codebase.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

try:
    import fitz  # PyMuPDF
except Exception:  # pragma: no cover - matches defensive import elsewhere
    fitz = None


# The Unicode replacement char shows up where a glyph had no ToUnicode mapping
# (common for the spell-slot pip symbols in the Cyclopedia). Drop it rather than
# render a literal box.
_REPLACEMENT = "�"


@dataclass
class ExtractedTable:
    """A table recovered from a page, in reading order.

    ``bbox`` is the table's rectangle on the page (x0, y0, x1, y1) in PDF points;
    the pipeline uses it to place the table relative to surrounding prose and to
    suppress the now-redundant flattened text underneath it.
    """

    bbox: Tuple[float, float, float, float]
    rows: List[List[str]]
    markdown: str

    @property
    def row_count(self) -> int:
        return len(self.rows)

    @property
    def col_count(self) -> int:
        return len(self.rows[0]) if self.rows else 0


def detect_columns(
    page,
    *,
    gutter_min_frac: float = 0.018,
    gutter_min_pts: float = 9.0,
) -> List["fitz.Rect"]:
    """Return the page's main text columns as full-height rectangles.

    Columns are the regions between *gutters* — vertical bands spanning the full
    content height that contain no word ink. A gutter must be at least
    ``max(gutter_min_pts, gutter_min_frac * page_width)`` wide to count, which
    keeps the narrow gaps *inside* a table from being mistaken for column
    breaks while still catching the wide magazine gutters between prose columns.

    Falls back to a single full-page column when there are no words or fitz is
    missing.
    """
    if fitz is None:
        return []

    page_rect = page.rect
    W, H = page_rect.width, page_rect.height

    words = page.get_text("words")  # (x0, y0, x1, y1, word, block, line, wno)
    if not words:
        return [fitz.Rect(0, 0, W, H)]

    content_x0 = min(w[0] for w in words)
    content_x1 = max(w[2] for w in words)
    if content_x1 <= content_x0:
        return [fitz.Rect(0, 0, W, H)]

    # Coverage count per 1-pt bin across the content span.
    span = int(content_x1 - content_x0) + 1
    cover = [0] * (span + 1)
    base = content_x0
    for w in words:
        a = int(w[0] - base)
        b = int(w[2] - base)
        a = max(0, min(a, span))
        b = max(0, min(b, span))
        for x in range(a, b + 1):
            cover[x] += 1

    gutter_min = max(gutter_min_pts, gutter_min_frac * W)

    # Walk the coverage array collecting maximal zero runs => candidate gutters.
    boundaries: List[float] = [content_x0]
    run_start: Optional[int] = None
    for x in range(span + 1):
        if cover[x] == 0:
            if run_start is None:
                run_start = x
        else:
            if run_start is not None:
                run_len = x - run_start
                if run_len >= gutter_min:
                    # Column break at the middle of the gutter.
                    boundaries.append(base + (run_start + x) / 2.0)
                run_start = None
    boundaries.append(content_x1)

    cols: List["fitz.Rect"] = []
    for left, right in zip(boundaries[:-1], boundaries[1:]):
        if right - left < gutter_min:  # skip slivers
            continue
        cols.append(fitz.Rect(left, page_rect.y0, right, page_rect.y1))
    return cols or [fitz.Rect(0, 0, W, H)]


def _clean_cell(text: Optional[str]) -> str:
    if not text:
        return ""
    text = text.replace(_REPLACEMENT, "")
    text = text.replace("\n", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _clean_grid(raw_rows: List[List[Optional[str]]]) -> List[List[str]]:
    """Normalise a raw ``Table.extract()`` grid.

    Cleans every cell, pads rows to a common width, then drops columns and rows
    that are empty everywhere (find_tables' text strategy often emits phantom
    all-blank columns between real ones).
    """
    if not raw_rows:
        return []

    grid = [[_clean_cell(c) for c in row] for row in raw_rows]
    width = max((len(r) for r in grid), default=0)
    if width == 0:
        return []
    grid = [r + [""] * (width - len(r)) for r in grid]

    keep_cols = [j for j in range(width) if any(row[j] for row in grid)]
    if not keep_cols:
        return []
    grid = [[row[j] for j in keep_cols] for row in grid]

    grid = [row for row in grid if any(cell for cell in row)]
    return grid


_NUMERIC_RE = re.compile(r"[-+]?[\d][\d,.\-–/*% ]*$")
_DOTLEADER_RE = re.compile(r"\.\s*\.\s*\.")  # ". . ." table-of-contents leaders


def _is_toc_like(grid: List[List[str]]) -> bool:
    """True for table-of-contents / index grids (dot-leader rows)."""
    cells = [c for row in grid for c in row if c]
    if not cells:
        return False
    leaders = sum(1 for c in cells if _DOTLEADER_RE.search(c))
    return leaders / len(cells) >= 0.15


def _looks_tabular(grid: List[List[str]]) -> bool:
    """Discriminate a real table from prose the text-finder mis-gridded.

    The text strategy splits multi-column *prose* into fake cells at incidental
    word alignments (e.g. ``and gain | s 1d6 more...``). Genuine BECMI rules
    tables, by contrast, are dominated by short, often numeric tokens. We accept
    a grid when it is numeric enough, or when its cells are short and rarely
    multi-word; we reject long, spacey, non-numeric grids (prose).
    """
    # Judge by the body: header/title rows are reliably messy (spanned, split)
    # and would otherwise mask an obviously-tabular numeric body.
    body = grid[1:] if len(grid) > 3 else grid
    cells = [c for row in body for c in row if c]
    if not cells:
        return False
    n = len(cells)
    numeric = sum(1 for c in cells if _NUMERIC_RE.match(c))
    multiword = sum(1 for c in cells if " " in c)
    mean_len = sum(len(c) for c in cells) / n

    numeric_frac = numeric / n
    multiword_frac = multiword / n

    # Prose fragments are long and spacey; bail early even if some cells are numeric.
    if multiword_frac >= 0.45 or mean_len >= 14.0:
        return False
    if numeric_frac >= 0.35:
        return True
    if mean_len <= 7.0 and multiword_frac <= 0.25:
        return True
    return False


def _column_boundaries(tab) -> List[float]:
    """Internal column separator x-positions from a table's cell geometry."""
    xs = sorted({round(c[0], 1) for c in tab.cells if c})
    return xs[1:]  # drop the left edge; keep internal separators


def _straddle_frac(words, tab, boundaries: List[float], tol: float = 1.0) -> float:
    """Fraction of a table's words that a column boundary cuts through.

    A clean table's separators fall in whitespace, so ~no word straddles them.
    Prose that the text-finder mis-gridded splits words across the fake columns,
    so many words straddle. This is the strongest real-table vs prose signal and
    works for textual tables (weapon/spell/monster lists) that a numeric test
    would wrongly reject.
    """
    if not boundaries:
        return 1.0
    x0, y0, x1, y1 = tab.bbox
    in_table = [
        w for w in words
        if w[0] >= x0 - tol and w[2] <= x1 + tol and w[1] >= y0 - tol and w[3] <= y1 + tol
    ]
    if not in_table:
        return 1.0
    straddlers = 0
    for w in in_table:
        wx0, wx1 = w[0], w[2]
        if any(wx0 < b - tol and wx1 > b + tol for b in boundaries):
            straddlers += 1
    return straddlers / len(in_table)


def _to_markdown(grid: List[List[str]]) -> str:
    """Render a cleaned grid as a GitHub-flavored pipe table (row 0 = header)."""
    def esc(cell: str) -> str:
        return cell.replace("|", "\\|")

    ncols = len(grid[0])
    lines = ["| " + " | ".join(esc(c) for c in grid[0]) + " |"]
    lines.append("| " + " | ".join(["---"] * ncols) + " |")
    for row in grid[1:]:
        lines.append("| " + " | ".join(esc(c) for c in row) + " |")
    return "\n".join(lines)


def extract_page_tables(
    page,
    *,
    min_rows: int = 3,
    min_cols: int = 2,
    max_straddle_frac: float = 0.10,
) -> List[ExtractedTable]:
    """Extract borderless tables from ``page`` in reading order.

    Detects columns, runs the text-strategy table finder clipped to each, cleans
    the grids, and filters out anything too small to be a real table (which also
    discards single-column prose that the finder occasionally reports).

    Returned tables are ordered by column (left-to-right) then vertical position,
    i.e. natural reading order.
    """
    if fitz is None:
        return []

    words = page.get_text("words")
    columns = detect_columns(page)
    results: List[Tuple[float, float, ExtractedTable]] = []

    for col in columns:
        try:
            finder = page.find_tables(
                clip=col,
                vertical_strategy="text",
                horizontal_strategy="text",
            )
        except Exception:
            continue

        for tab in finder.tables:
            grid = _clean_grid(tab.extract())
            if len(grid) < min_rows or (grid and len(grid[0]) < min_cols):
                continue
            if _is_toc_like(grid):  # table-of-contents / index, not a real table
                continue
            # Primary discriminator: do the column separators fall in whitespace?
            # Prose mis-grids cut words; real tables (numeric or textual) don't.
            # Fall back to the numeric/short-cell heuristic if geometry is absent.
            straddle = _straddle_frac(words, tab, _column_boundaries(tab))
            if straddle > max_straddle_frac and not _looks_tabular(grid):
                continue
            bbox = tuple(float(v) for v in tab.bbox)
            table = ExtractedTable(bbox=bbox, rows=grid, markdown=_to_markdown(grid))
            # sort key: column left edge, then table top.
            results.append((col.x0, bbox[1], table))

    results.sort(key=lambda t: (t[0], t[1]))
    return [t[2] for t in results]


__all__ = ["ExtractedTable", "detect_columns", "extract_page_tables"]

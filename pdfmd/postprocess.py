"""Deterministic post-processing of converted Markdown ("tuning").

Runs *before* any LLM cleanup pass. Everything here is mechanical and
reproducible — it adds structure and flags problem areas so a later LLM pass is
cheaper and more reliable, but it never tries to reconstruct data it can't
recover deterministically (fused/picture tables are *flagged*, not rewritten).

Passes (see :func:`apply_tuning`):
  1. normalise chapter headings to a single `#` level (config-driven, exact-title
     match so in-prose "see Chapter 2" references are never promoted)
  2. flag hard cases for the LLM — picture-text blobs and garbled/fused tables get
     a `<!-- NEEDS-RECONSTRUCTION: … -->` marker
  3. collapse excess blank runs
  4. prepend a generated, hyperlinked Contents index built from the headings

Book-specific facts (chapter list, name) come from a TOML tuning file in
``pdfmd/tunings/<name>.toml`` — data, not code, so a new book is a new file.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Dict, List, Optional

try:  # Python 3.11+
    import tomllib as _toml
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11
    try:
        import tomli as _toml  # type: ignore
    except ModuleNotFoundError:  # pragma: no cover
        _toml = None  # type: ignore

_TUNINGS_DIR = Path(__file__).parent / "tunings"

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)


# ------------------------------- tuning files -------------------------------
def available_tunings() -> List[str]:
    if not _TUNINGS_DIR.is_dir():
        return []
    return sorted(p.stem for p in _TUNINGS_DIR.glob("*.toml"))


def load_tuning(name: str) -> Dict:
    """Load a tuning TOML by name (e.g. 'rules-cyclopedia'). Raises on problems."""
    if _toml is None:  # pragma: no cover
        raise RuntimeError(
            "Reading tuning files needs a TOML parser. On Python < 3.11 install it "
            "with: pip install tomli"
        )
    path = _TUNINGS_DIR / f"{name}.toml"
    if not path.is_file():
        avail = ", ".join(available_tunings()) or "(none installed)"
        raise FileNotFoundError(f"Unknown tuning '{name}'. Available: {avail}")
    with path.open("rb") as fh:
        return _toml.load(fh)


# --------------------------------- helpers ---------------------------------
def _clean_heading_text(raw: str) -> str:
    """Strip Markdown emphasis / HTML tags from a heading for display + slugging."""
    t = re.sub(r"<[^>]+>", "", raw)
    t = re.sub(r"[*_`]", "", t)
    return t.strip()


def _norm_title(t: str) -> str:
    """Aggressive normalisation for chapter-title equality tests."""
    return re.sub(r"[^a-z0-9]+", "", t.lower())


def _slug(text: str) -> str:
    """GitHub-style heading anchor slug."""
    s = re.sub(r"<[^>]+>", "", text)
    s = re.sub(r"[*_`]", "", s).strip().lower()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"\s+", "-", s)
    return s


# ------------------------------- pass 1: headings -------------------------------
def _normalize_chapter_headings(md: str, cfg: Dict) -> str:
    """Force every line that *is* a known chapter/appendix title to a single `#`.

    Matches on exact normalised title text, so a chapter title rendered as bold,
    as an h6, or as plain text is promoted, while a mid-sentence reference to the
    same words is left alone.
    """
    chapters = cfg.get("chapters") or []
    if not chapters:
        return md
    # Match ONLY the full title ("Chapter 2: The Character Classes"). Matching the
    # short title ("Movement") was tried and abandoned: common one-word chapter
    # names collide with sub-section headings and inject bogus chapter headings.
    # Reliable chapter/major-section headings are injected by page (option B),
    # using the page anchors this run adds — not by fuzzy body-text matching.
    by_norm = {_norm_title(c["title"]): c["title"] for c in chapters if c.get("title")}

    out: List[str] = []
    for line in md.split("\n"):
        stripped = line.strip()
        # candidate = the line with any leading heading hashes removed
        cand = _clean_heading_text(re.sub(r"^#{1,6}\s*", "", stripped))
        canon = by_norm.get(_norm_title(cand)) if cand else None
        if canon and len(cand) <= 80:
            out.append(f"# {canon}")
        else:
            out.append(line)
    return "\n".join(out)


# ------------------------------- pass 2: flagging -------------------------------
def _flag_hard_cases(md: str) -> str:
    """Mark blocks a later LLM pass must reconstruct; don't rewrite them here."""
    # (a) picture-text blobs: tables the layout engine detected as images.
    md = md.replace(
        "<!-- Start of picture text -->",
        "<!-- NEEDS-RECONSTRUCTION: block below was detected as an image and "
        "dumped as raw text; likely a table to rebuild as a grid. -->",
    )
    md = md.replace("<!-- End of picture text -->", "<!-- END NEEDS-RECONSTRUCTION -->")

    # (b) garbled / fused pipe tables: many in-cell line breaks => columns or
    # adjacent tables have been merged. Flag the block, leave the data intact.
    lines = md.split("\n")
    out: List[str] = []
    i = 0
    while i < len(lines):
        if lines[i].lstrip().startswith("|"):
            j = i
            while j < len(lines) and lines[j].lstrip().startswith("|"):
                j += 1
            block = lines[i:j]
            cells = sum(row.count("|") for row in block)
            brs = sum(len(_BR_RE.findall(row)) for row in block)
            already = i > 0 and "NEEDS-RECONSTRUCTION" in lines[i - 1]
            if not already and cells and brs / cells >= 0.5:
                out.append(
                    "<!-- NEEDS-RECONSTRUCTION: table may be fused/garbled "
                    "(many in-cell line breaks). -->"
                )
            out.extend(block)
            i = j
        else:
            out.append(lines[i])
            i += 1
    return "\n".join(out)


# ------------------------------- pass 3: whitespace -------------------------------
def _collapse_blank_runs(md: str) -> str:
    return re.sub(r"\n{4,}", "\n\n\n", md)


# ------------------------------- pass 4: index -------------------------------
def _build_index(md: str, cfg: Dict) -> str:
    """Prepend a generated, hyperlinked Contents index (levels 1-2)."""
    seen: Dict[str, int] = {}
    entries: List[str] = []
    for line in md.split("\n"):
        m = _HEADING_RE.match(line)
        if not m:
            continue
        level = len(m.group(1))
        if level > 2:
            continue
        text = _clean_heading_text(m.group(2))
        if not text:
            continue
        base = _slug(text)
        n = seen.get(base, 0)
        slug = base if n == 0 else f"{base}-{n}"
        seen[base] = n + 1
        entries.append(f"{'  ' * (level - 1)}- [{text}](#{slug})")

    if not entries:
        return md

    name = (cfg.get("book") or {}).get("name")
    head: List[str] = []
    if name:
        head += [f"# {name}", ""]
    head += ["## Contents", "", *entries, "", "---", ""]
    return "\n".join(head) + "\n" + md


# --------------------------------- orchestrator ---------------------------------
def apply_tuning(md: str, tuning_name: str, log_cb: Optional[Callable[[str], None]] = None) -> str:
    """Run the deterministic post-processing passes for ``tuning_name``."""
    cfg = load_tuning(tuning_name) if tuning_name else {}
    if log_cb:
        label = (cfg.get("book") or {}).get("name", tuning_name)
        log_cb(f"[tuning] Applying deterministic post-processing: {label}")

    md = _normalize_chapter_headings(md, cfg)
    md = _flag_hard_cases(md)
    md = _collapse_blank_runs(md)
    md = _build_index(md, cfg)
    return md if md.endswith("\n") else md + "\n"


__all__ = ["apply_tuning", "load_tuning", "available_tunings"]

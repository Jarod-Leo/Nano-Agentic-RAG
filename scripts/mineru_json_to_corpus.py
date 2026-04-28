#!/usr/bin/env python3
"""Convert MinerU output JSON to corpus.json.

Three-stage adapter:
  1. MinerU content_list.json  ->  normalized blocks
  2. Normalized blocks         ->  reconstructed page text
  3. Page text                 ->  corpus chunks

Usage:
  python scripts/mineru_json_to_corpus.py \\
    --input path/to/mineru_output/ \\
    --output data/manuals/corpus.json \\
    --chunk-prefix benz_e300 \\
    --chunk-size 500 \\
    --overlap 50
"""

import argparse
import json
import os
import re
from html import unescape
from html.parser import HTMLParser
from typing import Optional

try:
    from scripts.corpus_chunking import chunk_pages
except ImportError:
    from corpus_chunking import chunk_pages


_WARNING_KEYWORDS = re.compile(
    r'\b(warning|caution|note|attention|warnung|achtung|aviso|'
    r'atención|警告|注意|小心|注)\b',
    re.IGNORECASE,
)


def _find_content_list(input_path: str) -> str:
    """Resolve input path to a content_list.json file.

    If ``input_path`` is a directory, searches for ``*_content_list.json``
    or ``content_list.json`` inside it.
    """
    if os.path.isfile(input_path):
        return input_path
    if os.path.isdir(input_path):
        candidates = []
        for fname in os.listdir(input_path):
            if fname.endswith("_content_list.json") or fname == "content_list.json":
                candidates.append(fname)
        if candidates:
            # Prefer shortest name (usually content_list.json)
            candidates.sort(key=len)
            resolved = os.path.join(input_path, candidates[0])
            print(f"  Found content list: {candidates[0]}")
            return resolved
        raise FileNotFoundError(
            f"No content_list.json found in directory: {input_path}"
        )
    raise FileNotFoundError(f"Input path does not exist: {input_path}")


# ---------------------------------------------------------------------------
# Stage 1: Block normalization
# ---------------------------------------------------------------------------

class _TableHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] = []
        self._cell_parts: list[str] = []
        self._in_cell = False

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"}:
            self._in_cell = True
            self._cell_parts = []

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._cell_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"}:
            cell = unescape("".join(self._cell_parts)).strip()
            if cell:
                self._row.append(cell)
            self._cell_parts = []
            self._in_cell = False
        elif tag == "tr":
            if self._row:
                self.rows.append(self._row)
            self._row = []


def _html_table_to_text(html_body: str) -> str:
    """Convert HTML table body to line-oriented text.

    Two-column tables become ``field: value`` lines; wider tables become
    pipe-delimited rows.
    """
    lines = []
    parser = _TableHTMLParser()
    parser.feed(html_body)
    parser.close()
    for cells in parser.rows:
        if len(cells) == 1:
            lines.append(cells[0])
        elif len(cells) == 2:
            lines.append(f"{cells[0]}: {cells[1]}")
        else:
            lines.append(' | '.join(cells))
    return '\n'.join(lines)


def _is_warning(text: str) -> bool:
    return bool(_WARNING_KEYWORDS.search(text[:150]))


def normalize_blocks(entries: list[dict]) -> list[dict]:
    """Convert MinerU ``content_list.json`` entries to normalized blocks.

    Returns a list of dicts sorted by (page, order), each with:

    * ``page``   — 1-based page number
    * ``kind``   — heading | paragraph | list | table | caption | warning
    * ``text``   — plain-text content
    * ``level``  — heading level (int) or None
    * ``order``  — global reading order (int)
    """
    blocks: list[dict] = []
    order = 0

    for entry in entries:
        entry_type = entry.get("type", "")
        page = entry.get("page_idx", 0) + 1

        # ---- title / heading ----
        text_level = entry.get("text_level", 0)
        if entry_type == "title" or (
            entry_type == "text" and text_level and text_level > 0
        ):
            text = _extract_str(entry, "text")
            if text:
                blocks.append({
                    "page": page,
                    "kind": "heading",
                    "text": text,
                    "level": text_level or 1,
                    "order": order,
                })
                order += 1
            continue

        # ---- body text (paragraph or warning) ----
        if entry_type == "text":
            text = _extract_str(entry, "text")
            if text:
                kind = "warning" if _is_warning(text) else "paragraph"
                blocks.append({
                    "page": page,
                    "kind": kind,
                    "text": text,
                    "level": None,
                    "order": order,
                })
                order += 1
            continue

        # ---- list ----
        if entry_type == "list":
            items = entry.get("list_items", [])
            if items:
                text = "\n".join(str(it) for it in items if isinstance(it, str)).strip()
                if text:
                    blocks.append({
                        "page": page,
                        "kind": "list",
                        "text": text,
                        "level": None,
                        "order": order,
                    })
                    order += 1
            continue

        # ---- table ----
        if entry_type == "table":
            parts = []
            captions = entry.get("table_caption", [])
            if captions:
                parts.append(" ".join(str(c) for c in captions if c))
            body = entry.get("table_body", "")
            if body:
                parts.append(_html_table_to_text(body))
            footnotes = entry.get("table_footnote", [])
            if footnotes:
                parts.append(" ".join(str(f) for f in footnotes if f))
            text = "\n".join(p for p in parts if p.strip()).strip()
            if text:
                blocks.append({
                    "page": page,
                    "kind": "table",
                    "text": text,
                    "level": None,
                    "order": order,
                })
                order += 1
            continue

        # ---- image / chart (caption + optional content) ----
        if entry_type in ("image", "chart"):
            captions = entry.get("image_caption", entry.get("chart_caption", []))
            if captions:
                cap = " ".join(str(c) for c in captions if c).strip()
                if cap:
                    blocks.append({
                        "page": page,
                        "kind": "caption",
                        "text": cap,
                        "level": None,
                        "order": order,
                    })
                    order += 1
            content = entry.get("content", "")
            if isinstance(content, str) and content.strip():
                blocks.append({
                    "page": page,
                    "kind": "paragraph",
                    "text": content.strip(),
                    "level": None,
                    "order": order,
                })
                order += 1
            continue

        # ---- equation ----
        if entry_type == "equation":
            text = _extract_str(entry, "text")
            if text:
                blocks.append({
                    "page": page,
                    "kind": "paragraph",
                    "text": text,
                    "level": None,
                    "order": order,
                })
                order += 1
            continue

        # ---- code ----
        if entry_type == "code":
            body = entry.get("code_body", "")
            if isinstance(body, str) and body.strip():
                blocks.append({
                    "page": page,
                    "kind": "paragraph",
                    "text": body.strip(),
                    "level": None,
                    "order": order,
                })
                order += 1
            continue

        # ---- auxiliary (header / footer / page_number / aside_text / page_footnote) ----
        # Intentionally skipped per spec.

        # ---- seal ----
        # Skipped (not retrieval-relevant).

    return blocks


# ---------------------------------------------------------------------------
# Stage 2: Title & section extraction
# ---------------------------------------------------------------------------

def extract_title(blocks: list[dict]) -> str:
    """Extract document title per the spec priority rules.

    1. first heading block (any page)
    2. first heading on page 1
    3. first non-empty text near page 1
    """
    for b in blocks:
        if b["kind"] == "heading":
            return b["text"]
    for b in blocks:
        if b["kind"] == "heading" and b["page"] == 1:
            return b["text"]
    for b in blocks:
        if b["page"] == 1 and b["text"].strip():
            return b["text"][:100]
    return "Untitled"


# ---------------------------------------------------------------------------
# Stage 3: Page reconstruction
# ---------------------------------------------------------------------------

def reconstruct_page_text(
    blocks: list[dict],
) -> list[dict]:
    """Serialize normalized blocks into per-page readable text.

    Returns list of ``{"page": int, "text": str, "section": str}``.
    Section labels are populated from heading hierarchy.
    """
    groups: dict[int, list[dict]] = {}
    for b in blocks:
        groups.setdefault(b["page"], []).append(b)

    # Build a page -> current-section map by scanning headings in order
    current_section = ""
    page_sections: dict[int, str] = {}

    for b in sorted(blocks, key=lambda x: (x["page"], x["order"])):
        if b["kind"] == "heading":
            current_section = b["text"]
        page_sections[b["page"]] = current_section

    result = []
    for page_num in sorted(groups):
        page_blocks = sorted(groups[page_num], key=lambda x: x["order"])
        lines = []
        for b in page_blocks:
            text = b["text"].strip()
            if not text:
                continue
            kind = b["kind"]
            if kind == "heading":
                lines.append(f"{text}")
            elif kind == "warning":
                lines.append(f"{text}")
            elif kind == "list":
                lines.append(f"{text}")
            elif kind == "table":
                lines.append(f"{text}")
            elif kind == "caption":
                lines.append(f"({text})")
            else:
                lines.append(text)

        page_text = "\n\n".join(lines).strip()
        if page_text:
            result.append({
                "page": page_num,
                "text": page_text,
                "section": page_sections.get(page_num, ""),
            })

    return result


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _validate(chunks: list[dict]) -> dict:
    required = {"chunk_id", "text", "title", "pages", "section"}
    stats: dict = {"count": len(chunks), "errors": [], "lengths": []}
    for i, c in enumerate(chunks):
        missing = required - set(c.keys())
        extra = set(c.keys()) - required
        if missing:
            stats["errors"].append(f"Chunk {i}: missing {missing}")
        if extra:
            stats["errors"].append(f"Chunk {i}: extra {extra}")
        stats["lengths"].append(len(c["text"]))
        cid = c.get("chunk_id", "")
        parts = cid.rsplit("_", 1)
        if len(parts) != 2 or not parts[1].isdigit():
            stats["errors"].append(f"Chunk {i}: bad chunk_id {cid!r}")
        pages = c.get("pages", [])
        if not isinstance(pages, list) or not all(isinstance(p, int) for p in pages):
            stats["errors"].append(f"Chunk {i}: bad pages {pages!r}")

    if stats["lengths"]:
        ls = stats["lengths"]
        stats["min_len"] = min(ls)
        stats["max_len"] = max(ls)
        stats["avg_len"] = sum(ls) / len(ls)
    return stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Convert MinerU output JSON to corpus.json"
    )
    parser.add_argument(
        "--input", required=True,
        help="Path to MinerU content_list.json or output directory",
    )
    parser.add_argument(
        "--output", required=True,
        help="Path for output corpus.json",
    )
    parser.add_argument(
        "--chunk-prefix", required=True,
        help="Document prefix for chunk_id (e.g. benz_e300)",
    )
    parser.add_argument(
        "--chunk-size", type=int, default=500,
        help="Target chars per chunk (default: 500)",
    )
    parser.add_argument(
        "--overlap", type=int, default=50,
        help="Overlap chars between chunks (default: 50)",
    )
    args = parser.parse_args()

    # -- resolve input --
    json_path = _find_content_list(args.input)
    print(f"Loading: {json_path}")
    with open(json_path, "r", encoding="utf-8") as fh:
        entries = json.load(fh)
    print(f"  {len(entries)} entries loaded")

    # -- Stage 1: normalize --
    print("Normalizing blocks ...")
    blocks = normalize_blocks(entries)
    print(f"  {len(blocks)} normalized blocks")
    for k in sorted({b["kind"] for b in blocks}):
        count = sum(1 for b in blocks if b["kind"] == k)
        print(f"    {k}: {count}")

    # -- Stage 2: title --
    title = extract_title(blocks)
    print(f"  Title: {title}")

    # -- Stage 3: reconstruct pages --
    print("Reconstructing page text ...")
    page_texts = reconstruct_page_text(blocks)
    print(f"  {len(page_texts)} pages reconstructed")
    sections = {pt["section"] for pt in page_texts if pt["section"]}
    if sections:
        print(f"  {len(sections)} sections detected")

    # -- Stage 4: chunk --
    print(f"Chunking (size={args.chunk_size}, overlap={args.overlap}) ...")
    chunks = chunk_pages(
        page_texts,
        chunk_size=args.chunk_size,
        overlap=args.overlap,
        doc_prefix=args.chunk_prefix,
        doc_title=title,
    )
    print(f"  {len(chunks)} chunks generated")

    # -- validate --
    print("Validating ...")
    stats = _validate(chunks)
    if stats["lengths"]:
        print(
            f"  Lengths: min={stats['min_len']}, max={stats['max_len']}, "
            f"avg={stats['avg_len']:.0f}"
        )
    if stats["errors"]:
        print(f"  {len(stats['errors'])} validation error(s):")
        for e in stats["errors"][:10]:
            print(f"    - {e}")
    else:
        print("  Validation passed")

    # -- save --
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(chunks, fh, ensure_ascii=False, indent=2)
    print(f"\nSaved to {args.output}")


def _extract_str(entry: dict, key: str) -> Optional[str]:
    val = entry.get(key, "")
    if isinstance(val, str):
        return val.strip() or None
    return None


if __name__ == "__main__":
    main()

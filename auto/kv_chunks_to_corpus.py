#!/usr/bin/env python3
"""Convert kv_store_text_chunks.json to corpus.json format.

Transforms chunk objects from the kv_store database format into
corpus-compatible dicts with chunk_id, text, title, pages, and section.

Filtering:
- All text chunks (no ``original_type``) are included.
- All table chunks (``original_type == "table"``) are included.
- Image chunks (``original_type == "image"``) are included **only** when
  the embedded ``Captions`` field is **not** ``None``.

Usage:
  python auto/kv_chunks_to_corpus.py \
    --chunk-prefix benz_e300 \
    --title "免责声明" \
    --input auto/kv_store_text_chunks.json \
    --output auto/corpus.json
"""

import argparse
import json
import os
import re
import sys

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_CAPTIONS_NONE_RE = re.compile(r"^Captions:\s*None\s*$", re.MULTILINE)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _image_caption_is_none(content: str) -> bool:
    """Return True if the image content has ``Captions: None``."""
    return bool(_CAPTIONS_NONE_RE.search(content))


def _page_num(chunk: dict) -> int | None:
    """Return 1-based page number from ``page_idx``, or None."""
    page_idx = chunk.get("page_idx")
    if page_idx is not None:
        return page_idx + 1
    return None


def _make_entry(
    prefix: str,
    index: int,
    text: str,
    title: str,
    pages: list[int],
) -> dict:
    """Build a single corpus-compatible chunk dict."""
    return {
        "chunk_id": f"{prefix}_{index:04d}",
        "text": text,
        "title": title,
        "pages": sorted(pages),
        "section": "",
    }


# ---------------------------------------------------------------------------
# Core conversion
# ---------------------------------------------------------------------------


def build_corpus(
    kv_chunks: dict,
    chunk_prefix: str,
    title: str,
) -> list[dict]:
    """Convert kv-store chunks into corpus format.

    Chunks are categorised by ``original_type``, filtered per the module
    docstring, then ordered: text chunks first (sorted by
    ``chunk_order_index``), multimodal chunks second (sorted by
    ``(page_idx, chunk_order_index)``).

    Args:
        kv_chunks: Mapping of ``chunk_key → chunk_obj``.
        chunk_prefix: Prefix for ``chunk_id`` (e.g. ``"benz_e300"``).
        title: Document title assigned to every corpus entry.

    Returns:
        List of corpus dicts with keys ``chunk_id``, ``text``, ``title``,
        ``pages``, ``section``.
    """
    text_chunks: dict[str, dict] = {}
    multimodal_chunks: dict[str, dict] = {}
    excluded_count = 0

    for key, chunk in kv_chunks.items():
        original_type = chunk.get("original_type")

        if original_type is None:
            # Pure text chunk
            text_chunks[key] = chunk
        elif original_type == "image":
            content = chunk.get("content", "")
            if _image_caption_is_none(content):
                excluded_count += 1
            else:
                multimodal_chunks[key] = chunk
        elif original_type == "table":
            multimodal_chunks[key] = chunk
        else:
            raise ValueError(
                f"Unknown original_type {original_type!r} for chunk {key}"
            )

    if excluded_count:
        print(f"  {excluded_count} image chunks excluded (Captions: None)")

    # Stable sort: text by chunk_order_index, multimodal by (page_idx, chunk_order_index)
    text_keys = sorted(
        text_chunks,
        key=lambda k: (text_chunks[k].get("chunk_order_index", 0), k),
    )
    multimodal_keys = sorted(
        multimodal_chunks,
        key=lambda k: (
            multimodal_chunks[k].get("page_idx", 0),
            multimodal_chunks[k].get("chunk_order_index", 0),
            k,
        ),
    )

    corpus: list[dict] = []
    chunk_index = 0

    for key in text_keys:
        chunk = text_chunks[key]
        entry = _make_entry(chunk_prefix, chunk_index, chunk["content"], title, [])
        corpus.append(entry)
        chunk_index += 1

    for key in multimodal_keys:
        chunk = multimodal_chunks[key]
        pn = _page_num(chunk)
        pages = [pn] if pn is not None else []
        entry = _make_entry(chunk_prefix, chunk_index, chunk["content"], title, pages)
        corpus.append(entry)
        chunk_index += 1

    return corpus


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

_REQUIRED_KEYS = {"chunk_id", "text", "title", "pages", "section"}


def _validate_corpus(corpus: list[dict], prefix: str) -> dict:
    """Validate corpus entries and return a stats dict.

    Stats includes ``count``, ``errors`` (list of strings), ``lengths``
    (list of text lengths), and optionally ``min_len``, ``max_len``,
    ``avg_len``.
    """
    stats: dict = {"count": len(corpus), "errors": [], "lengths": []}
    escaped = re.escape(prefix)
    cid_pat = re.compile(rf"^{escaped}_\d{{4}}$")

    for i, entry in enumerate(corpus):
        if not isinstance(entry, dict):
            stats["errors"].append(f"Entry {i}: not a dict")
            continue

        # Keys
        missing = _REQUIRED_KEYS - set(entry.keys())
        extra = set(entry.keys()) - _REQUIRED_KEYS
        if missing:
            stats["errors"].append(f"Entry {i}: missing {missing}")
        if extra:
            stats["errors"].append(f"Entry {i}: extra {extra}")

        # chunk_id
        cid = entry.get("chunk_id", "")
        if not isinstance(cid, str):
            stats["errors"].append(f"Entry {i}: bad chunk_id type {cid!r}")
        elif not cid_pat.match(cid):
            stats["errors"].append(f"Entry {i}: bad chunk_id format {cid!r}")

        expected_id = f"{prefix}_{i:04d}"
        if cid != expected_id:
            stats["errors"].append(
                f"Entry {i}: expected chunk_id {expected_id!r}, got {cid!r}"
            )

        # text
        text = entry.get("text", "")
        if not isinstance(text, str):
            stats["errors"].append(f"Entry {i}: bad text type {text!r}")
        else:
            stats["lengths"].append(len(text))

        # title
        title = entry.get("title", "")
        if not isinstance(title, str):
            stats["errors"].append(f"Entry {i}: bad title type {title!r}")

        # section
        section = entry.get("section", "")
        if not isinstance(section, str):
            stats["errors"].append(f"Entry {i}: bad section type {section!r}")
        elif section != "":
            stats["errors"].append(f"Entry {i}: section not empty: {section!r}")

        # pages
        pages = entry.get("pages", [])
        if not isinstance(pages, list) or not all(
            isinstance(p, int) for p in pages
        ):
            stats["errors"].append(f"Entry {i}: bad pages {pages!r}")

    if stats["lengths"]:
        ls = stats["lengths"]
        stats["min_len"] = min(ls)
        stats["max_len"] = max(ls)
        stats["avg_len"] = sum(ls) / len(ls)
    return stats


def _validate_corpus_or_raise(corpus: list[dict], prefix: str) -> dict:
    """Validate and raise ``ValueError`` on any errors."""
    stats = _validate_corpus(corpus, prefix)
    errors = stats.get("errors", [])
    if errors:
        raise ValueError("Validation failed:\n" + "\n".join(errors))
    return stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Convert kv_store_text_chunks.json to corpus.json",
    )
    parser.add_argument(
        "--input",
        default=None,
        help=(
            "Path to kv_store_text_chunks.json "
            "(default: auto/kv_store_text_chunks.json under script dir)"
        ),
    )
    parser.add_argument(
        "--output",
        default=None,
        help=(
            "Path for output corpus.json "
            "(default: auto/corpus.json under script dir)"
        ),
    )
    parser.add_argument(
        "--chunk-prefix",
        required=True,
        help="Document prefix for chunk_id (e.g. benz_e300)",
    )
    parser.add_argument(
        "--title",
        required=True,
        help="Document title assigned to every corpus entry",
    )
    args = parser.parse_args(argv)

    # Resolve defaults relative to this script's directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    input_path = args.input or os.path.join(script_dir, "kv_store_text_chunks.json")
    output_path = args.output or os.path.join(script_dir, "corpus.json")

    # ── Load ──────────────────────────────────────────────────────────
    print(f"Loading: {input_path}")
    with open(input_path, "r", encoding="utf-8") as fh:
        kv_chunks = json.load(fh)
    if not isinstance(kv_chunks, dict):
        raise ValueError("Input JSON must be a dict (object)")
    print(f"  {len(kv_chunks)} chunks loaded")

    # ── Convert ───────────────────────────────────────────────────────
    print(f"Building corpus (prefix={args.chunk_prefix!r}, title={args.title!r}) ...")
    corpus = build_corpus(kv_chunks, args.chunk_prefix, args.title)
    print(f"  {len(corpus)} entries generated")

    # ── Validate ──────────────────────────────────────────────────────
    stats = _validate_corpus_or_raise(corpus, args.chunk_prefix)
    if stats.get("lengths"):
        print(
            f"  Lengths: min={stats['min_len']}, max={stats['max_len']}, "
            f"avg={stats['avg_len']:.0f}"
        )

    # ── Save ──────────────────────────────────────────────────────────
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(corpus, fh, ensure_ascii=False, indent=2)
    print(f"\nSaved to {output_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

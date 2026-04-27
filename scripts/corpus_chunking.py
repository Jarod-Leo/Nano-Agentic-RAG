"""Reusable chunking helper for converting page text into corpus-compatible chunks."""

import re


def chunk_pages(
    pages: list[dict],
    chunk_size: int = 500,
    overlap: int = 50,
    doc_prefix: str = "doc",
    doc_title: str = "",
) -> list[dict]:
    """Convert page-level text into corpus chunks.

    Strategy: split on paragraph boundaries; keep paragraphs together when
    possible; force-split only when a single paragraph exceeds chunk_size.
    Cross-page chunks are allowed.

    Args:
        pages: List of ``{"page": int, "text": str, "section": Optional[str]}``
        chunk_size: Target max characters per chunk.
        overlap: Overlap characters when force-splitting long paragraphs.
        doc_prefix: Prefix for ``chunk_id`` (e.g. ``"benz_e300"``).
        doc_title: Document title assigned to every chunk.

    Returns:
        List of corpus-compatible dicts with keys:
        ``chunk_id``, ``text``, ``title``, ``pages``, ``section``.
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than 0")
    if overlap < 0:
        raise ValueError("overlap must be greater than or equal to 0")
    if chunk_size <= overlap:
        raise ValueError("chunk_size must be greater than overlap")

    chunks: list[dict] = []
    chunk_index = 0
    current_text = ""
    current_pages: list[int] = []
    current_chunk_section = ""

    for page_info in pages:
        text = page_info["text"]
        page_num = page_info["page"]
        page_section = page_info.get("section") or ""

        paragraphs = re.split(r'\n(?=\s{2,}|\S)', text)

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            if not current_text:
                current_chunk_section = page_section

            if len(current_text) + len(para) <= chunk_size:
                current_text += ("\n" if current_text else "") + para
                if page_num not in current_pages:
                    current_pages.append(page_num)
            else:
                if current_text:
                    chunks.append(_make_chunk(
                        doc_prefix, chunk_index, current_text,
                        doc_title, current_pages, current_chunk_section,
                    ))
                    chunk_index += 1

                if len(para) > chunk_size:
                    for start in range(0, len(para), chunk_size - overlap):
                        sub = para[start:start + chunk_size]
                        if len(sub) >= 50:
                            chunks.append(_make_chunk(
                                doc_prefix, chunk_index, sub,
                                doc_title, [page_num], page_section,
                            ))
                            chunk_index += 1
                    current_text = ""
                    current_pages = []
                    current_chunk_section = ""
                else:
                    current_text = para
                    current_pages = [page_num]
                    current_chunk_section = page_section

    if current_text and len(current_text) >= 50:
        chunks.append(_make_chunk(
            doc_prefix, chunk_index, current_text,
            doc_title, current_pages, current_chunk_section,
        ))

    return chunks


def _make_chunk(
    doc_prefix: str,
    index: int,
    text: str,
    title: str,
    pages: list[int],
    section: str = "",
) -> dict:
    """Build a single corpus chunk dict."""
    return {
        "chunk_id": f"{doc_prefix}_{index:04d}",
        "text": text,
        "title": title,
        "pages": sorted(pages),
        "section": section,
    }

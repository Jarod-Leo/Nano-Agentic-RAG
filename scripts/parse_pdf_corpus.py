#!/usr/bin/env python3
"""PDF 财报解析 → corpus.json

用法:
  python scripts/parse_pdf_corpus.py \
    --pdf 11323531.PDF \
    --output data/financial/corpus.json \
    --chunk-size 500
"""
import argparse
import json
import os
import re
from typing import Optional

try:
    from scripts.corpus_chunking import chunk_pages
except ModuleNotFoundError as exc:
    if exc.name != "scripts":
        raise
    from corpus_chunking import chunk_pages


def extract_text_by_page(pdf_path: str) -> list[dict]:
    """逐页提取 PDF 文本"""
    import fitz  # PyMuPDF

    doc = fitz.open(pdf_path)
    pages = []
    for i, page in enumerate(doc):
        text = page.get_text("text")
        if text.strip():
            pages.append({"page": i + 1, "text": text.strip()})
    doc.close()
    return pages


def detect_section_title(text: str) -> Optional[str]:
    """检测章节标题"""
    patterns = [
        r"^第[一二三四五六七八九十]+节\s+.+",
        r"^[一二三四五六七八九十]+、\s*.+",
        r"^\([一二三四五六七八九十]+\)\s*.+",
        r"^\d+、\s*.+",
    ]
    first_line = text.split("\n")[0].strip()
    for p in patterns:
        if re.match(p, first_line):
            return first_line
    return None


def main():
    parser = argparse.ArgumentParser(description="Parse PDF financial report to corpus.json")
    parser.add_argument("--pdf", required=True, help="Path to PDF file")
    parser.add_argument("--output", default="data/financial/corpus.json")
    parser.add_argument("--chunk-size", type=int, default=500, help="Max chars per chunk")
    parser.add_argument("--doc-title", default="", help="Document title (auto-detect if empty)")
    args = parser.parse_args()

    print(f"Parsing PDF: {args.pdf}")
    pages = extract_text_by_page(args.pdf)
    print(f"Extracted {len(pages)} pages with text")

    # 自动检测标题
    doc_title = args.doc_title
    if not doc_title and pages:
        for line in pages[0]["text"].split("\n"):
            line = line.strip()
            if "公司" in line and len(line) > 5:
                doc_title = line
                break
    print(f"Document title: {doc_title}")

    # 切块
    page_chunks = [
        {
            "page": page["page"],
            "text": page["text"],
            "section": detect_section_title(page["text"]) or "",
        }
        for page in pages
    ]
    chunks = chunk_pages(
        page_chunks,
        chunk_size=args.chunk_size,
        overlap=50,
        doc_prefix="fin",
        doc_title=doc_title,
    )
    print(f"Generated {len(chunks)} chunks")

    # 统计
    lengths = [len(c["text"]) for c in chunks]
    print(f"Chunk length: min={min(lengths)}, max={max(lengths)}, avg={sum(lengths)/len(lengths):.0f}")

    sections = set(c["section"] for c in chunks if c["section"])
    print(f"Sections detected: {len(sections)}")
    for s in sorted(sections):
        count = sum(1 for c in chunks if c["section"] == s)
        print(f"  [{count:3d}] {s}")

    # 保存
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(chunks, f, ensure_ascii=False, indent=2)
    print(f"\nSaved to {args.output}")


if __name__ == "__main__":
    main()

# MinerU Manual Corpus Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert a single MinerU JSON result for a text-based vehicle manual into a `corpus.json` that matches the repository schema and stays close to current chunking, page attribution, and retrieval behavior.

**Architecture:** Keep the final pipeline split into three explicit stages: normalize MinerU blocks, reconstruct retrieval-friendly page text, then chunk pages with a shared helper that is also used by `scripts/parse_pdf_corpus.py`. Keep `chunk_id` generation configurable via `--chunk-prefix`, and centralize prefix parsing so multi-underscore IDs such as `benz_e300_0000` are handled consistently.

**Tech Stack:** Python 3.11, stdlib `unittest`, JSON fixtures, existing `scripts/` CLI style, existing corpus/index format.

---

## File Structure

- Create: `scripts/chunk_id_utils.py`
- Create or reconcile existing untracked draft: `scripts/corpus_chunking.py`
- Create or reconcile existing untracked draft: `scripts/mineru_json_to_corpus.py`
- Modify: `scripts/parse_pdf_corpus.py`
- Modify: `scripts/domain_multihop_synthesis.py`
- Create: `tests/__init__.py`
- Create: `tests/scripts/__init__.py`
- Create: `tests/fixtures/mineru/benz_e300_content_list.json`
- Create: `tests/scripts/test_chunk_id_utils.py`
- Create: `tests/scripts/test_corpus_chunking.py`
- Create: `tests/scripts/test_mineru_json_to_corpus.py`

Current working tree already contains untracked drafts at `scripts/corpus_chunking.py` and `scripts/mineru_json_to_corpus.py`. During execution, reconcile those files to the interfaces below instead of creating parallel implementations under different paths.

### Task 1: Add Chunk ID Prefix Utility

**Files:**
- Create: `scripts/chunk_id_utils.py`
- Create: `tests/__init__.py`
- Create: `tests/scripts/__init__.py`
- Test: `tests/scripts/test_chunk_id_utils.py`

- [ ] **Step 1: Write the failing test**

```python
import unittest

from scripts.chunk_id_utils import get_doc_prefix


class ChunkIdUtilsTest(unittest.TestCase):
    def test_preserves_multi_underscore_prefix(self):
        self.assertEqual(get_doc_prefix("benz_e300_0000"), "benz_e300")
        self.assertEqual(get_doc_prefix("manual_0007"), "manual")

    def test_rejects_missing_numeric_suffix(self):
        with self.assertRaises(ValueError):
            get_doc_prefix("benz_e300")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.scripts.test_chunk_id_utils -v`
Expected: `ERROR` with `ModuleNotFoundError: No module named 'scripts.chunk_id_utils'`

- [ ] **Step 3: Write minimal implementation**

```python
import re


_CHUNK_ID_RE = re.compile(r"^(?P<prefix>.+)_(?P<index>\d{4})$")


def get_doc_prefix(chunk_id: str) -> str:
    match = _CHUNK_ID_RE.match(chunk_id)
    if not match:
        raise ValueError(f"Invalid chunk_id: {chunk_id!r}")
    return match.group("prefix")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.scripts.test_chunk_id_utils -v`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add tests/__init__.py tests/scripts/__init__.py tests/scripts/test_chunk_id_utils.py scripts/chunk_id_utils.py
git commit -m "feat: add chunk id prefix utility"
```

### Task 2: Land Shared Chunking Helper And Refactor PDF Parser

**Files:**
- Create or Modify: `scripts/corpus_chunking.py`
- Modify: `scripts/parse_pdf_corpus.py`
- Test: `tests/scripts/test_corpus_chunking.py`

- [ ] **Step 1: Write the failing test**

```python
import unittest

from scripts.corpus_chunking import chunk_pages


class ChunkPagesTest(unittest.TestCase):
    def test_cross_page_chunk_keeps_start_section_and_prefix(self):
        pages = [
            {
                "page": 1,
                "text": "Overview paragraph one.\n\nOverview paragraph two.",
                "section": "Overview",
            },
            {
                "page": 2,
                "text": "Climate control paragraph on next page.",
                "section": "Climate Control",
            },
        ]

        chunks = chunk_pages(
            pages,
            chunk_size=120,
            overlap=20,
            doc_prefix="benz_e300",
            doc_title="Mercedes-Benz E300 Owner's Manual",
        )

        self.assertEqual(chunks[0]["chunk_id"], "benz_e300_0000")
        self.assertEqual(chunks[0]["pages"], [1, 2])
        self.assertEqual(chunks[0]["section"], "Overview")
        self.assertEqual(chunks[0]["title"], "Mercedes-Benz E300 Owner's Manual")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.scripts.test_corpus_chunking -v`
Expected: `FAIL` on the section assertion because the current page-level section tracking emits the later page's section for a cross-page chunk.

- [ ] **Step 3: Write minimal implementation**

In `scripts/corpus_chunking.py`, make chunk section assignment depend on the section at chunk start, not the last page seen:

```python
def chunk_pages(...):
    chunks = []
    chunk_index = 0
    current_text = ""
    current_pages = []
    current_chunk_section = ""

    for unit in _iter_units(pages):
        unit_text = unit["text"].strip()
        if not unit_text:
            continue

        if not current_text:
            current_chunk_section = unit.get("section", "")

        if len(current_text) + len(unit_text) <= chunk_size:
            current_text += ("\n" if current_text else "") + unit_text
            if unit["page"] not in current_pages:
                current_pages.append(unit["page"])
            continue

        chunks.append(_make_chunk(
            doc_prefix, chunk_index, current_text, doc_title,
            current_pages, current_chunk_section,
        ))
        chunk_index += 1
        current_text = unit_text
        current_pages = [unit["page"]]
        current_chunk_section = unit.get("section", "")
```

Then refactor `scripts/parse_pdf_corpus.py` to import the helper instead of carrying a second copy of chunking logic:

```python
from corpus_chunking import chunk_pages


def main():
    ...
    page_chunks = [
        {"page": p["page"], "text": p["text"], "section": detect_section_title(p["text"]) or ""}
        for p in pages
    ]
    chunks = chunk_pages(
        page_chunks,
        chunk_size=args.chunk_size,
        overlap=50,
        doc_prefix="fin",
        doc_title=doc_title,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.scripts.test_corpus_chunking -v`
Expected: `OK`

Run: `python scripts/parse_pdf_corpus.py --help`
Expected: CLI help renders without import errors

- [ ] **Step 5: Commit**

```bash
git add tests/scripts/test_corpus_chunking.py scripts/corpus_chunking.py scripts/parse_pdf_corpus.py
git commit -m "refactor: share corpus chunking logic"
```

### Task 3: Implement MinerU Normalization, Title Extraction, And Page Reconstruction

**Files:**
- Create: `tests/fixtures/mineru/benz_e300_content_list.json`
- Test: `tests/scripts/test_mineru_json_to_corpus.py`
- Modify: `scripts/mineru_json_to_corpus.py`

- [ ] **Step 1: Write the failing fixture and unit tests**

Fixture file `tests/fixtures/mineru/benz_e300_content_list.json`:

```json
[
  {
    "type": "title",
    "page_idx": 0,
    "text": "Mercedes-Benz E300 Owner's Manual",
    "text_level": 1
  },
  {
    "type": "text",
    "page_idx": 0,
    "text": "Warning: Never adjust the driver's seat while the vehicle is moving."
  },
  {
    "type": "table",
    "page_idx": 0,
    "table_caption": ["Recommended cold tire pressure"],
    "table_body": "<table><tr><td>Front</td><td>240 kPa</td></tr><tr><td>Rear</td><td>250 kPa</td></tr></table>",
    "table_footnote": ["Applies to normal load."]
  },
  {
    "type": "text",
    "page_idx": 1,
    "text": "Climate Control",
    "text_level": 1
  },
  {
    "type": "list",
    "page_idx": 1,
    "list_items": [
      "1. Press MENU.",
      "2. Select Climate.",
      "3. Turn the left knob to increase temperature."
    ]
  },
  {
    "type": "image",
    "page_idx": 1,
    "image_caption": ["Air outlet direction control switch"]
  }
]
```

Test file excerpt:

```python
import json
import unittest
from pathlib import Path

from scripts.mineru_json_to_corpus import (
    extract_title,
    normalize_blocks,
    reconstruct_page_text,
)


FIXTURE = Path("tests/fixtures/mineru/benz_e300_content_list.json")


class MineruNormalizationTest(unittest.TestCase):
    def test_normalization_and_page_reconstruction(self):
        entries = json.loads(FIXTURE.read_text(encoding="utf-8"))
        blocks = normalize_blocks(entries)

        self.assertEqual(extract_title(blocks), "Mercedes-Benz E300 Owner's Manual")
        self.assertTrue(any(b["kind"] == "warning" for b in blocks))
        self.assertTrue(any("Front: 240 kPa" in b["text"] for b in blocks if b["kind"] == "table"))

        pages = reconstruct_page_text(blocks)
        self.assertEqual(pages[0]["section"], "Mercedes-Benz E300 Owner's Manual")
        self.assertEqual(pages[1]["section"], "Climate Control")
        self.assertIn("1. Press MENU.", pages[1]["text"])
        self.assertIn("(Air outlet direction control switch)", pages[1]["text"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.scripts.test_mineru_json_to_corpus.MineruNormalizationTest -v`
Expected: `FAIL` on at least one of the table serialization, warning classification, or reconstructed section assertions.

- [ ] **Step 3: Write minimal implementation**

In `scripts/mineru_json_to_corpus.py`, expose pure functions that match the spec:

```python
def normalize_blocks(entries: list[dict]) -> list[dict]:
    ...


def extract_title(blocks: list[dict]) -> str:
    ...


def reconstruct_page_text(blocks: list[dict]) -> list[dict]:
    ...
```

Also make imports work both from CLI execution and test imports:

```python
try:
    from scripts.corpus_chunking import chunk_pages
except ImportError:
    from corpus_chunking import chunk_pages
```

For table handling, serialize two-column rows as `field: value` and keep captions and footnotes:

```python
def _html_table_to_text(html_body: str) -> str:
    text = re.sub(r"<[^>]+>", "\t", html_body)
    text = unescape(text)
    ...
    if len(cells) == 2:
        lines.append(f"{cells[0]}: {cells[1]}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.scripts.test_mineru_json_to_corpus.MineruNormalizationTest -v`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add tests/fixtures/mineru/benz_e300_content_list.json tests/scripts/test_mineru_json_to_corpus.py scripts/mineru_json_to_corpus.py
git commit -m "feat: normalize MinerU manual blocks"
```

### Task 4: Finish End-To-End Corpus Builder And Prefix Compatibility

**Files:**
- Modify: `scripts/mineru_json_to_corpus.py`
- Modify: `scripts/domain_multihop_synthesis.py`
- Test: `tests/scripts/test_mineru_json_to_corpus.py`

- [ ] **Step 1: Write the failing end-to-end and compatibility tests**

Append these tests to `tests/scripts/test_mineru_json_to_corpus.py`:

```python
from scripts.chunk_id_utils import get_doc_prefix
from scripts.mineru_json_to_corpus import build_corpus_from_entries


class MineruEndToEndTest(unittest.TestCase):
    def test_builds_corpus_with_expected_schema(self):
        entries = json.loads(FIXTURE.read_text(encoding="utf-8"))
        chunks = build_corpus_from_entries(
            entries,
            chunk_prefix="benz_e300",
            chunk_size=120,
            overlap=20,
        )

        self.assertTrue(chunks)
        self.assertEqual(
            set(chunks[0].keys()),
            {"chunk_id", "text", "title", "pages", "section"},
        )
        self.assertEqual(chunks[0]["chunk_id"], "benz_e300_0000")
        self.assertEqual(get_doc_prefix(chunks[0]["chunk_id"]), "benz_e300")
        self.assertTrue(all(isinstance(p, int) for p in chunks[0]["pages"]))
        self.assertTrue(any(chunk["section"] == "Climate Control" for chunk in chunks))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.scripts.test_mineru_json_to_corpus.MineruEndToEndTest -v`
Expected: `ERROR` with `ImportError` or `AttributeError` because `build_corpus_from_entries(...)` does not exist yet.

- [ ] **Step 3: Write minimal implementation**

Add a pure end-to-end builder in `scripts/mineru_json_to_corpus.py` and use the shared prefix helper in `scripts/domain_multihop_synthesis.py`:

```python
def build_corpus_from_entries(
    entries: list[dict],
    chunk_prefix: str,
    chunk_size: int = 500,
    overlap: int = 50,
) -> list[dict]:
    blocks = normalize_blocks(entries)
    title = extract_title(blocks)
    page_texts = reconstruct_page_text(blocks)
    chunks = chunk_pages(
        page_texts,
        chunk_size=chunk_size,
        overlap=overlap,
        doc_prefix=chunk_prefix,
        doc_title=title,
    )
    stats = _validate(chunks)
    if stats["errors"]:
        raise ValueError("Invalid corpus output: " + "; ".join(stats["errors"]))
    return chunks
```

Compatibility change in `scripts/domain_multihop_synthesis.py`:

```python
from chunk_id_utils import get_doc_prefix

...
company_prefix = get_doc_prefix(cid)
...
if get_doc_prefix(other_cid) != company_prefix:
    continue
```

Then make `main()` delegate to `build_corpus_from_entries(...)` instead of duplicating orchestration logic.

- [ ] **Step 4: Run tests and verification**

Run: `python -m unittest tests.scripts.test_mineru_json_to_corpus -v`
Expected: `OK`

Run: `rg -n "split\\(\\s*['\\\"]_['\\\"]\\s*\\)\\s*\\[\\s*0\\s*\\]" scripts/domain_multihop_synthesis.py`
Expected: no matches

Run: `python scripts/mineru_json_to_corpus.py --help`
Expected: CLI help renders and includes `--chunk-prefix`

- [ ] **Step 5: Commit**

```bash
git add tests/scripts/test_mineru_json_to_corpus.py scripts/mineru_json_to_corpus.py scripts/domain_multihop_synthesis.py
git commit -m "feat: add MinerU manual corpus adapter"
```

## Self-Review

### Spec coverage

- Single-manual MinerU JSON input: Task 3 and Task 4
- Final corpus schema compatibility: Task 4
- Shared chunking behavior aligned with current corpus: Task 2
- Configurable prefix such as `benz_e300`: Task 1 and Task 4
- Multi-underscore prefix compatibility for downstream code: Task 1 and Task 4
- Section, title, pages, warning, list, caption, and table handling: Task 3

No uncovered spec sections remain.

### Placeholder scan

- No `TODO`, `TBD`, or deferred implementation markers remain in the plan
- Every code-changing task includes concrete code blocks
- Every verification step includes an exact command and expected result

### Type consistency

- `get_doc_prefix(chunk_id: str) -> str` is introduced once and reused consistently
- `chunk_pages(...)` always emits `chunk_id`, `text`, `title`, `pages`, `section`
- `build_corpus_from_entries(...)` is the single pure end-to-end builder used by tests and CLI orchestration


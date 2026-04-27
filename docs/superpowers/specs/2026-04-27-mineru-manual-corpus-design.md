# MinerU Manual Corpus Adapter Design

## Summary

This design adds a single-document adapter that converts MinerU JSON output for a vehicle user manual PDF into the existing `corpus.json` contract used by this repository.

The goal is not only schema compatibility with `data/financial_all/corpus_all.json`, but also approximate alignment with the current corpus behavior:

- similar chunk granularity, centered around about 500 characters
- page ownership that supports cross-page chunks such as `[12, 13]`
- retrieval behavior that remains close to the current indexing and search pipeline

Scope is intentionally limited to one manual at a time. MinerU runs outside this project and produces JSON first. This project only reads MinerU JSON and converts it into `corpus.json`.

## Goals

- Accept MinerU JSON as input for a single text-based PDF manual
- Produce output compatible with the current corpus schema:
  - `chunk_id`
  - `text`
  - `title`
  - `pages`
  - `section`
- Keep chunk length and cross-page behavior close to the current financial corpus style
- Preserve retrieval-critical content such as procedural steps, warnings, captions, and table values
- Support configurable chunk ID prefixes such as `benz_e300`

## Non-Goals

- No direct invocation of MinerU from the conversion script
- No multi-document merge flow
- No index rebuild automation as part of this task
- No schema expansion for layout metadata such as bounding boxes or block types

## Existing Constraints

The current repository uses a minimal corpus contract. Downstream indexing and retrieval rely primarily on `text`, `title`, and `chunk_id`. `pages` and `section` are additional metadata, but `pages` is also used by the synthesis pipeline to exclude nearby chunks from the same document.

The current corpus style is approximately:

- chunk length usually near 500 characters
- chunks may span multiple pages
- one chunk maps to one primary section label

Because the new source is a vehicle user manual instead of a financial report, any report-specific assumptions should be removed. The adapter should reproduce current corpus behavior, not report-specific semantics.

## Recommended Approach

Use a three-stage adapter:

`MinerU JSON -> normalized blocks -> reconstructed page text -> corpus chunks`

This is a hybrid approach:

- MinerU provides structural extraction, reading order, and page attribution
- the repository keeps control over final chunking so output remains close to existing corpus behavior

This is preferred over:

- emitting one chunk per MinerU block, which would fragment retrieval too much
- ignoring MinerU structure and falling back to plain PDF extraction, which would underuse MinerU

## Proposed Files

- new entry script: `scripts/mineru_json_to_corpus.py`
- new reusable chunking helper: `scripts/corpus_chunking.py`

The current `scripts/parse_pdf_corpus.py` should not be rewritten in place. The new adapter has a different input contract and should remain separate. Shared chunking logic can be extracted into a helper module.

## Input Contract

The adapter reads a MinerU JSON result from disk. MinerU is expected to have already processed the manual PDF.

CLI shape:

```bash
python scripts/mineru_json_to_corpus.py \
  --input path/to/mineru_output.json \
  --output data/manuals/corpus.json \
  --chunk-prefix benz_e300 \
  --chunk-size 500 \
  --overlap 50
```

Required inputs:

- `--input`: MinerU JSON path
- `--output`: target corpus path
- `--chunk-prefix`: document prefix used in `chunk_id`

Optional inputs:

- `--chunk-size`: default `500`
- `--overlap`: default `50`

## Intermediate Normalized Block Schema

MinerU raw JSON should be normalized into an internal list of blocks with a stable schema:

```python
{
    "page": 12,
    "kind": "heading|paragraph|list|table|caption|warning",
    "text": "...",
    "level": 1,
    "order": 37,
}
```

Notes:

- `page` is the source page number
- `kind` is an internal normalized type, not a final corpus field
- `text` is the plain-text representation used for reconstruction
- `level` is only meaningful for headings; use `None` otherwise
- `order` preserves page-local or document-global reading order

The adapter should hide MinerU schema details behind this normalized layer so chunking code remains independent of MinerU internals.

## Block Mapping Rules

MinerU block types should be mapped into normalized blocks as follows:

- title or heading blocks:
  - map to `kind="heading"`
  - preserve heading text
  - keep heading level if MinerU provides one
- body text blocks:
  - map to `kind="paragraph"`
- ordered or unordered list blocks:
  - map to `kind="list"`
  - preserve numbers or bullets in text form
- warning, caution, note, or notice blocks:
  - map to `kind="warning"`
  - preserve marker words such as `Warning`, `Caution`, `Note`, `Attention`
- table blocks:
  - map to `kind="table"`
  - convert to line-oriented text
  - do not drop field names, row labels, numeric values, units, or statuses
- figure captions or diagram labels:
  - map to `kind="caption"`
  - keep captions that contain descriptive or part-related text
  - discard purely decorative captions if they carry no retrieval value

## Title Extraction

Document title should be assigned in this priority order:

1. first document-level or highest-level MinerU heading/title block near the beginning
2. first strong heading on page 1
3. topmost non-empty text near the start of page 1

This replaces the report-specific title heuristics currently used in `scripts/parse_pdf_corpus.py`.

## Section Extraction

`section` should be derived from heading hierarchy rather than report-style regular expressions.

Rules:

- maintain a current section pointer while scanning normalized blocks
- when a heading block appears, update the current section text
- when a chunk begins, its `section` is the most recent heading text in scope
- one chunk should have one primary section value only

This is better suited to vehicle manuals, where sections are often labels such as:

- Safety
- Dashboard
- Air Conditioning
- Mirrors
- Maintenance
- Troubleshooting
- Technical Specifications

## Page Reconstruction

Before chunking, reconstruct each page into retrieval-oriented text using normalized block order.

Reconstruction rules:

- `heading`:
  - keep clear boundaries around the heading
  - update the current section pointer
- `paragraph`:
  - append as continuous prose
- `list`:
  - preserve ordered steps and bullet semantics
- `warning`:
  - preserve warning labels and content together
- `table`:
  - serialize rows into searchable text
  - prefer forms like `field: value` when possible
- `caption`:
  - include explanatory captions and component descriptions

This reconstruction should aim for readable and searchable text, not visual layout fidelity.

## Chunking Rules

Chunking should stay close to the existing corpus behavior while respecting manual structure.

Primary targets:

- target chunk size: about 500 characters
- overlap: about 50 characters
- minimum emitted chunk length: about 50 characters
- cross-page chunks are allowed

Boundary priority when deciding where to cut:

1. heading boundary
2. warning, list, or small table-group boundary
3. paragraph boundary
4. forced split only if a single unit is too long

Chunking rules:

- avoid splitting a short procedure sequence across chunks
- avoid splitting a warning block across chunks
- avoid splitting a compact parameter table across chunks
- if a single unit exceeds the limit, force split with overlap
- allow page lists such as `[12, 13]` when a chunk spans multiple pages
- assign one primary `section` per chunk based on the section in scope at chunk start

This differs slightly from raw block-based chunking, but it better matches existing retrieval behavior.

## Final Output Schema

Final `corpus.json` entries must remain exactly:

```json
{
  "chunk_id": "benz_e300_0000",
  "text": "...",
  "title": "Mercedes-Benz E300 Owner's Manual",
  "pages": [12, 13],
  "section": "Air Conditioning"
}
```

No extra fields should be emitted in the final corpus.

## Chunk ID Rules

`chunk_id` format is:

`{doc_prefix}_{index:04d}`

Examples:

- `benz_e300_0000`
- `benz_e300_0001`

`doc_prefix` is required and must be configurable by CLI argument.

Important parsing constraint:

- `doc_prefix` may itself contain underscores
- code that derives document prefix from `chunk_id` must use:

```python
doc_prefix = chunk_id.rsplit("_", 1)[0]
```

- code must not use:

```python
chunk_id.split("_")[0]
```

Reason:

- `benz_e300_0000` must resolve to `benz_e300`, not `benz`

This matters because existing code such as `scripts/domain_multihop_synthesis.py` currently assumes a single underscore boundary.

## Compatibility Implications

For the single-manual scope of this design, outputting `benz_e300_0000` style IDs is safe for indexing and retrieval.

If later work extends to multi-manual merge flows, those flows should preserve per-document prefixes and should update any prefix-grouping logic to use `rsplit("_", 1)`.

## Validation Plan

Minimum validation should cover four dimensions:

1. Schema validation
   - every emitted chunk has only `chunk_id`, `text`, `title`, `pages`, `section`
2. Distribution validation
   - most chunk lengths remain near the current corpus style, centered roughly in the 450 to 500 character range
3. Page attribution validation
   - cross-page chunks produce stable page lists such as `[n, n+1]`
4. Retrieval smoke test
   - run 5 to 10 representative manual questions and confirm top hits are sensible

Example smoke-test queries for a vehicle manual:

- how to enable windshield defogging
- what tire pressure warning means
- where mirror heating is controlled
- how to reset maintenance reminder
- what the seat memory buttons do

## Risks

- MinerU table serialization may vary in quality; dropping labels or units would hurt retrieval
- overly strict structure preservation may cause chunk sizes to drift away from the current corpus distribution
- overly aggressive flattening may destroy procedural and warning semantics that matter for manual QA
- any remaining code that assumes `chunk_id.split("_")[0]` will mis-handle multi-underscore prefixes

## Decision Summary

- use MinerU JSON as the only upstream input inside this project
- keep final corpus schema unchanged
- reconstruct searchable text from MinerU structure before chunking
- preserve procedures, warnings, captions, and tables in text form
- keep chunking behavior close to the current corpus style
- make chunk prefix configurable and support prefixes such as `benz_e300`

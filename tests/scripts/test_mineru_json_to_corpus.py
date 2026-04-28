import json
import unittest
from pathlib import Path

from scripts.mineru_json_to_corpus import (
    _chunk_pages_by_section,
    _html_table_to_text,
    _raise_on_validation_errors,
    _validate_chunks_or_raise,
    _validate,
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
        self.assertTrue(
            any("Front: 240 kPa" in b["text"] for b in blocks if b["kind"] == "table")
        )
        self.assertTrue(
            any(
                "Recommended cold tire pressure" in b["text"]
                for b in blocks
                if b["kind"] == "table"
            )
        )
        self.assertTrue(
            any(
                "Applies to normal load." in b["text"]
                for b in blocks
                if b["kind"] == "table"
            )
        )

        pages = reconstruct_page_text(blocks)
        self.assertEqual(pages[0]["section"], "Mercedes-Benz E300 Owner's Manual")
        self.assertEqual(pages[1]["section"], "Climate Control")
        self.assertIn("1. Press MENU.", pages[1]["text"])
        self.assertIn("(Air outlet direction control switch)", pages[1]["text"])

    def test_extract_title_prefers_page_one_heading_over_out_of_order_later_heading(self):
        blocks = [
            {"page": 2, "kind": "heading", "text": "Climate Control", "level": 1, "order": 0},
            {
                "page": 1,
                "kind": "heading",
                "text": "Mercedes-Benz E300 Owner's Manual",
                "level": 1,
                "order": 1,
            },
        ]

        self.assertEqual(extract_title(blocks), "Mercedes-Benz E300 Owner's Manual")

    def test_extract_title_prefers_page_one_title_block_over_same_page_heading(self):
        entries = [
            {
                "type": "text",
                "page_idx": 0,
                "text": "Climate Control",
                "text_level": 1,
            },
            {
                "type": "title",
                "page_idx": 0,
                "text": "Mercedes-Benz E300 Owner's Manual",
                "text_level": 1,
            },
        ]

        blocks = normalize_blocks(entries)

        self.assertEqual(extract_title(blocks), "Mercedes-Benz E300 Owner's Manual")

    def test_extract_title_prefers_lower_heading_level_on_page_one(self):
        blocks = [
            {"page": 1, "kind": "heading", "text": "Climate Control", "level": 2, "order": 0, "source_type": "text"},
            {
                "page": 1,
                "kind": "heading",
                "text": "Mercedes-Benz E300 Owner's Manual",
                "level": 1,
                "order": 1,
                "source_type": "text",
            },
        ]

        self.assertEqual(extract_title(blocks), "Mercedes-Benz E300 Owner's Manual")

    def test_reconstruct_page_text_anchors_section_to_start_of_page(self):
        blocks = [
            {"page": 1, "kind": "heading", "text": "Driving", "level": 1, "order": 0},
            {"page": 1, "kind": "paragraph", "text": "Seat adjustment guidance.", "level": None, "order": 1},
            {"page": 1, "kind": "heading", "text": "Climate Control", "level": 1, "order": 2},
            {"page": 1, "kind": "list", "text": "1. Press MENU.", "level": None, "order": 3},
            {"page": 2, "kind": "paragraph", "text": "Temperature remains stable.", "level": None, "order": 4},
        ]

        pages = reconstruct_page_text(blocks)

        self.assertEqual(pages[0]["section"], "Driving")
        self.assertEqual(pages[1]["section"], "Climate Control")

    def test_reconstruct_page_text_anchors_heading_only_page_to_first_heading(self):
        blocks = [
            {"page": 1, "kind": "heading", "text": "Driving", "level": 1, "order": 0},
            {"page": 1, "kind": "heading", "text": "Climate Control", "level": 1, "order": 1},
            {"page": 2, "kind": "paragraph", "text": "Airflow guidance.", "level": None, "order": 2},
        ]

        pages = reconstruct_page_text(blocks)

        self.assertEqual(pages[0]["section"], "Driving")
        self.assertEqual(pages[1]["section"], "Climate Control")

    def test_reconstruct_page_text_anchors_to_last_leading_heading_before_body(self):
        blocks = [
            {"page": 1, "kind": "heading", "text": "Controls", "level": 1, "order": 0},
            {"page": 1, "kind": "heading", "text": "Climate Control", "level": 2, "order": 1},
            {"page": 1, "kind": "paragraph", "text": "Set temperature with the left knob.", "level": None, "order": 2},
        ]

        pages = reconstruct_page_text(blocks)

        self.assertEqual(pages[0]["section"], "Climate Control")

    def test_reconstruct_page_text_splits_same_page_section_transitions(self):
        blocks = [
            {"page": 1, "kind": "heading", "text": "Driving", "level": 1, "order": 0},
            {"page": 1, "kind": "paragraph", "text": "Seat adjustment guidance.", "level": None, "order": 1},
            {"page": 1, "kind": "heading", "text": "Climate Control", "level": 1, "order": 2},
            {"page": 1, "kind": "paragraph", "text": "Set temperature with the left knob.", "level": None, "order": 3},
        ]

        pages = reconstruct_page_text(blocks)

        self.assertEqual(len(pages), 2)
        self.assertEqual(pages[0]["page"], 1)
        self.assertEqual(pages[0]["section"], "Driving")
        self.assertIn("Seat adjustment guidance.", pages[0]["text"])
        self.assertNotIn("Set temperature with the left knob.", pages[0]["text"])
        self.assertEqual(pages[1]["page"], 1)
        self.assertEqual(pages[1]["section"], "Climate Control")
        self.assertIn("Set temperature with the left knob.", pages[1]["text"])

    def test_html_table_to_text_preserves_block_boundaries_and_empty_cells(self):
        html = (
            "<table>"
            "<tr><td><p>Front<br>Left</p></td><td><div>240 kPa</div><div>Normal load</div></td></tr>"
            "<tr><td>Rear</td><td></td></tr>"
            "<tr><td><ul><li>Spare</li><li>Temporary</li></ul></td><td>420 kPa</td></tr>"
            "</table>"
        )

        text = _html_table_to_text(html)
        lines = text.splitlines()

        self.assertEqual(lines[0], "Front Left: 240 kPa Normal load")
        self.assertEqual(lines[1], "Rear:")
        self.assertEqual(lines[2], "Spare Temporary: 420 kPa")

    def test_validate_reports_non_string_chunk_id_without_throwing(self):
        chunks = [
            {
                "chunk_id": None,
                "text": "Seat adjustment guidance.",
                "title": "Mercedes-Benz E300 Owner's Manual",
                "pages": [1],
                "section": "Driving",
            },
            {
                "chunk_id": 123,
                "text": "Climate guidance.",
                "title": "Mercedes-Benz E300 Owner's Manual",
                "pages": [2],
                "section": "Climate Control",
            },
        ]

        stats = _validate(chunks)

        self.assertEqual(stats["count"], 2)
        self.assertGreaterEqual(len(stats["errors"]), 2)
        self.assertTrue(any("bad chunk_id None" in err for err in stats["errors"]))
        self.assertTrue(any("bad chunk_id 123" in err for err in stats["errors"]))

    def test_validate_reports_non_string_title_and_section(self):
        chunks = [
            {
                "chunk_id": "benz_e300_0000",
                "text": "Seat adjustment guidance.",
                "title": None,
                "pages": [1],
                "section": 123,
            }
        ]

        stats = _validate(chunks)

        self.assertTrue(any("bad title None" in err for err in stats["errors"]))
        self.assertTrue(any("bad section 123" in err for err in stats["errors"]))

    def test_chunk_pages_by_section_keeps_fixture_sections_separate(self):
        entries = json.loads(FIXTURE.read_text(encoding="utf-8"))
        blocks = normalize_blocks(entries)
        pages = reconstruct_page_text(blocks)

        chunks = _chunk_pages_by_section(
            pages,
            chunk_size=10_000,
            overlap=0,
            doc_prefix="benz_e300",
            doc_title=extract_title(blocks),
        )

        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0]["section"], "Mercedes-Benz E300 Owner's Manual")
        self.assertEqual(chunks[1]["section"], "Climate Control")
        self.assertNotIn("Climate Control", chunks[0]["text"])
        self.assertNotIn("Warning: Never adjust", chunks[1]["text"])

    def test_chunk_pages_by_section_keeps_same_page_section_transitions_separate(self):
        blocks = [
            {"page": 1, "kind": "heading", "text": "Driving", "level": 1, "order": 0},
            {"page": 1, "kind": "paragraph", "text": "Seat adjustment guidance.", "level": None, "order": 1},
            {"page": 1, "kind": "heading", "text": "Climate Control", "level": 1, "order": 2},
            {"page": 1, "kind": "paragraph", "text": "Set temperature with the left knob.", "level": None, "order": 3},
        ]
        pages = reconstruct_page_text(blocks)

        chunks = _chunk_pages_by_section(
            pages,
            chunk_size=10_000,
            overlap=0,
            doc_prefix="benz_e300",
            doc_title="Mercedes-Benz E300 Owner's Manual",
        )

        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0]["section"], "Driving")
        self.assertNotIn("Set temperature with the left knob.", chunks[0]["text"])
        self.assertEqual(chunks[1]["section"], "Climate Control")
        self.assertIn("Set temperature with the left knob.", chunks[1]["text"])

    def test_trailing_heading_segment_uses_new_section_before_next_page_body(self):
        blocks = [
            {"page": 1, "kind": "heading", "text": "Driving", "level": 1, "order": 0},
            {"page": 1, "kind": "paragraph", "text": "Seat adjustment guidance.", "level": None, "order": 1},
            {"page": 1, "kind": "heading", "text": "Climate Control", "level": 1, "order": 2},
            {"page": 2, "kind": "paragraph", "text": "Set temperature with the left knob.", "level": None, "order": 3},
        ]

        pages = reconstruct_page_text(blocks)
        chunks = _chunk_pages_by_section(
            pages,
            chunk_size=10_000,
            overlap=0,
            doc_prefix="benz_e300",
            doc_title="Mercedes-Benz E300 Owner's Manual",
        )

        self.assertEqual(len(pages), 3)
        self.assertEqual(pages[1]["section"], "Climate Control")
        self.assertIn("Climate Control", pages[1]["text"])
        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0]["section"], "Driving")
        self.assertNotIn("Climate Control", chunks[0]["text"])
        self.assertEqual(chunks[1]["section"], "Climate Control")
        self.assertIn("Set temperature with the left knob.", chunks[1]["text"])

    def test_raise_on_validation_errors_fails_fast(self):
        stats = {"errors": ["Chunk 0: bad chunk_id None"]}

        with self.assertRaises(ValueError):
            _raise_on_validation_errors(stats)

    def test_validate_chunks_or_raise_uses_validation_gate(self):
        chunks = [
            {
                "chunk_id": None,
                "text": "Seat adjustment guidance.",
                "title": "Mercedes-Benz E300 Owner's Manual",
                "pages": [1],
                "section": "Driving",
            }
        ]

        with self.assertRaises(ValueError):
            _validate_chunks_or_raise(chunks)


if __name__ == "__main__":
    unittest.main()

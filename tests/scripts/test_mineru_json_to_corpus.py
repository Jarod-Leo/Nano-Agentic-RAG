import json
import unittest
from pathlib import Path

from scripts.mineru_json_to_corpus import (
    _html_table_to_text,
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


if __name__ == "__main__":
    unittest.main()

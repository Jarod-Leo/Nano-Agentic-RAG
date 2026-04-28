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
        self.assertTrue(
            any("Front: 240 kPa" in b["text"] for b in blocks if b["kind"] == "table")
        )

        pages = reconstruct_page_text(blocks)
        self.assertEqual(pages[0]["section"], "Mercedes-Benz E300 Owner's Manual")
        self.assertEqual(pages[1]["section"], "Climate Control")
        self.assertIn("1. Press MENU.", pages[1]["text"])
        self.assertIn("(Air outlet direction control switch)", pages[1]["text"])


if __name__ == "__main__":
    unittest.main()

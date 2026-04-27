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

    def test_invalid_chunking_config_raises_value_error(self):
        pages = [{"page": 1, "text": "A" * 80, "section": "Overview"}]

        invalid_configs = [
            {"chunk_size": 0, "overlap": 0},
            {"chunk_size": 80, "overlap": -1},
            {"chunk_size": 80, "overlap": 80},
        ]

        for config in invalid_configs:
            with self.subTest(config=config):
                with self.assertRaises(ValueError):
                    chunk_pages(
                        pages,
                        doc_prefix="benz_e300",
                        doc_title="Mercedes-Benz E300 Owner's Manual",
                        **config,
                    )

    def test_new_chunk_uses_empty_page_section_without_carrying_previous_one(self):
        pages = [
            {"page": 1, "text": "A" * 80, "section": "Overview"},
            {"page": 2, "text": "B" * 80, "section": ""},
        ]

        chunks = chunk_pages(
            pages,
            chunk_size=100,
            overlap=20,
            doc_prefix="benz_e300",
            doc_title="Mercedes-Benz E300 Owner's Manual",
        )

        self.assertEqual(chunks[0]["section"], "Overview")
        self.assertEqual(chunks[1]["pages"], [2])
        self.assertEqual(chunks[1]["section"], "")

    def test_short_buffer_is_preserved_and_none_section_is_normalized(self):
        pages = [
            {
                "page": 1,
                "text": "Short intro.\n\n" + ("B" * 130),
                "section": None,
            }
        ]

        chunks = chunk_pages(
            pages,
            chunk_size=100,
            overlap=20,
            doc_prefix="benz_e300",
            doc_title="Mercedes-Benz E300 Owner's Manual",
        )

        joined_text = "\n".join(chunk["text"] for chunk in chunks)

        self.assertIn("Short intro.", joined_text)
        self.assertTrue(all(chunk["section"] == "" for chunk in chunks))

    def test_long_paragraph_preserves_final_unique_tail(self):
        long_paragraph = "".join(f"part{i:02d}-" for i in range(36)) + "FINAL-TAIL-XYZ"
        pages = [{"page": 1, "text": long_paragraph, "section": "Overview"}]

        chunks = chunk_pages(
            pages,
            chunk_size=100,
            overlap=20,
            doc_prefix="benz_e300",
            doc_title="Mercedes-Benz E300 Owner's Manual",
        )

        self.assertTrue(any("FINAL-TAIL-XYZ" in chunk["text"] for chunk in chunks))

    def test_parser_flow_propagates_active_section_to_continuation_pages(self):
        from scripts import parse_pdf_corpus

        pages = [
            {"page": 1, "text": "一、 概述\n" + ("A" * 80)},
            {"page": 2, "text": "Continuation text on the next page that should keep the active section."},
        ]

        page_chunks = parse_pdf_corpus.build_page_chunks(pages)
        chunks = chunk_pages(
            page_chunks,
            chunk_size=100,
            overlap=20,
            doc_prefix="fin",
            doc_title="Sample Report",
        )

        self.assertEqual(chunks[1]["pages"], [2])
        self.assertEqual(chunks[1]["section"], "一、 概述")

    def test_chunk_size_counts_newline_separator_when_joining_paragraphs(self):
        pages = [
            {
                "page": 1,
                "text": ("A" * 50) + "\n\n" + ("B" * 50),
                "section": "Overview",
            }
        ]

        chunks = chunk_pages(
            pages,
            chunk_size=100,
            overlap=20,
            doc_prefix="benz_e300",
            doc_title="Mercedes-Benz E300 Owner's Manual",
        )

        self.assertEqual(len(chunks), 2)
        self.assertTrue(all(len(chunk["text"]) <= 100 for chunk in chunks))


if __name__ == "__main__":
    unittest.main()

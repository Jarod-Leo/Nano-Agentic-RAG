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


if __name__ == "__main__":
    unittest.main()

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

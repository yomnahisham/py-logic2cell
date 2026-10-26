import unittest

from src.hd.classes import (
    canonical_truth_table,
    npn_canonical_truth_table,
    npn_class_count,
    p_class_id,
)


class ClassTests(unittest.TestCase):
    def test_input_permutation_has_same_class(self):
        self.assertEqual(p_class_id(0x2, 2), p_class_id(0x4, 2))

    def test_canonicalization_is_deterministic(self):
        self.assertEqual(canonical_truth_table(0x8, 2), 0x8)
        self.assertEqual(canonical_truth_table(0xE8, 3), 0xE8)

    def test_invalid_width_is_rejected(self):
        with self.assertRaises(ValueError):
            canonical_truth_table(0x10, 2)

    def test_npn_canonicalization(self):
        self.assertEqual(npn_canonical_truth_table(0x8, 2), 0x1)
        self.assertEqual(npn_canonical_truth_table(0x7, 2), 0x1)
        self.assertEqual(npn_class_count(4), 222)


if __name__ == "__main__":
    unittest.main()

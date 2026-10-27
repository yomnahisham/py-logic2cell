import unittest

from src.hd.classes import (
    canonical_truth_table,
    is_single_stage,
    npn_canonical_truth_table,
    npn_class_count,
    p_class_id,
)


class ClassTests(unittest.TestCase):
    def test_single_stage_negative_unate_functions(self):
        self.assertTrue(is_single_stage(0x7, 2))  # NAND
        self.assertTrue(is_single_stage(0x1, 2))  # NOR
        self.assertFalse(is_single_stage(0x8, 2))  # AND
        self.assertFalse(is_single_stage(0x6, 2))  # XOR

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

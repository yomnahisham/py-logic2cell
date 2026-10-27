import unittest

from src.hd.liberty import parse_liberty
from src.hd.redundancy import _classify
from src.hd.selftest import depends_on_all_four_inputs, full_support_p_classes


LIBERTY = r'''
library ("test") {
  cell ("and2") {
    pin ("A") { direction : "input"; }
    pin ("B") { direction : "input"; }
    pin ("Y") { direction : "output"; function : "A & B"; }
  }
  cell ("and5") {
    pin ("A") { direction : "input"; }
    pin ("B") { direction : "input"; }
    pin ("C") { direction : "input"; }
    pin ("D") { direction : "input"; }
    pin ("E") { direction : "input"; }
    pin ("Y") { direction : "output"; function : "A & B & C & D & E"; }
  }
  cell ("inv") {
    pin ("A") { direction : "input"; }
    pin ("Y") { direction : "output"; function : "!A"; }
  }
}
'''


class RedundancyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cells = tuple(parse_liberty(LIBERTY))

    def test_exact_exists(self):
        self.assertEqual(_classify(0x8888, self.cells)[0], "exists")

    def test_input_inversion_is_exists_inv(self):
        self.assertEqual(_classify(0x4444, self.cells)[0], "exists_inv")

    def test_constant_is_contained(self):
        self.assertEqual(_classify(0xFFFF, self.cells)[0], "contained")
        self.assertEqual(_classify(0x0000, self.cells)[0], "contained")

    def test_higher_input_cell_allows_repeated_candidate_inputs(self):
        self.assertEqual(_classify(0x8000, self.cells)[0], "contained")

    def test_unmatched_function_is_new(self):
        self.assertEqual(_classify(0x6996, self.cells)[0], "new")

    def test_invalid_candidate(self):
        with self.assertRaises(ValueError):
            _classify(-1, self.cells)

    def test_full_support_class_enumeration(self):
        classes = full_support_p_classes()
        self.assertEqual(len(classes), 3904)
        self.assertTrue(all(depends_on_all_four_inputs(table) for table in classes))


if __name__ == "__main__":
    unittest.main()

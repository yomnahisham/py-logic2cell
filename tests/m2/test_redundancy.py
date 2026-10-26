import unittest

from src.hd.liberty import parse_liberty
from src.hd.redundancy import _classify


LIBERTY = r'''
library ("test") {
  cell ("and2") {
    pin ("A") { direction : "input"; }
    pin ("B") { direction : "input"; }
    pin ("Y") { direction : "output"; function : "A & B"; }
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

    def test_unmatched_function_is_new(self):
        self.assertEqual(_classify(0x6996, self.cells)[0], "new")

    def test_invalid_candidate(self):
        with self.assertRaises(ValueError):
            _classify(-1, self.cells)


if __name__ == "__main__":
    unittest.main()

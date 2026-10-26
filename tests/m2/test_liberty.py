import unittest

from src.hd.liberty import LibertySyntaxError, parse_liberty, truth_table


class LibertyTests(unittest.TestCase):
    def test_truth_table_convention(self):
        examples = (
            ("A", 0x2),
            ("!A", 0x1),
            ("A & B", 0x8),
            ("(!A) | (!B)", 0x7),
            ("(A & !B) | (!A & B)", 0x6),
            ("A B", 0x8),
            ("A ^ B", 0x6),
            ("A'", 0x1),
        )
        for expression, expected in examples:
            with self.subTest(expression=expression):
                _, table = truth_table(expression)
                self.assertEqual(table, expected)

    def test_four_input_and(self):
        support, table = truth_table("A & B & C & D")
        self.assertEqual(support, ("A", "B", "C", "D"))
        self.assertEqual(table, 0x8000)

    def test_liberty_filters_ineligible_groups(self):
        text = r'''
    library ("test") {
      cell ("good") {
        area : 1.0;
        pin ("A") { direction : input; }
        pin ("Y") { direction : output; function : "(!A)"; }
      }
      cell ("sequential") {
        ff ("IQ", "IQN") { next_state : "D"; }
        pin ("D") { direction : input; }
        pin ("IQ") { direction : output; function : "D"; }
      }
      cell ("multi") {
        pin ("A") { direction : input; }
        pin ("Y") { direction : output; function : "A"; }
        pin ("Z") { direction : output; function : "!A"; }
      }
      cell ("tri") {
        pin ("A") { direction : input; }
        pin ("TE_B") { direction : input; }
        pin ("Y") {
          direction : output;
          function : "A";
          three_state : "TE_B";
        }
      }
    }
    '''
        cells = parse_liberty(text)
        self.assertEqual(
            [(cell.name, cell.truth_table) for cell in cells],
            [("good", 0x1)],
        )
        self.assertEqual(cells[0].area, 1.0)

    def test_invalid_expression_is_explicit(self):
        with self.assertRaises(LibertySyntaxError):
            truth_table("A &")


if __name__ == "__main__":
    unittest.main()

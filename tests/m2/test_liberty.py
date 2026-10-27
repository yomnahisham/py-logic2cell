import pytest

from src.hd.liberty import LibertySyntaxError, parse_liberty, truth_table


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("A", 0x2),
        ("!A", 0x1),
        ("A & B", 0x8),
        ("(!A) | (!B)", 0x7),
        ("(A & !B) | (!A & B)", 0x6),
        ("A B", 0x8),
        ("A ^ B", 0x6),
        ("A'", 0x1),
    ],
)
def test_truth_table_convention(expression, expected):
    _, table = truth_table(expression)
    assert table == expected


def test_four_input_and():
    support, table = truth_table("A & B & C & D")
    assert support == ("A", "B", "C", "D")
    assert table == 0x8000


def test_liberty_filters_ineligible_groups():
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
    assert [(cell.name, cell.truth_table) for cell in cells] == [("good", 0x1)]
    assert cells[0].area == 1.0


def test_invalid_expression_is_explicit():
    with pytest.raises(LibertySyntaxError):
        truth_table("A &")

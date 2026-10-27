import csv
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

# Table 1 of the option 2 handout (Yosys 0.33): (A usable, A reduced, B usable, B reduced)
HANDOUT = {
    "cpu8": (4186.5, 4186.5, 4367.9, 4359.2),
    "dsp8": (5928.2, 5928.2, 6217.2, 6214.7),
    "arlet6502": (9654.3, 9701.8, 9954.5, 9995.8),
    "uart_apb": (12948.7, 12948.7, 13180.1, 13180.1),
    "risc8": (28265.9, 28263.4, 27501.4, 27511.4),
    "fir10": (25968.7, 25968.7, 29055.4, 29055.4),
}


def rows():
    with (ROOT / "results/table1.csv").open() as f:
        return {(r["design"], r["script"], r["library"]): float(r["area_um2"]) for r in csv.DictReader(f)}


@pytest.mark.parametrize("design", HANDOUT)
def test_table1_matches_handout(design):
    got = rows()
    keys = [("A", "usable"), ("A", "reduced"), ("B", "usable"), ("B", "reduced")]
    for (script, lib), want in zip(keys, HANDOUT[design]):
        assert got[(design, script, lib)] == pytest.approx(want, abs=0.06)


def test_reduced_costs_at_most_half_a_percent():
    got = rows()
    for design in HANDOUT:
        for script in "AB":
            assert got[(design, script, "reduced")] <= 1.005 * got[(design, script, "usable")]

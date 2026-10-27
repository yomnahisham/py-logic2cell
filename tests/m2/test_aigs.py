import csv
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

# Table 2 of the option 2 handout: flip-flops and AIG AND nodes
HANDOUT = {"cpu8": (82, 1265), "dsp8": (72, 1973), "arlet6502": (143, 3221),
           "uart_apb": (330, 4673), "risc8": (696, 7750), "fir10": (176, 8795)}


@pytest.mark.parametrize("design", HANDOUT)
def test_aig_sizes_match_table2(design):
    with (ROOT / "results/aig_sizes.csv").open() as f:
        row = next(r for r in csv.DictReader(f) if r["design"] == design)
    flops, ands = HANDOUT[design]
    assert int(row["latches"]) == flops + 1      # write_aiger -zinit adds one latch for the initial state
    assert int(row["ands_raw"]) == ands
    assert int(row["ands_abc"]) < ands

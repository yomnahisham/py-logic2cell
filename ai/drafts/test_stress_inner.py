"""DRAFT for a member to review and move to tests/ (AGENTS.md: the assistant does not edit tests/).

Every gate of a multi-stage cell gets a name in src/cell/stress.py, and the layout's fingers per (type, gate)
are exactly the extracted netlist's transistors per (type, gate). Needs the cells built by `make cells`.
"""

from collections import Counter
from pathlib import Path

import pytest

from src.cell.stress import fingers, inner_gate_nets

CELLS = Path("build/cells")
MULTI = ["dd2_gc1__a21o_1", "dd2_gc1__and2_1", "dd2_gc1__mux2_1", "dd2_gc1__xor2_1", "dd2_gc1__maj3_1",
         "dd2_gc1__or_and_maj"]


def _netlist_counts(netlist: Path) -> Counter:
    count = Counter()
    for line in netlist.read_text().replace("\n+", " ").splitlines():
        tok = line.split()
        if tok and tok[0][0] in "Xx" and len(tok) > 5 and "fet" in tok[5]:
            count["p" if "pfet" in tok[5] else "n", tok[2].split(".")[0]] += 1
    return count


@pytest.mark.parametrize("name", MULTI)
def test_every_gate_named_like_the_netlist(name):
    folder = CELLS / name
    if not (folder / f"{name}.gds").exists():
        pytest.skip(f"{name} not built")
    netlist = folder / f"{name}_pex.spice"
    inner = inner_gate_nets(netlist)
    assert inner, f"{name} is multi-stage, so it must have an inner gate net"
    found = fingers(folder / f"{name}.gds", name, inner)
    assert all(f["gate"] != "?" for f in found)
    assert Counter((f["kind"], f["gate"]) for f in found) == _netlist_counts(netlist)


def test_wrong_inner_name_fails():
    """Broken case: a net name that points at no unlabelled net must stop the flow, not give a '?' gate."""
    name = "dd2_gc1__a21o_1"
    folder = CELLS / name
    if not (folder / f"{name}.gds").exists():
        pytest.skip(f"{name} not built")
    with pytest.raises(ValueError, match="unlabelled nets"):
        fingers(folder / f"{name}.gds", name, ["a_1_1"])


def test_same_width_fingers_matched_by_position(tmp_path):
    """xor2: input A drives two nfets of the same width with different SA/SB; each netlist device must get the
    finger at its own position in Magic's .res.ext."""
    from src.cell.stress import annotate, device_positions
    name = "dd2_gc1__xor2_1"
    folder = CELLS / name
    if not (folder / f"{name}.gds").exists():
        pytest.skip(f"{name} not built")
    netlist = folder / f"{name}_pex.spice"
    found = fingers(folder / f"{name}.gds", name, inner_gate_nets(netlist))
    with pytest.raises(ValueError, match="different SA/SB"):
        annotate(netlist, found, tmp_path / "no_positions.spice")          # without positions it must refuse
    given = annotate(netlist, found, tmp_path / "sasb.spice", device_positions(folder / f"{name}.res.ext"))
    assert len({(d["kind"], d["gate"], d["sa"], d["sb"]) for d in given}) == len(given)

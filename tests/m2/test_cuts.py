"""Cut enumerator: truth tables built by merging, checked by simulating each cut."""

from pathlib import Path

import pytest

from src.cut_enum import cut_enumerator
from src.cut_enum.cut_enumerator import CutEnumerator

ROOT = Path(__file__).resolve().parents[2]

# y = a xor b as three ANDs: 3 = a&b, 4 = !a&!b, 5 = !3 & !4
XOR = "aag 5 2 0 1 3\n2\n4\n10\n6 2 4\n8 3 5\n10 7 9\n"


@pytest.fixture(scope="module")
def cpu8():
    path = ROOT / "build/aigs/cpu8_raw.aig"
    if not path.exists():
        from src.aig.aigs import write
        path.parent.mkdir(parents=True, exist_ok=True)
        write("cpu8", "cpu8")
    return CutEnumerator(path)


def test_xor(tmp_path):
    (tmp_path / "x.aag").write_text(XOR)
    e = CutEnumerator(tmp_path / "x.aag")
    cuts = e.enumerate_cuts(4)
    assert cuts[5][(1, 2)] == 0b0110
    assert cuts[3][(1, 2)] == 0b1000
    assert cuts[4][(1, 2)] == 0b0001


def test_every_cut_of_cpu8_checks(cpu8):
    cuts = cpu8.enumerate_cuts(4)
    assert sum(len(c) for c in cuts.values()) > 10000
    assert cpu8.check(cuts) == []


def test_broken_wrong_truth_table(cpu8):
    cuts = cpu8.enumerate_cuts(4)
    node, (cut, table) = next((n, item) for n, c in cuts.items() if n in cpu8.ands
                              for item in c.items() if len(item[0]) == 4)
    cuts[node][cut] = table ^ 1
    assert cpu8.check(cuts) == [(node, cut)]


def test_broken_merge_ignores_inverted_edges(cpu8, monkeypatch):
    ands = {n: (l, 0, r, 0) for n, (l, li, r, ri) in cpu8.ands.items()}
    monkeypatch.setattr(cpu8, "ands", ands)
    cuts = cpu8.enumerate_cuts(4)
    monkeypatch.undo()
    assert cpu8.check(cuts) != []


def test_broken_keeps_dominated_cuts(cpu8, monkeypatch):
    monkeypatch.setattr(CutEnumerator, "drop_dominated", staticmethod(lambda cuts: cuts))
    assert cpu8.check(cpu8.enumerate_cuts(4)) != []

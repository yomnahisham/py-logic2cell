"""Cut files (src/cut_enum/write_cuts.py): the format src/hd/cut_classes.py reads."""

import csv

import pytest

from src.cut_enum.cut_enumerator import CutEnumerator
from src.cut_enum.write_cuts import COLUMNS, cone_size, write
from src.hd.cut_classes import npn_class, pn_class, read

# y = a xor b as three ANDs: 3 = a&b, 4 = !a&!b, 5 = !3 & !4
XOR = "aag 5 2 0 1 3\n2\n4\n10\n6 2 4\n8 3 5\n10 7 9\n"


@pytest.fixture
def xor_dir(tmp_path):
    (tmp_path / "x_raw.aag").write_text(XOR)
    return tmp_path


def rows(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def test_columns_and_cuts_of_xor(xor_dir):
    n = write("x", "raw", src=xor_dir, out=xor_dir / "cuts")
    r = rows(xor_dir / "cuts/x_raw.csv")
    assert n == len(r) == 4                                  # no trivial cuts
    assert list(r[0]) == COLUMNS
    got = {(int(x["root"]), x["leaves"]): (x["truth_table"], int(x["cone_size"])) for x in r}
    assert got[(3, "1 2")] == ("0x8", 1)                     # and
    assert got[(4, "1 2")] == ("0x1", 1)                     # nor
    assert got[(5, "1 2")] == ("0x6", 3)                     # xor over the inputs, three ANDs
    assert got[(5, "3 4")] == ("0x1", 1)                     # nor of the two inner nodes


def test_cone_size(xor_dir):
    e = CutEnumerator(xor_dir / "x_raw.aag")
    assert cone_size(e.ands, 5, (1, 2)) == 3
    assert cone_size(e.ands, 5, (3, 4)) == 1
    assert cone_size(e.ands, 5, (5,)) == 0                   # a node is its own leaf


def test_cut_classes_reads_the_files(xor_dir):
    write("x", "raw", src=xor_dir, out=xor_dir / "cuts")
    aig = read([xor_dir / "cuts/x_raw.csv"])[("x", "raw")]
    assert (aig.cuts, aig.dropped) == (4, 0)
    assert len(aig.classes) == 3                             # and, nor, xor
    nor = aig.classes[(2, pn_class(0x1, 2))]
    assert nor.count == 2 and set(nor.roots) == {4, 5}       # roots 4 and 5 are one class
    assert npn_class(0x8, 2) == npn_class(0x1, 2)            # NPN frees the input inverters


def test_missing_aig_names_the_fix(tmp_path):
    with pytest.raises(FileNotFoundError, match="src.aig.aigs"):
        write("none", "raw", src=tmp_path, out=tmp_path)


def test_broken_wrong_truth_table_stops_the_run(xor_dir, monkeypatch):
    real = CutEnumerator.enumerate_cuts

    def corrupt(self, k=4):
        cuts = real(self, k)
        cuts[5][(1, 2)] ^= 1                                  # flip one bit of the xor table
        return cuts

    monkeypatch.setattr(CutEnumerator, "enumerate_cuts", corrupt)
    with pytest.raises(AssertionError, match="disagree with simulation"):
        write("x", "raw", src=xor_dir, out=xor_dir / "cuts")
    assert not (xor_dir / "cuts/x_raw.csv").exists()          # nothing half-written
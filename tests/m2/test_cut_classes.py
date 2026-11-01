"""Classes of cut truth tables (src/hd/cut_classes.py)."""

from src.hd.cut_classes import npn_class, pn_class, read, reduce_support

CSV = """design,aig,root,leaves,truth_table,cone_size
d,abc,10,1 2,0x8,1
d,abc,10,1 2 3,0x88,2
d,abc,11,4 5,0x7,1
d,abc,12,1 2,0x6,3
d,abc,13,1 2,0xa,1
"""


def test_reduce_support_drops_unused_inputs():
    # A & C over leaves (A, B, C): B unused
    assert reduce_support(0xA0, 3) == (0x8, 2)
    assert reduce_support(0xAA, 3) == (0x2, 1)


def test_class_is_up_to_order_and_output_inversion():
    assert pn_class(0x8, 2) == pn_class(0x7, 2)          # and2, nand2
    assert pn_class(0x2, 2) == pn_class(0x4, 2)          # A & !B, !A & B
    assert pn_class(0x8, 2) != pn_class(0x2, 2)          # input inversion is not free


def test_npn_also_frees_input_inversion():
    assert npn_class(0x8, 2) == npn_class(0x2, 2) == npn_class(0xE, 2)
    assert len({npn_class(t, 2) for t in range(16)}) == 4
    assert len({npn_class(t, 3) for t in range(256)}) == 14


def test_occurrences_count_roots_once(tmp_path):
    (tmp_path / "c.csv").write_text(CSV)
    aig = read([tmp_path / "c.csv"])[("d", "abc")]
    assert (aig.cuts, aig.dropped) == (5, 1)              # 0xa over (1, 2) is a buffer of leaf 1
    and_class = aig.classes[(2, pn_class(0x8, 2))]
    assert and_class.count == 2                           # roots 10 (two cuts, one occurrence) and 11
    assert and_class.roots[10][0] == 1                    # the smaller cone is kept
    assert and_class.polarity_counts() == {0x8: 1, 0x7: 1}   # root 10 is and2, root 11 nand2

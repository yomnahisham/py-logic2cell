"""The redundancy checker against Table 4 of the option 2 handout, on the full HD library."""

import os
from collections import Counter
from itertools import permutations

import pytest

from src.common.stage import single_stage
from src.hd.liberty import parse_liberty_file
from src.hd.redundancy import _classify, _permute_four

PERMS = list(permutations(range(4)))


def depends_on_all(t):
    return all(any((t >> i & 1) != (t >> (i ^ 1 << k) & 1) for i in range(16)) for k in range(4))


@pytest.fixture(scope="module")
def cells():
    return tuple(parse_liberty_file(os.environ["HD_LIB_FULL"]))


@pytest.fixture(scope="module")
def classes(cells):
    """One representative per class up to input order, of the functions that use all 4 inputs."""
    seen, reps = set(), []
    for t in range(1 << 16):
        if t in seen or not depends_on_all(t):
            continue
        orbit = {_permute_four(t, p) for p in PERMS}
        seen |= orbit
        reps.append(min(orbit))
    return {t: _classify(t, cells)[0] for t in reps}


def test_every_hd_cell_exists(cells):
    from src.hd.redundancy import _expand
    for cell in cells:
        if len(cell.support) <= 4:
            assert _classify(_expand(cell.truth_table, len(cell.support)), cells)[0] == "exists", cell.name


def test_class_counts(classes):
    assert Counter(classes.values()) == {"exists": 24, "exists_inv": 20, "contained": 38, "new": 3822}


def test_new_single_stage(classes):
    new = [t for t, c in classes.items() if c == "new"]
    assert sum(single_stage(t, 4, max_series=12) is not None for t in new) == 9


@pytest.mark.xfail(reason="handout says 5; we find 6 (0x0017 0x011F 0x013F 0x037F 0x077F 0x17FF), "
                          "each 12 transistors and 3 in series, see results/table4.txt", strict=True)
def test_new_single_stage_within_limits(classes):
    new = [t for t, c in classes.items() if c == "new"]
    small = [t for t in new if (f := single_stage(t, 4)) is not None and 2 * f.size <= 12]
    assert len(small) == 5


def test_read_once_cells(classes):
    once = Counter(c for t, c in classes.items() if (f := single_stage(t, 4)) is not None and f.size == 4)
    assert once == {"exists": 6, "contained": 2}

"""Baseline mapping logs: the stat format src/hd/rank.py reads."""

import pytest

from src.hd.rank import stat
from src.map_library.table1 import check_log

LOG = """
   Number of cells:                  5
     sky130_fd_sc_hd__dfxtp_1        2
     sky130_fd_sc_hd__nand2_1        3

   Chip area for module '\\cpu8': 85.0800
"""


def test_check_log_and_rank_agree(tmp_path):
    assert check_log(LOG) == (85.08, 5)
    (tmp_path / "x.log").write_text(LOG)
    area, counts = stat(tmp_path / "x.log")
    assert area == 85.08 and counts == {"sky130_fd_sc_hd__dfxtp_1": 2, "sky130_fd_sc_hd__nand2_1": 3}


def test_broken_counts_that_do_not_add_up():
    with pytest.raises(ValueError, match="add up"):
        check_log(LOG.replace("nand2_1        3", "nand2_1        2"))


def test_broken_no_area():
    with pytest.raises(ValueError, match="no chip area"):
        check_log("Number of cells: 3\n")
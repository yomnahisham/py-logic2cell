"""Paths to PDK files and reference cells. Built from the pdk/ and given/ links."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIB = ROOT / "pdk/libs.ref/sky130_fd_sc_hd"

GDS = LIB / "gds/sky130_fd_sc_hd.gds"
LEF = LIB / "lef/sky130_fd_sc_hd.lef"
SPICE = LIB / "spice/sky130_fd_sc_hd.spice"
LIBERTY_TT = LIB / "lib/sky130_fd_sc_hd__tt_025C_1v80.lib"
PLAN_HD = ROOT / "given/plan_hd.json"

PREFIX = "sky130_fd_sc_hd__"
REFERENCE_CELLS = ["inv_1", "nand2_1", "tapvpwrvgnd_1", "fill_1"]

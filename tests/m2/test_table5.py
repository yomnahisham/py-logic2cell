"""Table 5 mapping and CEC checks, including the required broken netlist case."""

import shutil
import subprocess
from pathlib import Path

import pytest

import src.map_library.table5 as table5

ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(
    shutil.which("docker") is None
    or not (ROOT / "given").exists()
    or subprocess.run(
        ["docker", "image", "inspect", "dd2-yosys"],
        capture_output=True,
    ).returncode,
    reason="needs make setup and the dd2-yosys image",
)


def test_table5_columns():
    assert table5.COLUMNS == [
        "design",
        "script",
        "baseline_um2",
        "new_cells_um2",
        "reduction_percent",
        "new_cell_instances",
        "equivalence",
    ]


def test_broken_netlist_cec_rejects(monkeypatch, tmp_path):
    stem = tmp_path / "table5_tiny"
    stat_log = """
       Number of cells:                  1
         sky130_fd_sc_hd__nand2_1        1
       Chip area for module '\\tiny': 1.0
    """

    def fake_run(args, **_):
        assert "delete t:sky130_fd_sc_hd__nand2_1" in args[-1]
        stem.with_suffix(".log").write_text(stat_log)
        return "ABC: Networks are NOT equivalent."

    monkeypatch.setattr(table5, "run", fake_run)
    result = table5.check(
        "build/broken/table5_tiny.v",
        "tiny",
        "given/hd_reduced.lib",
        "A",
        stem,
        tamper="delete t:sky130_fd_sc_hd__nand2_1",
    )
    assert result["equivalent"] is False

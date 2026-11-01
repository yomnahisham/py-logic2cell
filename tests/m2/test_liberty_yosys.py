"""The extended Liberty file in Yosys 0.33, and the Liberty broken cases. Needs docker and make setup."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from src.hd.liberty import _CELL_GROUP, _braced_groups

ROOT = Path(__file__).resolve().parents[2]
BROKEN = ROOT / "build/broken"
SCRIPTS = {"A": "+strash;dch,-f;amap;topo", "B": "+strash;&get,-n;&dch,-f;&nf,-R,1000;&put"}

pytestmark = pytest.mark.skipif(
    shutil.which("docker") is None or not (ROOT / "given").exists()
    or subprocess.run(["docker", "image", "inspect", "dd2-yosys"], capture_output=True).returncode,
    reason="needs make setup and the dd2-yosys image")


@pytest.fixture(scope="module", autouse=True)
def broken():
    subprocess.run(["python3", "tests/broken/make_m2_liberty.py"], cwd=ROOT, check=True)


def yosys(commands: str) -> str:
    from src.common.yosys import run
    return run(["yosys", "-p", commands])


def cells(path: Path) -> int:
    return sum(1 for _ in _braced_groups(path.read_text(), _CELL_GROUP))


def map_maj4n(lib: str, script: str) -> str:
    return yosys(f"read_verilog build/broken/m2_maj4n.v; synth -flatten -top maj4n; dfflibmap -liberty {lib}; "
                 f"abc -liberty {lib} -script {SCRIPTS[script]}; opt_clean -purge; stat -liberty {lib}")


def test_reference_loads_and_script_b_uses_the_cell():
    lib = "build/broken/m2_liberty_ok.lib"
    out = yosys(f"read_liberty {lib}")
    assert re.search(r"Imported (\d+) cell types", out)[1] == str(cells(ROOT / lib))
    assert re.search(r"dd2_g5__maj4n_1\s+1\b", map_maj4n(lib, "B"))


def test_broken_function_syntax_is_rejected():
    with pytest.raises(RuntimeError, match="Parser error in function expr"):
        yosys("read_liberty build/broken/m2_liberty_syntax.lib")


@pytest.mark.parametrize("script", "AB")
def test_broken_unclosed_cell_fails_mapping(script):
    with pytest.raises(RuntimeError, match="ABC"):
        map_maj4n("build/broken/m2_liberty_brace.lib", script)


@pytest.mark.parametrize("script", "AB")
def test_no_timing_still_maps(script):
    """Observed with Yosys 0.33: without timing groups both scripts still map (B uses the cell).
    The handout says ABC's map command crashes without them; neither script uses map, so the
    timing groups are kept for map and for OpenSTA, not because scripts A or B need them."""
    map_maj4n("build/broken/m2_liberty_no_timing.lib", script)


def test_writer_output_loads():
    """What src.hd.liberty_writer wrote: hd_reduced.lib plus every cell of libs/new_cells.lib."""
    lib = ROOT / "build/libs/hd_reduced_ext.lib"
    if not lib.exists():
        pytest.skip("run python -m src.hd.liberty_writer first")
    out = yosys("read_liberty build/libs/hd_reduced_ext.lib")
    expected = cells(ROOT / "given/hd_reduced.lib") + cells(ROOT / "libs/new_cells.lib")
    assert re.search(r"Imported (\d+) cell types", out)[1] == str(expected)

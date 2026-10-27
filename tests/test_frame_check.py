import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(plan=None):
    args = [sys.executable, str(ROOT / "src/frame_check.py")] + ([str(plan)] if plan else [])
    return subprocess.run(args, capture_output=True, text=True)


def test_given_plan_passes():
    assert run().returncode == 0


def test_broken_plan_with_moved_nwell_fails(tmp_path):
    plan = json.loads((ROOT / "given/plan_hd.json").read_text())
    plan["frame"]["nwell"]["y"] = [1.405, 2.91]
    (tmp_path / "plan.json").write_text(json.dumps(plan))
    result = run(tmp_path / "plan.json")
    assert result.returncode == 1
    assert "FAIL: Plan nwell" in result.stdout

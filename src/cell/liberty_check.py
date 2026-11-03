"""Load a Liberty file in Yosys and OpenSTA and report what they say (option 1 handout, Table 5, Liberty syntax).

    python -m src.cell.liberty_check <lib> [<lib> ...]

Yosys 0.33 reads it with read_liberty -lib, as a mapping would; OpenSTA reads it with read_liberty and lists
its cells. A file passes when both tools exit 0, print no error, and see every cell group in the file.
Warnings are reported, not counted as errors. Writes results/liberty_syntax.txt.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from src.cell.tools import STA_IMAGE, YOSYS_IMAGE, run

ROOT = Path(__file__).resolve().parents[2]
ERROR = re.compile(r"\b(error|ERROR|Error)\b")
WARNING = re.compile(r"\b(warning|Warning|WARNING)\b")


def check(lib: Path) -> tuple[list[str], bool]:
    lib = lib.resolve()
    cells = len(re.findall(r'^\s*cell\s*\(', lib.read_text(), re.M))
    log = ROOT / "build/sta" / lib.stem
    lines, ok = [f"{lib.relative_to(ROOT)}: {cells} cell groups"], True

    try:
        out = run("yosys", ["-p", f"read_liberty -lib {lib}"], ROOT, log.with_suffix(".yosys.log"), image=YOSYS_IMAGE)
        m = re.search(r"Imported (\d+) cell types", out)
        seen = int(m[1]) if m else 0
        errors = [l for l in out.splitlines() if ERROR.search(l)]
        warnings = [l for l in out.splitlines() if WARNING.search(l)]
        version = re.search(r"Yosys [\d.]+[^\n]*", out)
        good = not errors and seen == cells
        lines.append(f"  Yosys ({version[0] if version else '?'}): imported {seen} cells, {len(errors)} errors, "
                     f"{len(warnings)} warnings: {'PASS' if good else 'FAIL'}")
        lines += [f"    {l.strip()}" for l in errors + warnings[:10]]
    except RuntimeError as e:
        good = False
        lines.append(f"  Yosys: FAIL, {e}")
    ok &= good

    script = (f"read_liberty {lib}\n"
              f"puts \"CELLS [llength [get_lib_cells */*]]\"\n"
              "exit\n")
    try:
        out = run("sta", ["-no_init", "-no_splash", "-exit"], ROOT, log.with_suffix(".sta.log"), stdin=script,
                  image=STA_IMAGE)
        m = re.search(r"CELLS (\d+)", out)
        seen = int(m[1]) if m else 0
        errors = [l for l in out.splitlines() if ERROR.search(l)]
        warnings = [l for l in out.splitlines() if WARNING.search(l)]
        version = run("sta", ["-version"], ROOT, log.with_suffix(".sta_version.log"), image=STA_IMAGE).strip()
        good = not errors and seen == cells
        lines.append(f"  OpenSTA ({version}): read {seen} cells, {len(errors)} errors, {len(warnings)} warnings: "
                     f"{'PASS' if good else 'FAIL'}")
        lines += [f"    {l.strip()}" for l in errors + warnings[:10]]
    except RuntimeError as e:
        good = False
        lines.append(f"  OpenSTA: FAIL, {e}")
    ok &= good
    return lines, ok


if __name__ == "__main__":
    report, ok = [], True
    for path in sys.argv[1:]:
        lines, good = check(Path(path))
        report += lines
        ok &= good
    report.append(f"Liberty syntax (Table 5): {'PASS' if ok else 'FAIL'}")
    out = ROOT / "results/liberty_syntax.txt"
    out.write_text("\n".join(report) + "\n")
    print("\n".join(report))
    sys.exit(0 if ok else 1)

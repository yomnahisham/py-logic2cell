"""Gate-level simulation of Tutorial 4's SPM and Tutorial 2's multiplier, mapped with the reduced library
and with the library plus the new cells (option 2 handout, section 4, step 9, and section 3).

    python -m src.hd.gls --tut2 <Tutorial 2 folder> --tut4 <Tutorial 4 folder> [--real]
        -> results/gls/mapped.csv    (results/gls_real/ with --real) area, cells, new-cell instances and cec for every mapping
        -> results/gls/gls.csv       one row per netlist and testbench: PASS or FAIL
        -> results/gls/broken.txt    the broken cases: each must make a testbench FAIL
        -> results/gls/gls.txt       the summary the report quotes
        -> build/gls/                sources, netlists, the cell models and the simulation logs

Per design and per script (A, B) and per library (reduced, extended or real) it maps with the commands of
section 2 and proves the netlist equivalent to the RTL with ABC's cec (table5.check), then simulates it with the
tutorials' own testbenches, unmodified (Tutorial 4, section 7): SPM_tb for SPM; mul_tb and mul_exhaustive_tb
(all 65,536 signed input pairs, a proof and not a sample) for the multiplier.

Cell models. HD cells use the PDK's Verilog models, with -DFUNCTIONAL, the behavioural view that works on any
Icarus (the timing view needs Icarus 13: Tutorial 4, section 7). A new cell has no PDK model: its model is built
from the truth table of its request (requests/candidates/<name>.json), or is the cell.v Option 1 delivered with
the cell when there is one. Neither comes from the Liberty file, which is what cec reads on both sides, so a
Liberty `function` that disagrees with the request shows up here and not there.
Only cells that a netlist instantiates are exercised: mapped.csv counts them.

Broken cases (Overview, section 4.3, rule 3), each must make a testbench FAIL, and a compile error does not count:
(1) one xor2_1 (or similar) instance in a mapped netlist is replaced by a cell with another function;
(2) the model of the most used new cell is inverted;
(3) the Liberty `function` of that cell is complemented: ABC maps with it, cec reads the same Liberty on both
    sides and says "equivalent", the simulation does not.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from src.hd.request_writer import OUT as REQUESTS, final_set
from src.map_library.table5 import check, libraries
from src.paths import ROOT

WORK = ROOT / "build/gls"
OUT = ROOT / "results/gls"
HD_VERILOG = Path(os.getenv("HD_VERILOG_DIR", ROOT / "pdk/libs.ref/sky130_fd_sc_hd/verilog"))
HD_MODELS = ["primitives.v", "sky130_fd_sc_hd.v"]

# design -> (tutorial folder option, sources, top, [(testbench module, file)])
DESIGNS = {
    "SPM": ("tut4", ["SPM.v", "CSADD.v", "TCMP.v"], "SPM", [("SPM_tb", "SPM_tb.v")]),
    "mul": ("tut2", ["mul.v"], "mul", [("mul_tb", "mul_tb.v"), ("mul_exhaustive_tb", "mul_exhaustive_tb.v")]),
}
SCRIPT_NAMES = "AB"
# instances whose function a broken case can change without changing the pins (same pin names on both cells)
SWAPS = [("xor2_1", "or2_1"), ("and2_1", "or2_1"), ("xnor2_1", "nor2_1"), ("nand2_1", "nor2_1"), ("nor2_1", "nand2_1")]


# ---------------------------------------------------------------------------------------------------- models

def truth_table_model(request: dict, invert: bool = False) -> str:
    """Verilog for a new cell from its request: Y = TT[{inputs}], A the least significant input."""
    inputs, out = request["inputs"], request["output"]
    width = 2 ** len(inputs)
    tt = int(request["truth_table"], 16)
    if not 0 <= tt < 2 ** width:
        raise ValueError(f"{request['name']}: truth table {request['truth_table']} does not fit {len(inputs)} inputs")
    if invert:
        tt ^= 2 ** width - 1
    ports = ", ".join([*inputs, out])
    index = ", ".join(reversed(inputs))
    return (f"// {request['name']}: function from the truth table of its request{' (INVERTED: broken case)' if invert else ''}\n"
            f"module {request['name']} ({ports});\n"
            f"  input {', '.join(inputs)};\n  output {out};\n"
            f"  localparam [{width - 1}:0] TT = {width}'h{tt:0{(width + 3) // 4}X};\n"
            f"  assign {out} = TT[{{{index}}}];\nendmodule\n")


def cell_models(names: list[str], invert: str | None = None) -> tuple[str, dict[str, str]]:
    """The Verilog of every new cell, and where each model came from (cell.v from Option 1 or the truth table)."""
    text, source = "", {}
    for name in names:
        request = json.loads((REQUESTS / f"{name}.json").read_text())
        response = ROOT / "cells" / name / "response.json"
        verilog = None
        if response.is_file():
            r = json.loads(response.read_text())
            path = (r.get("files") or {}).get("verilog")
            if r.get("status") == "pass" and path and (ROOT / path).is_file():
                verilog = ROOT / path
        if verilog is not None and name != invert:
            text += f"// {name}: cell.v from Option 1\n{verilog.read_text()}\n"
            source[name] = "cell.v"
        else:
            text += truth_table_model(request, invert=(name == invert)) + "\n"
            source[name] = "truth table"
    return text, source


# ---------------------------------------------------------------------------------------------------- simulation

def verdict(returncode: int, output: str) -> bool:
    """A testbench passed if vvp exited 0, printed PASS and no ERROR, MISMATCH or FAIL line."""
    return (returncode == 0 and re.search(r"^\s*PASS", output, re.M) is not None
            and re.search(r"^\s*(ERROR|MISMATCH|FAIL)", output, re.M) is None)


def simulate(top: str, testbench: Path, netlist: Path, models: Path, stem: Path) -> tuple[bool, str]:
    """iverilog + vvp as in Tutorial 4, section 7, with the behavioural cell models (-DFUNCTIONAL)."""
    vvp = Path(f"{stem}.vvp")
    cmd = ["iverilog", "-g2012", "-DFUNCTIONAL", "-s", top, "-o", str(vvp), str(testbench), str(netlist),
           *[str(HD_VERILOG / m) for m in HD_MODELS], str(models)]
    c = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=WORK)
    if c.returncode:
        Path(f"{stem}.log").write_text(c.stdout)
        first = next((l for l in c.stdout.splitlines() if "error" in l.lower()), "")
        return False, f"compile error: {first}"[:160]
    r = subprocess.run(["vvp", str(vvp)], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=WORK, timeout=900)
    Path(f"{stem}.log").write_text(r.stdout)
    last = [l for l in r.stdout.splitlines() if re.match(r"\s*(PASS|FAIL|ERROR|MISMATCH)", l)]
    return verdict(r.returncode, r.stdout), (last[-1].strip() if last else "no PASS or FAIL line")[:160]


def functional_fail(ok: bool, line: str) -> bool:
    """A broken case is caught only by a testbench that ran and failed, never by a compile error."""
    return not ok and not line.startswith("compile error")


def corrupt_function(liberty: str, cell: str) -> str:
    """Broken case 3: complement the `function` of one cell in a Liberty file."""
    start = liberty.index(f'cell ("{cell}")')
    m = re.compile(r'function : "([^"]*)"').search(liberty, start)
    expr = m[1][1:] if m[1].startswith("!") else f"!({m[1]})"
    return liberty[:m.start(1)] + expr + liberty[m.end(1):]


def swap_cell(netlist: str) -> tuple[str, str] | None:
    """Broken case 1: replace the first instance of a swappable cell by one with another function. None if there is none."""
    for cell, other in SWAPS:
        pattern = re.compile(rf"\bsky130_fd_sc_hd__{cell}\b(?=\s+\S+\s*\()")
        if pattern.search(netlist):
            return pattern.sub(f"sky130_fd_sc_hd__{other}", netlist, count=1), f"one {cell} became {other}"
    return None


def new_cell_counts(netlist: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for m in re.finditer(r"^\s*(dd2_\w+)\s+\S+\s*\(", netlist, re.M):
        counts[m[1]] = counts.get(m[1], 0) + 1
    return counts


# ---------------------------------------------------------------------------------------------------- the flow

def stage_sources(args) -> dict[str, list[str]]:
    """Copy the tutorials' files into build/gls/src (the Yosys container only sees the repo), return relative paths."""
    src = WORK / "src"
    src.mkdir(parents=True, exist_ok=True)
    folders = {"tut2": Path(args.tut2), "tut4": Path(args.tut4)}
    paths = {}
    for design, (folder, sources, _, tbs) in DESIGNS.items():
        for name in [*sources, *[f for _, f in tbs]]:
            origin = folders[folder] / name
            if not origin.is_file():
                raise FileNotFoundError(f"{origin}: not found (give --{folder} the Tutorial {folder[-1]} folder)")
            shutil.copy(origin, src / name)
        paths[design] = [f"build/gls/src/{s}" for s in sources]
    return paths


def main(argv: list[str]):
    global OUT
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--tut2", required=True, help="Tutorial 2 folder: mul.v, mul_tb.v, mul_exhaustive_tb.v")
    parser.add_argument("--tut4", required=True, help="Tutorial 4 folder: SPM.v, CSADD.v, TCMP.v, SPM_tb.v")
    parser.add_argument("--real", action="store_true", help="use the real-cell library instead of the estimated one")
    args = parser.parse_args(argv)
    if args.real:
        OUT = ROOT / "results/gls_real"
    for m in HD_MODELS:
        if not (HD_VERILOG / m).is_file():
            sys.exit(f"{HD_VERILOG / m}: not found; make setup links pdk, or set HD_VERILOG_DIR")
    WORK.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    sources = stage_sources(args)
    libs = libraries(args.real)
    names = final_set()
    models_text, model_source = cell_models(names)
    models = WORK / "new_cells_models.v"
    models.write_text(models_text)

    # 1. map and prove equivalence with cec (the same flow as Table 5)
    jobs = [(d, lib, s) for d in DESIGNS for lib in libs for s in SCRIPT_NAMES]

    def job(j):
        design, lib, script = j
        stem = WORK / f"{design}_{lib}_{script}"
        return check(" ".join(sources[design]), DESIGNS[design][2], libs[lib], script, stem)

    with ThreadPoolExecutor(4) as pool:
        mapped = dict(zip(jobs, pool.map(job, jobs)))
    with (OUT / "mapped.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["design", "script", "library", "area_um2", "cells", "new_cell_instances", "cec"])
        for (d, lib, s), r in mapped.items():
            w.writerow([d, s, lib, f"{r['area_um2']:.4f}", r["cells"], r["new_cell_instances"],
                        "pass" if r["equivalent"] else "FAIL"])

    # 2. simulate every netlist with every testbench of its design, unmodified
    rows = []
    for (d, lib, s) in jobs:
        netlist = WORK / f"{d}_{lib}_{s}.v"
        for top, tb in DESIGNS[d][3]:
            ok, line = simulate(top, WORK / "src" / tb, netlist, models, WORK / f"{d}_{lib}_{s}_{top}")
            rows.append({"design": d, "script": s, "library": lib, "testbench": top,
                         "new_cell_instances": mapped[(d, lib, s)]["new_cell_instances"],
                         "result": "PASS" if ok else "FAIL", "last_line": line})
            print(f"{d:4} {lib:9} {s} {top:20} {rows[-1]['result']}  ({rows[-1]['new_cell_instances']} new cells)  {line}")
    with (OUT / "gls.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    # 3. the broken cases: every one must FAIL
    broken = []
    tampered = swap_cell((WORK / "mul_reduced_A.v").read_text())
    if tampered:
        bad = WORK / "broken_swap_mul.v"
        bad.write_text(tampered[0])
        ok, line = simulate("mul_exhaustive_tb", WORK / "src/mul_exhaustive_tb.v", bad, models, WORK / "broken_swap")
        broken.append(("netlist with a swapped cell", tampered[1], functional_fail(ok, line), line))
    else:
        broken.append(("netlist with a swapped cell", "no swappable cell in the netlist", None, ""))
    new_lib = "real" if args.real else "extended"
    best = None
    for (d, lib, s), r in mapped.items():
        if lib == new_lib:
            for cell, n in new_cell_counts((WORK / f"{d}_{lib}_{s}.v").read_text()).items():
                if best is None or n > best[0]:
                    best = (n, cell, d, s)
    if best:
        n, cell, d, s = best
        inverted, _ = cell_models(names, invert=cell)
        bad_models = WORK / "broken_models.v"
        bad_models.write_text(inverted)
        netlist = WORK / f"{d}_{new_lib}_{s}.v"
        results = [simulate(top, WORK / "src" / tb, netlist, bad_models, WORK / f"broken_model_{d}_{top}")
                   for top, tb in DESIGNS[d][3]]
        broken.append(("model of a new cell inverted", f"{cell} ({n} instances in {d}, script {s}); testbenches "
                       f"{', '.join(t for t, _ in DESIGNS[d][3])}", all(functional_fail(*r) for r in results), results[-1][1]))
        # a Liberty whose function for that cell is complemented: ABC maps with it, cec reads the same Liberty on
        # both sides and cannot see it, the simulation (models from the request) must
        bad_lib = WORK / "broken_function.lib"
        bad_lib.write_text(corrupt_function(Path(libs[new_lib]).read_text(), cell))
        stem = WORK / f"broken_function_{d}_{s}"
        r = check(" ".join(sources[d]), DESIGNS[d][2], str(bad_lib.relative_to(ROOT)), s, stem)
        used = new_cell_counts(Path(f"{stem}.v").read_text()).get(cell, 0)
        results = [simulate(top, WORK / "src" / tb, Path(f"{stem}.v"), models, WORK / f"broken_function_{d}_{top}")
                   for top, tb in DESIGNS[d][3]]
        caught = all(functional_fail(*x) for x in results) if used else None
        broken.append(("Liberty function of a new cell complemented",
                       f"{cell} in {d}, script {s}: cec says {'equivalent (blind to it)' if r['equivalent'] else 'not equivalent'}, "
                       f"{used} instances, testbenches {', '.join(t for t, _ in DESIGNS[d][3])}", caught, results[-1][1]))
    else:
        broken.append(("model of a new cell inverted", "no new cell is used by SPM or the multiplier", None, ""))
        broken.append(("Liberty function of a new cell complemented", "no new cell is used by SPM or the multiplier", None, ""))
    lines = [f"{name}: {what} -> {'FAIL as it must' if caught else 'NOT CAUGHT' if caught is False else 'not run'}"
             f"{('  [' + line + ']') if line else ''}" for name, what, caught, line in broken]
    (OUT / "broken.txt").write_text("\n".join(lines) + "\n")

    # 4. the summary
    passed = sum(r["result"] == "PASS" for r in rows)
    cec_ok = all(r["equivalent"] for r in mapped.values())
    summary = [f"gate-level simulation: {passed} of {len(rows)} netlist/testbench runs PASS; cec {'proves all' if cec_ok else 'FAILS on some of'} "
               f"{len(mapped)} mapped netlists equivalent to the RTL",
               f"new cells in the models: {', '.join(f'{n} ({model_source[n]})' for n in names)}",
               "extra cell instances by netlist: " + ", ".join(f"{d} {l} {s}: {r['new_cell_instances']}" for (d, l, s), r in mapped.items() if l == new_lib),
               *lines]
    (OUT / "gls.txt").write_text("\n".join(summary) + "\n")
    print("\n".join(summary))
    if passed != len(rows) or not cec_ok or any(c is False for _, _, c, _ in broken):
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1:])
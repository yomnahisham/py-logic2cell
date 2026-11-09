"""Model level and round trip of a delivered cell (option 1 handout, sections 4.2 level 3 and 3.3).

    python -m src.cell.model_check <request.json>     -> cells/<name>/model_check.json, response checks

Run after src.cell.deliver. Three checks, each against the request's truth table:
  verilog   Icarus Verilog simulates cell.v for every input combination;
  liberty   the function attribute of cell.lib, evaluated for every input combination;
  round     the round trip of 3.3: cell.lib's cell group appended inside hd_reduced.lib, a one-cell design
            (assign Y = expression) mapped with scripts A and B of given/scripts/map.sh, and ABC's cec
            between the design and each mapped netlist ("free"). ABC uses our cell there only when it is the
            cheapest cover, so the same design is also mapped onto our cell with only HD's inv_1, buf_1 and nand2_1
            beside it ("forced"). It passes when both free maps are equivalent and at least one map, free
            or forced, is our cell alone (one instance, nothing else) and equivalent: a cell whose Liberty
            function is not the request's can be used, with inverters around it, but never alone.
            chosen_freely says whether ABC picked our cell with the whole reduced library to choose from.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

from src.common.request import read_request
from src.hd.liberty import parse_function
from src.hd.liberty_writer import extend
from src.map_library.table1 import LIBS
from src.map_library.table5 import check
from src.paths import PREFIX

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "build/model"
FORCED_HD = ("inv_1", "buf_1", "nand2_1")


def verilog_table(verilog: Path, name: str, inputs: list[str], output: str, work: Path) -> int:
    """The truth table cell.v gives, from an Icarus run over every input combination."""
    n = len(inputs)
    tb = [f"module tb; reg [{n - 1}:0] x; wire y;",
          f"  {name} dut ({', '.join(f'.{p}(x[{k}])' for k, p in enumerate(inputs))}, .{output}(y));",
          f"  integer i; initial begin for (i = 0; i < {1 << n}; i = i + 1) begin x = i; #1 $display(\"%0d %b\", i, y); end end",
          "endmodule"]
    work.mkdir(parents=True, exist_ok=True)
    (work / "tb.v").write_text("\n".join(tb) + "\n")
    subprocess.run(["iverilog", "-o", str(work / "tb.vvp"), str(work / "tb.v"), str(verilog)], check=True,
                   capture_output=True, text=True)
    out = subprocess.run(["vvp", "-n", str(work / "tb.vvp")], check=True, capture_output=True, text=True).stdout
    table = 0
    for i, y in re.findall(r"^(\d+) ([01xz])$", out, re.M):
        if y not in "01":
            raise ValueError(f"{verilog}: Y is {y} for input combination {i}")
        table |= int(y) << int(i)
    if len(re.findall(r"^\d+ ", out, re.M)) != 1 << n:
        raise ValueError(f"{verilog}: the simulation printed {out!r}")
    return table


def cell_group(lib: str, name: str) -> str:
    """The text of cell group `name` in a Liberty file, braces matched."""
    start = re.search(rf'^\s*cell\s*\(\s*"?{re.escape(name)}"?\s*\)\s*\{{', lib, re.M)
    if not start:
        raise ValueError(f"no cell group {name}")
    depth = 0
    for i in range(start.end() - 1, len(lib)):
        depth += {"{": 1, "}": -1}.get(lib[i], 0)
        if depth == 0:
            return lib[start.start():i + 1] + "\n"
    raise ValueError(f"cell group {name} is not closed")


def liberty_table(lib: str, name: str, inputs: list[str]) -> int:
    """The truth table of the function attribute of cell `name`, over the request's input order."""
    function = re.search(r'function\s*:\s*"([^"]+)"', cell_group(lib, name))
    _, evaluate = parse_function(function[1])
    return sum(evaluate({p: bool(i >> k & 1) for k, p in enumerate(inputs)}) << i for i in range(1 << len(inputs)))


def round_trip(lib: str, request, work: Path) -> dict:
    """Map a one-cell design onto hd_reduced.lib plus our cell with scripts A and B; cec each result."""
    work.mkdir(parents=True, exist_ok=True)
    library = work / "hd_reduced_plus.lib"
    library.write_text(extend((ROOT / LIBS["reduced"]).read_text(), cell_group(lib, request.name)))
    expr = request.expression.replace("!", "~")
    design = work / "one_cell.v"
    design.write_text(f"module one_cell ({', '.join(request.inputs)}, {request.output});\n"
                      + "".join(f"  input {p};\n" for p in request.inputs)
                      + f"  output {request.output};\n  assign {request.output} = {expr};\nendmodule\n")
    # forced: our cell with only HD's inv_1, buf_1 and nand2_1 beside it (enough for ABC to map anything), so a
    # cell that HD already has smaller, or that HD cells cover more cheaply, still shows it maps and passes cec
    reduced = (ROOT / LIBS["reduced"]).read_text()
    head = reduced[:re.search(r'^\s*cell\s*\(', reduced, re.M).start()]
    forced = work / "forced.lib"
    forced.write_text(head + "".join(cell_group(reduced, PREFIX + c) for c in FORCED_HD) + cell_group(lib, request.name) + "}\n")
    out = {}
    for mode, path in (("free", library), ("forced", forced)):
        for script in "AB":
            r = check(str(design.relative_to(ROOT)), "one_cell", str(path.relative_to(ROOT)), script,
                      work / f"map_{mode}_{script}")
            out[f"{mode}_{script}"] = dict(equivalent=r["equivalent"], our_cell_instances=r["new_cell_instances"],
                                           cells=r["cells"], area_um2=r["area_um2"])
    used = [k for k, v in out.items() if v["our_cell_instances"] == v["cells"] == 1 and v["equivalent"]]
    out["chosen_freely"] = any(out[f"free_{s}"]["our_cell_instances"] for s in "AB")
    out["pass"] = all(out[f"free_{s}"]["equivalent"] for s in "AB") and bool(used)
    return out


def model_check(request_path: Path, verilog: Path | None = None, lib: str | None = None, trip: bool = True) -> dict:
    request = read_request(request_path)
    folder = ROOT / "cells" / request.name
    lib = lib or (folder / "cell.lib").read_text()
    work = WORK / request.name
    inputs = list(request.inputs)
    v = verilog_table(verilog or folder / "cell.v", request.name, inputs, request.output, work)
    l = liberty_table(lib, request.name, inputs)
    width = max(1, (1 << len(inputs)) // 4)
    result = dict(cell=request.name, truth_table=f"0x{request.truth_table:0{width}x}",
                  verilog=dict(table=f"0x{v:0{width}x}", match=v == request.truth_table),
                  liberty=dict(table=f"0x{l:0{width}x}", match=l == request.truth_table))
    result["model"] = "pass" if v == l == request.truth_table else "fail"
    if trip:
        result["round_trip"] = round_trip(lib, request, work)
    return result


def record(request_path: Path) -> dict:
    """model_check, written to cells/<name>/model_check.json and to the response's checks."""
    r = model_check(request_path)
    folder = ROOT / "cells" / r["cell"]
    (folder / "model_check.json").write_text(json.dumps(r, indent=2) + "\n")
    response = json.loads((folder / "response.json").read_text())
    response["checks"].update(model=r["model"], round_trip="pass" if r["round_trip"]["pass"] else "fail")
    response["files"]["model_check"] = f"cells/{r['cell']}/model_check.json"
    (folder / "response.json").write_text(json.dumps(response, indent=2) + "\n")
    return r


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("request", type=Path)
    r = record(ap.parse_args().request.resolve())
    rt = r["round_trip"]
    print(f"{r['cell']}: request {r['truth_table']}, cell.v {r['verilog']['table']}, cell.lib {r['liberty']['table']}: "
          f"model {r['model']}")
    for k in ("free_A", "free_B", "forced_A", "forced_B"):
        print(f"  {k}: cec {'equivalent' if rt[k]['equivalent'] else 'NOT equivalent'}, "
              f"{rt[k]['our_cell_instances']} of our cell, {rt[k]['cells']} cells, {rt[k]['area_um2']} um2")
    print(f"  round trip: {'pass' if rt['pass'] else 'fail'}, chosen freely by ABC: {'yes' if rt['chosen_freely'] else 'no'}")
    raise SystemExit(0 if r["model"] == "pass" and rt["pass"] else 1)

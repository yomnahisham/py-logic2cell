"""One Boolean function through the whole Option 1 flow: request, build, deliver, model check.

    python -m src.cell.run_expression "<expression>" [--name myfunc] [--inputs A B C] [--output Y]
                                      [--sizing hd|stack] [--hd <HD cell to compare with>]

1. Writes the cell request (overview, Appendix A) to build/requests/<name>.json. The truth table is computed
   by the request reader's own truth_table(), and the request is checked with parse_request(), so the flow
   accepts it. The inputs default to the names in the expression, sorted; their order sets the bit order
   (the first input is bit 0). The name defaults to expr_<truth table>.
2. build    (src.cell.build): network, switch-level check, Euler order, layout, DRC, LVS, RC-LVS, abutment,
            layer check, DC and transient simulation of the extracted netlist.
3. deliver  (src.cell.deliver): characterization, cell.lib and cell.v. Only if the build passed.
4. model check (src.cell.model_check): Icarus on cell.v, the Liberty function, the round trip with ABC cec.
5. picture  cells/dd2_gc1__<name>/cell.png, the layout in the layer colours of the vs_hd pictures
            (src.cell.compare.picture), opened unless --no-show.
Prints the request and the final response. The cell is written to cells/dd2_gc1__<name>/ as with any request.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from src.cell.build import build
from src.cell.compare import load, picture
from src.cell.deliver import deliver
from src.cell.model_check import record
from src.common.request import RequestError, parse_request, truth_table
from src.hd.liberty import LibertySyntaxError, parse_function

ROOT = Path(__file__).resolve().parents[2]
CELL_PREFIX = "dd2_gc1__"


def make_request(expression: str, name: str | None, inputs: list[str] | None, output: str, sizing: str) -> dict:
    if inputs is None:
        try:
            inputs = sorted(parse_function(expression)[0])
        except LibertySyntaxError as error:
            raise RequestError("fail", f"cannot parse expression: {error}") from None
    table = truth_table(expression, tuple(inputs))
    digits = max(1, (1 << len(inputs)) // 4)
    short = (name or f"expr_{table:0{digits}x}").removeprefix(CELL_PREFIX)
    data = {"request_id": f"EXPR-{short}", "name": CELL_PREFIX + short, "inputs": list(inputs), "output": output,
            "expression": expression, "truth_table": f"0x{table:0{digits}X}", "sizing": sizing}
    parse_request(data)      # raises RequestError with the reader's reason if the flow would refuse it
    return data


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("expression", help="Boolean expression with ! & | ^ and parentheses, e.g. '!(A & B)'")
    ap.add_argument("--name", help="cell name, with or without the dd2_gc1__ prefix (default expr_<truth table>)")
    ap.add_argument("--inputs", nargs="+", help="input order (default: the expression's names, sorted)")
    ap.add_argument("--output", default="Y")
    ap.add_argument("--sizing", default="hd", choices=["hd", "stack"])
    ap.add_argument("--hd", help="installed HD cell to compare with, e.g. nand2_1 (adds vs_hd.png)")
    ap.add_argument("--no-show", action="store_true", help="write cell.png without opening it")
    args = ap.parse_args()

    try:
        request = make_request(args.expression, args.name, args.inputs, args.output, args.sizing)
    except RequestError as error:
        print(f"request refused ({error.status}): {error.reason}")
        return 1
    path = ROOT / "build/requests" / f"{request['name'].removeprefix(CELL_PREFIX)}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(request, indent=2) + "\n")

    print(f"== build {request['name']}", flush=True)
    response = build(path, args.hd)
    if response["status"] == "pass":
        print(f"== deliver {request['name']}", flush=True)
        deliver(path)
        print(f"== model check {request['name']}", flush=True)
        record(path)
        response = json.loads((ROOT / "cells" / request["name"] / "response.json").read_text())

    gds = ROOT / "cells" / request["name"] / "cell.gds"
    if gds.exists():
        png = gds.with_name("cell.png")
        picture(png, [(f"{request['name']}:  {request['output']} = {request['expression']}", load(gds))])
        print(f"\n== layout: {png.relative_to(ROOT)}")
        if not args.no_show and sys.platform == "darwin":
            subprocess.run(["open", str(png)], check=False)

    print(f"\n== request ({path.relative_to(ROOT)})\n{json.dumps(request, indent=2)}")
    print(f"\n== response (cells/{request['name']}/response.json)\n{json.dumps(response, indent=2)}")
    checks = response.get("checks", {})
    return 0 if response["status"] == "pass" and all(v not in ("fail", "mismatch") for v in checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())

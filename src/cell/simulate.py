"""Transistor-level simulation of the RC-extracted netlist (option 1 handout, section 4.2).

DC: the operating point of every input combination.
Transient: from every input state, toggle each input once. Y must settle within
10% of the right rail before the next edge, and never cross VDD/2 when it
should not change. Slew and load are the HD table point nearest 100 ps and 10 fF.

    python -m src.cell.simulate build/cells/<name> <truth table hex>
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from src.cell.tools import MODELS, run
from src.paths import LIBERTY_TT

VDD = 1.8
TEMP = 25
STEP = 2.0   # ns per input vector


def hd_point(slew_target=0.1, load_target=0.01):
    """Slew (20-80%, ns) and load (pF) from the inv_1 delay table of the HD Liberty."""
    text = LIBERTY_TT.read_text()
    cell = text[text.index('cell ("sky130_fd_sc_hd__inv_1")'):]
    table = cell[cell.index("cell_rise"):]
    index = [list(map(float, re.search(rf'index_{k}\("([^"]+)"\)', table)[1].split(","))) for k in (1, 2)]
    lower = float(re.search(r"slew_lower_threshold_pct_rise\s*:\s*([\d.]+)", text)[1])
    upper = float(re.search(r"slew_upper_threshold_pct_rise\s*:\s*([\d.]+)", text)[1])
    slew = min(index[0], key=lambda v: abs(v - slew_target))
    load = min(index[1], key=lambda v: abs(v - load_target))
    return slew, load, (upper - lower) / 100


def ports(folder: Path, name: str) -> list[str]:
    text = (folder / f"{name}_pex.spice").read_text()
    return re.search(rf"(?im)^\.subckt\s+{name}\s+(.+)", text)[1].split()


def instance(folder, name, inputs, output):
    nets = {p: p for p in ports(folder, name)}
    nets.update(VGND="0", VNB="0", VPWR="VPWR", VPB="VPWR")
    return f"XU {' '.join(nets[p] for p in ports(folder, name))} {name}"


def dc(folder: Path, name: str, inputs: list[str], output: str, table: int) -> list[dict]:
    deck = [f"* {name} DC", f'.lib "{MODELS}" tt', f'.include "{name}_pex.spice"', f".temp {TEMP}",
            f"VPWR VPWR 0 {VDD}"] + [f"V{p} {p} 0 0" for p in inputs]
    deck += [instance(folder, name, inputs, output), ".control"]
    for i in range(1 << len(inputs)):
        deck += [f"alter V{p} = {VDD * (i >> k & 1):g}" for k, p in enumerate(inputs)]
        deck += ["op", f"echo ROW {i}", f"print v({output})"]
    deck += ["quit", ".endc", ".end"]
    (folder / f"{name}_dc.spice").write_text("\n".join(deck) + "\n")
    out = run("ngspice", ["-b", f"{name}_dc.spice"], folder, folder / f"{name}_dc.log")
    rows = []
    for i in range(1 << len(inputs)):
        block = re.search(rf"^ROW {i}\n(.*?)(?=^ROW |\Z)", out, re.M | re.S)
        v = float(re.search(r"=\s*([-+\deE.]+)", block[1])[1])
        want = table >> i & 1
        ok = v >= 0.9 * VDD if want else v <= 0.1 * VDD
        rows.append(dict(inputs=i, expected=want, y=round(v, 4), passed=ok))
    return rows


def sequence(n: int) -> list[int]:
    """Input vectors that start from every state and toggle every input once from it."""
    vectors = []
    for state in range(1 << n):
        for k in range(n):
            vectors += [state, state ^ (1 << k)]
    return vectors


def transient(folder: Path, name: str, inputs: list[str], output: str, table: int) -> dict:
    slew, load, fraction = hd_point()
    ramp = slew / fraction
    vectors = sequence(len(inputs))
    deck = [f"* {name} transient, input slew {slew} ns (20-80%), load {load} pF",
            f'.lib "{MODELS}" tt', f'.include "{name}_pex.spice"', f".temp {TEMP}", f"VPWR VPWR 0 {VDD}"]
    for k, p in enumerate(inputs):
        points, level = [], vectors[0] >> k & 1
        points.append(f"0 {VDD * level:g}")
        for j, v in enumerate(vectors[1:], 1):
            new = v >> k & 1
            if new != level:
                t = j * STEP
                points += [f"{t:g}n {VDD * level:g}", f"{t + ramp:g}n {VDD * new:g}"]
                level = new
        deck.append(f"V{p} {p} 0 PWL({' '.join(points)})")
    deck += [instance(folder, name, inputs, output), f"CL {output} 0 {load}p",
             ".control", f"tran 5p {len(vectors) * STEP:g}n",
             f"wrdata {name}_tran.txt v({output})", "quit", ".endc", ".end"]
    (folder / f"{name}_tran.spice").write_text("\n".join(deck) + "\n")
    run("ngspice", ["-b", f"{name}_tran.spice"], folder, folder / f"{name}_tran.log")

    wave = [tuple(map(float, line.split()[:2])) for line in (folder / f"{name}_tran.txt").read_text().splitlines()
            if line.strip()]
    errors = []
    for j, v in enumerate(vectors):
        start, end = j * STEP * 1e-9, (j + 1) * STEP * 1e-9
        want = table >> v & 1
        before = table >> vectors[j - 1] & 1 if j else want
        window = [y for t, y in wave if start <= t < end]
        final = window[-1]
        if not (final >= 0.9 * VDD if want else final <= 0.1 * VDD):
            errors.append(f"step {j} inputs {v:0{len(inputs)}b}: Y={final:.3f} V at the next edge, expected {want}")
        if want == before and any((y > VDD / 2) != bool(want) for y in window):
            errors.append(f"step {j} inputs {v:0{len(inputs)}b}: Y glitched across VDD/2")
    return dict(slew_ns=slew, load_pf=load, steps=len(vectors), errors=errors, passed=not errors)


def simulate(folder: Path, name: str, table: int) -> dict:
    meta = json.loads((folder / f"{name}.json").read_text())
    rows = dc(folder, name, meta["inputs"], meta["output"], table)
    result = dict(dc=rows, dc_passed=all(r["passed"] for r in rows),
                  transient=transient(folder, name, meta["inputs"], meta["output"], table))
    result["passed"] = result["dc_passed"] and result["transient"]["passed"]
    (folder / f"{name}_sim.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    folder = Path(sys.argv[1]).resolve()
    result = simulate(folder.parent, folder.name, int(sys.argv[2], 16))
    for r in result["dc"]:
        print(f"DC {r['inputs']:04b} Y={r['y']:.4f} expected {r['expected']} {'ok' if r['passed'] else 'FAIL'}")
    t = result["transient"]
    print(f"transient: {t['steps']} steps, slew {t['slew_ns']} ns, load {t['load_pf']} pF, "
          f"{'PASS' if t['passed'] else 'FAIL'}")
    for e in t["errors"]:
        print("  ", e)
    sys.exit(0 if result["passed"] else 1)

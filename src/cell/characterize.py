"""The characterizer: delay, output transition and input capacitance of a cell from its extracted netlist
(option 1 handout, section 5).

    python -m src.cell.characterize hd <cell, e.g. nand2_1> [--grid N] [--full-ramp] [--image IMAGE]

`hd` characterizes an installed HD cell for the validation of section 5.1: its layout is cut from the PDK
GDS, extracted with our Magic flow (compare.hd_reference), and given SA and SB (stress.py). The slews and
loads are the index values of that cell's own HD tables, so every entry can be compared one to one.

One measurement, at input slew s (the table index) and load C:
  - the side inputs are held at a setting under which the pin controls Y (arcs.py);
  - the pin is driven by a linear ramp whose time between the slew thresholds is s * derate, so the
    full 0-100% ramp is s * derate / (upper - lower). --full-ramp makes the full ramp s instead: the broken
    case of Table 5, which the validation must flag;
  - delay is the time from the pin crossing input_threshold_pct to Y crossing output_threshold_pct;
  - transition is the time Y takes between the slew thresholds, divided by derate;
  - the pin's capacitance is the charge its source delivers while the pin moves through its own slew
    window (slew_lower to slew_upper threshold), over the voltage it moves in that window. Liberty's pin
    capacitance is the load a driver sees, and the driver's edge is timed between those thresholds; charge
    drawn after the pin has finished (Miller charge while Y is still swinging) does not slow that edge.
    The charge over the whole run, over VDD, is kept as capacitance_full for the report. Both are taken
    at the table point nearest 100 ps and 10 fF (the point of section 6).
Every threshold, the voltage and the temperature come from the Liberty header (liberty_timing.read_setup).

"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from src.cell.arcs import arcs
from src.cell.liberty_timing import read_cell, read_setup
from src.cell.stress import stress
from src.cell.tools import IMAGE, MODELS, run
from src.common.request import truth_table
from src.paths import PREFIX

ROOT = Path(__file__).resolve().parents[2]
TD = 0.1e-9          # s before the input edge; the DC operating point sets the start state
# Time simulated after the ramp ends: SETTLE + SETTLE_PER_PF * load. It must cover Y passing its slew
# thresholds; if it does not, the meas fails and the point is reported as missing, never as a number.
# 100 ns/pF is about 5x the slowest x1 pull-up among the reference cells (two hvt PMOS in series).
SETTLE = 1e-9
SETTLE_PER_PF = 100e-9
# default_arc_mode (read from the Liberty). We only support worst_edges now sincxe thats what we need. Any other config will stop the run.
SIDE_RULES = {"worst_edges": max}
CAP_POINT = (0.1, 0.01)   # ns, pF: the HD table point nearest 100 ps and 10 fF (section 6)


def pick(values: list[float], n: int | None) -> list[float]:
    """n values spread over the index, both ends kept (n=None keeps them all)."""
    if not n or n >= len(values):
        return list(values)
    return [values[round(i * (len(values) - 1) / (n - 1))] for i in range(n)]


def ramp_time(slew: float, setup: dict, edge: str, full_ramp: bool = False) -> float:
    """The full 0-100% ramp (ns) of an input whose table slew is `slew`."""
    if full_ramp:
        return slew
    window = (setup[f"slew_upper_threshold_pct_{edge}"] - setup[f"slew_lower_threshold_pct_{edge}"]) / 100
    return slew * setup["slew_derate_from_library"] / window


def window(ramp: float, setup: dict, edge: str) -> tuple[float, float]:
    """When a linear input ramp starting at TD is inside its slew window (s). Rising, it passes the lower
    threshold first; falling, the upper one; the window has the same length either way."""
    lo = setup[f"slew_lower_threshold_pct_{edge}"] / 100
    hi = setup[f"slew_upper_threshold_pct_{edge}"] / 100
    a, b = (lo, hi) if edge == "rise" else (1 - hi, 1 - lo)
    return TD + a * ramp, TD + b * ramp


def ngspice_id(folder: Path, image: str) -> dict:
    out = run("sh", ["-c", "ngspice -v 2>&1 | head -3; sha256sum \"$(command -v ngspice)\""], folder,
              folder / "ngspice_id.log", image=image)
    version = re.search(r"ngspice-[\w.+-]+", out)
    sha = re.search(r"\b([0-9a-f]{64})\b", out)
    return {"image": image, "version": version[0] if version else None, "sha256": sha[1] if sha else None}


def deck(name: str, netlist: str, ports: list[str], output: str, pin: str, side: dict, edge_in: str,
         edge_out: str, slews: list[float], loads: list[float], setup: dict, full_ramp: bool) -> str:
    vdd = setup["nom_voltage"]
    pct = lambda key: vdd * setup[key] / 100
    v0, v1 = (0, vdd) if edge_in == "rise" else (vdd, 0)
    nets = {p: p for p in ports}
    nets.update(VGND="0", VNB="0", VPWR="VPWR", VPB="VPWR")
    lines = [f"* {name}: {pin} {edge_in} -> {output} {edge_out}, side {side}",
             f'.lib "{MODELS}" tt', f'.include "{netlist}"', f".temp {setup['nom_temperature']:g}",
             f"VPWR VPWR 0 {vdd:g}"]
    lines += [f"V{p} {p} 0 {vdd * v:g}" for p, v in side.items()]
    lines += [f"V{pin} {pin} 0 PULSE({v0:g} {v1:g} {TD:g} 1e-11 1e-11 1 2)",
              f"XU {' '.join(nets[p] for p in ports)} {name}", f"CL {output} 0 {loads[0] * 1e-12:g}",
              ".control"]
    cross_in = "rise" if edge_in == "rise" else "fall"
    cross_out = "rise" if edge_out == "rise" else "fall"
    for i, slew in enumerate(slews):
        ramp = ramp_time(slew, setup, edge_in, full_ramp) * 1e-9
        # the step must stay fine through the edges: letting ngspice pick it moved small-load transitions
        # by ~20% against this setting (inv_1, compared with timing_diff)
        tmax = min(max(ramp / 20, 0.5e-12), 20e-12)
        lines.append(f"alter @V{pin}[pulse] = [ {v0:g} {v1:g} {TD:g} {ramp:g} {ramp:g} 1 2 ]")
        win = window(ramp, setup, edge_in)
        for j, load in enumerate(loads):
            tstop = TD + ramp + SETTLE + SETTLE_PER_PF * load
            lines += [f"alter CL = {load * 1e-12:g}",
                      f"tran {tmax:g} {tstop:g} 0 {tmax:g}",
                      f"echo POINT {i} {j}",
                      f"meas tran tin when v({pin})={pct(f'input_threshold_pct_{edge_in}'):g} {cross_in}=1",
                      f"meas tran tout when v({output})={pct(f'output_threshold_pct_{edge_out}'):g} {cross_out}=1",
                      f"meas tran tlo when v({output})={pct(f'slew_lower_threshold_pct_{edge_out}'):g} {cross_out}=1",
                      f"meas tran thi when v({output})={pct(f'slew_upper_threshold_pct_{edge_out}'):g} {cross_out}=1",
                      f"meas tran q integ i(V{pin}) from=0 to={tstop:g}",
                      f"meas tran qwin integ i(V{pin}) from={win[0]:g} to={win[1]:g}",
                      f"meas tran evdd integ i(VPWR) from={TD:g} to={tstop:g}",
                      "destroy all"]
    lines += ["quit", ".endc", ".end"]
    return "\n".join(lines) + "\n"


def measure(folder: Path, name: str, netlist: str, ports: list[str], output: str, pin: str, side: dict,
            edge_in: str, edge_out: str, slews: list[float], loads: list[float], setup: dict, full_ramp: bool,
            image: str, tag: str) -> dict:
    """Run one (pin, side setting, input edge) over the grid. Times in ns, capacitance in pF."""
    stem = f"{name}_{pin}_{edge_in}_" + "".join(f"{p}{v}" for p, v in side.items()) + tag
    (folder / f"{stem}.spice").write_text(deck(name, netlist, ports, output, pin, side, edge_in, edge_out,
                                              slews, loads, setup, full_ramp))
    out = run("ngspice", ["-b", f"{stem}.spice"], folder, folder / f"{stem}.log", timeout=3600, image=image)
    vdd, derate = setup["nom_voltage"], setup["slew_derate_from_library"]
    delay = [[None] * len(loads) for _ in slews]
    trans = [[None] * len(loads) for _ in slews]
    swing = vdd * (setup[f"slew_upper_threshold_pct_{edge_in}"] - setup[f"slew_lower_threshold_pct_{edge_in}"]) / 100
    cap = [[None] * len(loads) for _ in slews]
    cap_full = [[None] * len(loads) for _ in slews]
    errors = []
    energy = [[None] * len(loads) for _ in slews]
    wanted = {"tin", "tout", "tlo", "thi", "q", "qwin", "evdd"}
    blocks = re.split(r"^POINT (\d+) (\d+)\s*$", out, flags=re.M)
    for i, j, block in zip(blocks[1::3], blocks[2::3], blocks[3::3]):
        i, j = int(i), int(j)
        m = {k: float(v) for k, v in re.findall(r"^(tin|tout|tlo|thi|qwin|q|evdd)\s*=\s*([-+\d.eE]+)", block, re.M)}
        if not wanted <= m.keys():
            errors.append(f"slew {slews[i]} load {loads[j]}: missing {sorted(wanted - m.keys())}")
            continue
        delay[i][j] = (m["tout"] - m["tin"]) * 1e9
        trans[i][j] = abs(m["thi"] - m["tlo"]) / derate * 1e9
        cap[i][j] = abs(m["qwin"]) / swing * 1e12
        cap_full[i][j] = abs(m["q"]) / vdd * 1e12
        # internal energy of the transition, pJ: what VPWR delivers (the current into its + node is
        # negative while it sources), less half the load's C V^2, which the STA tool adds as switching
        # power. That is HD's convention: its fall_power is about -C V^2 / 2 (sky130_fd_sc_hd__inv_1).
        energy[i][j] = -m["evdd"] * vdd * 1e12 - 0.5 * loads[j] * vdd ** 2
    return dict(pin=pin, side=side, edge_in=edge_in, edge_out=edge_out, deck=f"{stem}.spice",
                delay=delay, transition=trans, capacitance=cap, capacitance_full=cap_full, energy=energy,
                errors=errors)


def combine(tables: list[list[list[float | None]]], rule) -> list[list[float | None]]:
    """One table from the tables of several side settings, entry by entry."""
    rows, cols = len(tables[0]), len(tables[0][0])
    out = [[None] * cols for _ in range(rows)]
    for i in range(rows):
        for j in range(cols):
            values = [t[i][j] for t in tables]
            out[i][j] = None if None in values else rule(values)
    return out


def nearest(values: list[float], target: float) -> int:
    return min(range(len(values)), key=lambda k: abs(values[k] - target))


def leakage(folder: Path, name: str, netlist: str, ports: list[str], inputs: list[str], setup: dict, image: str,
            tag: str = "") -> dict:
    """Leakage power (nW, the Liberty's leakage_power_unit) in every input state: the DC operating point,
    VPWR's current times VDD. Keys are the states as Liberty `when` conditions over the inputs."""
    vdd = setup["nom_voltage"]
    nets = {p: p for p in ports}
    nets.update(VGND="0", VNB="0", VPWR="VPWR", VPB="VPWR")
    lines = [f"* {name}: leakage in every input state", f'.lib "{MODELS}" tt', f'.include "{netlist}"',
             f".temp {setup['nom_temperature']:g}", f"VPWR VPWR 0 {vdd:g}",
             # ngspice's default gmin (1e-12 S on every junction) draws 1.8 pA at 1.8 V, more than a cell's
             # leakage in some states (HD's nand2_1 with both inputs low: 30 fW); measure far below it
             ".option gmin=1e-18 abstol=1e-18 reltol=1e-6"]
    lines += [f"V{p} {p} 0 0" for p in inputs]
    lines += [f"XU {' '.join(nets[p] for p in ports)} {name}", ".control"]
    for state in range(1 << len(inputs)):
        lines += [f"alter V{p} dc = {vdd * (state >> k & 1):g}" for k, p in enumerate(inputs)]
        lines += ["op", f"echo STATE {state}", "print i(VPWR)", "destroy all"]
    lines += ["quit", ".endc", ".end"]
    stem = f"{name}_leakage{tag}"
    (folder / f"{stem}.spice").write_text("\n".join(lines) + "\n")
    out = run("ngspice", ["-b", f"{stem}.spice"], folder, folder / f"{stem}.log", timeout=600, image=image)
    found = {}
    for state, value in re.findall(r"^STATE (\d+)\s*\n(?:.*\n)*?i\(vpwr\)\s*=\s*([-+\d.eE]+)", out, re.M | re.I):
        cond = "&".join(("" if int(state) >> k & 1 else "!") + p for k, p in enumerate(inputs))
        found[cond] = -float(value) * vdd * 1e9
    return found


def characterize(folder: Path, name: str, netlist: str, inputs: list[str], output: str, table: int,
                 grids: dict, setup: dict, full_ramp: bool = False, image: str = IMAGE, tag: str = "") -> dict:
    """grids: pin -> (slews ns, loads pF). Writes <name>_timing<tag>.json in folder and returns it."""
    mode = setup["default_arc_mode"]
    if mode not in SIDE_RULES:
        raise ValueError(f"default_arc_mode {mode!r}: no side-input rule for it")
    text = (folder / netlist).read_text()
    ports = re.search(rf"(?im)^\.subckt\s+{re.escape(name)}\s+(.+)", text)[1].split()
    jobs = []
    for arc in arcs(inputs, table):
        slews, loads = grids[arc.pin]
        for edge_in, edge_out, settings in arc.edges():
            for s in settings:
                jobs.append((arc, edge_in, edge_out, s, slews, loads))
    workers = max(1, min(len(jobs), os.cpu_count() or 2))      # ngspice is single-threaded
    with ThreadPoolExecutor(workers) as pool:
        runs = list(pool.map(lambda j: measure(folder, name, netlist, ports, output, j[0].pin, j[3].side, j[1],
                                               j[2], j[4], j[5], setup, full_ramp, image, tag), jobs))

    result = dict(cell=name, netlist=netlist, inputs=inputs, output=output, truth_table=f"0x{table:X}",
                  ngspice=ngspice_id(folder, image), setup=setup, full_ramp=full_ramp,
                  side_rule=f"default_arc_mode {mode}: {SIDE_RULES[mode].__name__} over the side settings per entry", pins={}, arcs=[])
    for arc in arcs(inputs, table):
        mine = [r for r in runs if r["pin"] == arc.pin]
        slews, loads = grids[arc.pin]
        i, j = nearest(slews, CAP_POINT[0]), nearest(loads, CAP_POINT[1])
        caps = {}
        for key in ("capacitance", "capacitance_full"):
            suffix = key[len("capacitance"):]
            for edge in ("rise", "fall"):
                values = [r[key][i][j] for r in mine if r["edge_in"] == edge and r[key][i][j] is not None]
                caps[f"{edge}_capacitance{suffix}"] = statistics.mean(values) if values else None
            both = [caps[f"{e}_capacitance{suffix}"] for e in ("rise", "fall") if caps[f"{e}_capacitance{suffix}"] is not None]
            caps[key] = statistics.mean(both) if both else None
        caps["at"] = dict(slew_ns=slews[i], load_pf=loads[j])
        result["pins"][arc.pin] = caps
        tables, power = {}, {}
        for edge_out in ("rise", "fall"):
            chosen = [r for r in mine if r["edge_out"] == edge_out]
            if chosen:
                tables[f"cell_{edge_out}"] = combine([r["delay"] for r in chosen], SIDE_RULES[mode])
                tables[f"{edge_out}_transition"] = combine([r["transition"] for r in chosen], SIDE_RULES[mode])
                # internal energy, pJ, kept apart from the timing tables; not a worst case: the mean over the
                # side settings
                power[f"{edge_out}_power"] = combine([r["energy"] for r in chosen], statistics.mean)
        result["arcs"].append(dict(pin=arc.pin, output=output, sense=arc.sense, index_1=slews, index_2=loads,
                                   tables=tables, power=power, runs=mine))
    result["leakage_nw"] = leakage(folder, name, netlist, ports, inputs, setup, image, tag)
    result["errors"] = [f"{r['deck']}: {e}" for r in runs for e in r["errors"]]
    (folder / f"{name}_timing{tag}.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def characterize_hd(short: str, grid: int | None = None, full_ramp: bool = False, image: str = IMAGE,
                    tag: str = "") -> dict:
    """Characterize the installed HD cell `short` on its own table indexes (section 5.1)."""
    from src.cell.compare import hd_reference
    hd = read_cell(short)
    folder = hd_reference(ROOT / "build/char" / short, short)
    stress(folder, hd.name)
    grids = hd_grids(short, hd.inputs, grid)
    table = truth_table(hd.function, tuple(hd.inputs))
    return characterize(folder, hd.name, f"{hd.name}_sasb.spice", hd.inputs, hd.output, table, grids,
                        read_setup(), full_ramp, image, tag)


def hd_grids(short: str, pins: list[str], grid: int | None = None, rename: dict | None = None) -> dict:
    """pin -> (slews, loads) from the cell_rise table of each of the HD cell's arcs. rename maps our pin
    to the HD cell's pin of the same role, when the names differ."""
    out = {}
    for a in read_cell(short).arcs:
        t = a.tables["cell_rise"] if "cell_rise" in a.tables else next(iter(a.tables.values()))
        out[a.pin] = (pick(t["index_1"], grid), pick(t["index_2"], grid))
    if rename and all(rename.get(p) in out for p in pins):
        return {p: out[rename[p]] for p in pins}
    if all(p in out for p in pins):
        return {p: out[p] for p in pins}
    # different pin names (a test cell's A, B, C against HD's A1, A2, B1): usable only if every arc of the
    # HD cell has the same grid, so the choice of arc does not matter
    if len({(tuple(s), tuple(l)) for s, l in out.values()}) == 1:
        return {p: next(iter(out.values())) for p in pins}
    raise ValueError(f"HD cell {short}: pins {sorted(out)} differ from {pins} and its arcs have different grids")


def characterize_ours(request: Path, grid_from: str, grid: int | None = None, full_ramp: bool = False,
                      image: str = IMAGE, tag: str = "", rename: dict | None = None) -> dict:
    """Characterize one of our generated cells, as built by src.cell.build in build/cells/<name>/, on the
    table indexes of the HD cell grid_from (its HD counterpart, or a comparable x1 cell when there is none)."""
    from src.common.request import read_request
    req = read_request(request)
    folder = ROOT / "build/cells" / req.name
    if not (folder / f"{req.name}_pex.spice").exists():
        raise FileNotFoundError(f"{folder}: no extracted netlist; run python -m src.cell.build {request} first")
    stress(folder, req.name)
    grids = hd_grids(grid_from, list(req.inputs), grid, rename)
    r = characterize(folder, req.name, f"{req.name}_sasb.spice", list(req.inputs), req.output, req.truth_table,
                     grids, read_setup(), full_ramp, image, tag)
    r["grid_from"] = PREFIX + grid_from
    (folder / f"{req.name}_timing{tag}.json").write_text(json.dumps(r, indent=2) + "\n")
    return r


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=["hd", "ours"], help="hd: an installed cell; ours: a request we built")
    ap.add_argument("cell", help="hd: the cell, e.g. nand2_1; ours: the request JSON")
    ap.add_argument("--grid-from", help="ours: the HD cell whose table indexes to use, e.g. nand2_1")
    ap.add_argument("--grid", type=int, help="points per index, e.g. 5 for the 5x5 subset")
    ap.add_argument("--full-ramp", action="store_true", help="broken case: full ramp = table slew")
    ap.add_argument("--image", default=IMAGE, help="container with the ngspice to use")
    ap.add_argument("--tag", default="", help="suffix for the output files, e.g. _stock")
    args = ap.parse_args()
    if args.kind == "hd":
        r = characterize_hd(args.cell, args.grid, args.full_ramp, args.image, args.tag)
    else:
        if not args.grid_from:
            ap.error("ours needs --grid-from <HD cell>")
        r = characterize_ours(Path(args.cell).resolve(), args.grid_from, args.grid, args.full_ramp, args.image, args.tag)
    print(f"{r['cell']}: ngspice {r['ngspice']['version']} sha256 {r['ngspice']['sha256']}")
    for pin, c in r["pins"].items():
        print(f"  pin {pin}: rise {c['rise_capacitance']:.6f} fall {c['fall_capacitance']:.6f} pF in the slew window; "
              f"whole run {c['capacitance_full']:.6f} pF")
    for a in r["arcs"]:
        for k, t in a["tables"].items():
            print(f"  {a['pin']}->{a['output']} {a['sense']:15s} {k:16s} first row {[round(v, 4) if v else v for v in t[0]]}")
    for e in r["errors"]:
        print("  ERROR", e)

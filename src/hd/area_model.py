"""Area model: width in sites against transistor count, fitted to HD's x1 cells (section 4, step 6).

Training cells: the x1 (name ends in _1) single-output combinational cells of given/hd_usable.lib.
Transistors come from the PDK SPICE netlist, width from the cell LEF, and the site from the
tech LEF; nothing is typed in. The model is a least-squares line sites = a + b * transistors,
and an estimate is that line rounded up to a whole site.

    python -m src.hd.area_model      -> results/hd/area_model.csv, results/hd/area_model.json
"""

from __future__ import annotations

from dataclasses import dataclass
import csv
import json
import math
import re
import statistics
from pathlib import Path

from src.hd.cost import cost
from src.hd.liberty import parse_liberty_file
from src.paths import LEF, LIB, PREFIX, ROOT, SPICE

TLEF = LIB / "techlef/sky130_fd_sc_hd__nom.tlef"
USABLE = ROOT / "given/hd_usable.lib"
OUT = ROOT / "results/hd"


def spice_transistors(path: Path = SPICE) -> dict[str, int]:
    """Transistors (X or M instances) in each .subckt of a SPICE netlist."""
    counts, current = {}, None
    for line in path.read_text().splitlines():
        words = line.split()
        if not words:
            continue
        if words[0].lower() == ".subckt":
            current = words[1]
            counts[current] = 0
        elif words[0].lower() == ".ends":
            current = None
        elif current and words[0][0] in "XxMm":
            counts[current] += 1
    return counts


def lef_widths(path: Path = LEF) -> dict[str, float]:
    """Width in um of every MACRO, from its SIZE <w> BY <h> line."""
    widths = {}
    for name, body in re.findall(r"^MACRO (\S+)\n(.*?)^END \1", path.read_text(), re.S | re.M):
        size = re.search(r"SIZE ([\d.]+) BY ([\d.]+)", body)
        if size:
            widths[name] = float(size[1])
    return widths


def site(path: Path = TLEF, name: str = "unithd") -> tuple[float, float]:
    """Width and height in um of a placement site, from the tech LEF."""
    body = re.search(rf"^SITE {name}\n(.*?)^END {name}", path.read_text(), re.S | re.M)[1]
    size = re.search(r"SIZE ([\d.]+) BY ([\d.]+)", body)
    return float(size[1]), float(size[2])


def one_stage(table: int, n: int) -> bool:
    """Negative unate in every input: one static CMOS stage computes it."""
    return all(not (table >> i & 1 == 0 and table >> (i | 1 << k) & 1)
               for k in range(n) for i in range(1 << n) if not i >> k & 1)


@dataclass(frozen=True)
class Model:
    a: float
    b: float
    site_w: float
    site_h: float

    def sites(self, transistors: int) -> int:
        return math.ceil(self.a + self.b * transistors)

    def area(self, transistors: int) -> float:
        return round(self.sites(transistors) * self.site_w * self.site_h, 4)


def training_rows() -> list[dict]:
    spice, widths = spice_transistors(), lef_widths()
    site_w, _ = site()
    rows = []
    for cell in parse_liberty_file(str(USABLE)):
        if not cell.name.endswith("_1") or cell.name not in spice or cell.name not in widths:
            continue
        n = len(cell.support)
        c = cost(cell.truth_table, n) if n <= 4 else None
        rows.append(dict(cell=cell.name.removeprefix(PREFIX), inputs=n,
                         stages="single" if one_stage(cell.truth_table, n) else "multi",
                         transistors=spice[cell.name], sites=round(widths[cell.name] / site_w),
                         cost_transistors=c.transistors if c else ""))
    return sorted(rows, key=lambda r: r["cell"])


def fit(rows: list[dict] | None = None) -> Model:
    rows = training_rows() if rows is None else rows
    b, a = statistics.linear_regression([r["transistors"] for r in rows], [r["sites"] for r in rows])
    return Model(a, b, *site())


def errors(model: Model, rows: list[dict]) -> dict:
    out = {}
    for group in ("single", "multi", "all"):
        e = [model.sites(r["transistors"]) - r["sites"] for r in rows if group in ("all", r["stages"])]
        out[group] = dict(cells=len(e), mean_abs_sites=round(statistics.fmean(map(abs, e)), 3),
                          max_abs_sites=max(map(abs, e)), mean_sites=round(statistics.fmean(e), 3),
                          mean_abs_um2=round(statistics.fmean(map(abs, e)) * model.site_w * model.site_h, 4))
    return out


def main():
    rows = training_rows()
    model = fit(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "area_model.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["cell", "inputs", "stages", "transistors_spice", "transistors_cost", "sites",
                    "sites_model", "error_sites"])
        for r in rows:
            w.writerow([r["cell"], r["inputs"], r["stages"], r["transistors"], r["cost_transistors"],
                        r["sites"], model.sites(r["transistors"]), model.sites(r["transistors"]) - r["sites"]])
    summary = dict(model="sites = ceil(a + b * transistors)", a=round(model.a, 4), b=round(model.b, 4),
                   site_um=[model.site_w, model.site_h], source=dict(
                       cells=str(USABLE.relative_to(ROOT)), transistors=str(SPICE.relative_to(ROOT)),
                       widths=str(LEF.relative_to(ROOT)), site=str(TLEF.relative_to(ROOT))),
                   error=errors(model, rows))
    (OUT / "area_model.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

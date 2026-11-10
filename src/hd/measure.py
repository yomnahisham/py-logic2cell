"""Map the required designs onto the reduced library plus some new cells and total the area
(option 2 handout, section 4, steps 10 and 12, and section 7).

The total is the one the conclusion rests on: for each required design the smaller of the areas
from scripts A and B ("best of both"), summed over the six designs.

    from src.hd.measure import measure
    measure(cells, real=None, tag="trial") -> {"areas": {design: {"A": um2, "B": um2}},
                                              "best": {design: um2}, "total": um2, "library": path}
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from src.hd.liberty_writer import REDUCED, extend, groups
from src.map_library.table1 import DESIGNS, NETLIST_OUT, map_design
from src.paths import ROOT

WORK = ROOT / "build/measure"


def totals(areas: dict[str, dict[str, float]]) -> tuple[dict[str, float], float]:
    """Best of both scripts per design, and their sum."""
    best = {d: min(a.values()) for d, a in areas.items()}
    return best, round(sum(best.values()), 4)


def measure(cells: list[dict], real: dict[str, str] | None = None, tag: str = "trial",
            scale: dict[str, float] | None = None, workers: int = 4) -> dict:
    """Write reduced library + `cells` (real groups where `real` has one) and map every required
    design with both scripts. An empty `cells` measures the baseline."""
    WORK.mkdir(parents=True, exist_ok=True)
    NETLIST_OUT.mkdir(parents=True, exist_ok=True)
    library = REDUCED.read_text()
    path = WORK / f"{tag}.lib"
    path.write_text(extend(library, groups(cells, library, scale, real)))
    jobs = [(d, top, s) for d, top in DESIGNS.items() for s in "AB"]

    def job(j):
        design, top, script = j
        return map_design(design, top, tag, script, library=str(path), map_out=WORK)[0]

    with ThreadPoolExecutor(workers) as pool:
        results = list(pool.map(job, jobs))
    areas: dict[str, dict[str, float]] = {d: {} for d in DESIGNS}
    for (design, _, script), area in zip(jobs, results):
        areas[design][script] = area
    best, total = totals(areas)
    return {"areas": areas, "best": best, "total": total, "library": str(path)}
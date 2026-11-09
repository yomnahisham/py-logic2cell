"""Characterize every test cell of Table 6 (option 1 handout, sections 5 and 6) on one ngspice build.

    python -m src.cell.char_tests [--only mux2_1,xor2_1] [--redo] [--jobs 1]

Each request in requests/test/ and requests/hd/ is characterized with characterize.characterize_ours on the
table indexes of the HD cell in GRID_FROM. A cell whose _timing.json already exists is kept unless --redo,
but only if it was made by the same ngspice binary (sha256) as this run; otherwise it is run again.
Writes results/char_tests.txt: cell, grid source, ngspice sha256, minutes, errors. Cells run one at a time by
default: characterize() already runs one ngspice per CPU.
"""

from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from src.cell.characterize import IMAGE, ROOT, characterize_ours, ngspice_id

# request file stem -> HD cell whose table indexes (input slews, output loads) the cell is measured on.
# A cell with an HD counterpart uses that cell. The rest (Table 6 "None" rows) use the HD cell named here:
#   and_a_or_b_cd  !(A&(B|(C&D)))      a32oi_1   the handout: a32oi_1 with two inputs tied computes it
#   or_a_and_b_cd  !(A|(B&(C|D)))      a221oi_1  the handout: a221oi_1 with two inputs tied computes it
#   or_and_maj     (C&D)|(A&B&(C|D))   maj3_1    no HD cell computes it; maj3_1 is the nearest x1 cell:
#                                                multi-stage, non-inverting, majority-like
#   or_and_maj_n   its complement      a22oi_1   no HD cell computes it; a22oi_1 is a single-stage
#                                                inverting 4-input x1 cell
# Every one of these HD cells uses one grid on all its pins (checked by hd_grids), so its pin names need not
# match ours.
GRID_FROM = {
    "inv_1": "inv_1", "nand2_1": "nand2_1", "nor2_1": "nor2_1", "nand3_1": "nand3_1", "nor3_1": "nor3_1",
    "a21oi_1": "a21oi_1", "o21ai_1": "o21ai_1", "a22oi_1": "a22oi_1", "o22ai_1": "o22ai_1", "and2_1": "and2_1",
    "a21o_1": "a21o_1", "mux2_1": "mux2_1", "maj3_1": "maj3_1", "xor2_1": "xor2_1", "a31oi_1": "a31oi_1",
    "o31ai_1": "o31ai_1", "and_a_or_b_cd": "a32oi_1", "or_a_and_b_cd": "a221oi_1", "or_and_maj": "maj3_1",
    "or_and_maj_n": "a22oi_1",
}
OUT = ROOT / "results/char_tests.txt"


def requests() -> dict[str, Path]:
    """stem -> request file; requests/test/ wins over requests/hd/ for a stem in both."""
    out = {}
    for folder in ("hd", "test"):
        for f in sorted((ROOT / "requests" / folder).glob("*.json")):
            out[f.stem] = f
    missing = sorted(set(out) - set(GRID_FROM))
    if missing:
        raise ValueError(f"no grid source chosen for {missing}; add them to GRID_FROM")
    return out


def one(stem: str, request: Path) -> dict:
    start = time.time()
    r = characterize_ours(request, GRID_FROM[stem])
    return dict(stem=stem, cell=r["cell"], grid_from=r["grid_from"], sha256=r["ngspice"]["sha256"],
                minutes=round((time.time() - start) / 60, 1), errors=r["errors"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=1, help="cells at the same time (each already uses every CPU)")
    ap.add_argument("--only", help="comma-separated request stems, e.g. mux2_1,xor2_1")
    ap.add_argument("--redo", action="store_true", help="run cells that already have a timing file")
    args = ap.parse_args()

    reqs = requests()
    if args.only:
        reqs = {s: reqs[s] for s in args.only.split(",")}
    sha = ngspice_id(ROOT / "build/cells", IMAGE)["sha256"]
    print(f"ngspice sha256 {sha} (image {IMAGE})")

    done, todo = [], []
    for stem, req in reqs.items():
        name = json.loads(req.read_text())["name"]
        old = ROOT / "build/cells" / name / f"{name}_timing.json"
        if old.exists() and not args.redo:
            r = json.loads(old.read_text())
            if r["ngspice"]["sha256"] == sha:
                done.append(dict(stem=stem, cell=r["cell"], grid_from=r.get("grid_from"), sha256=sha, minutes=None,
                                 errors=r["errors"]))
                continue
            print(f"{stem}: earlier run used ngspice {r['ngspice']['sha256'][:8]}, running again")
        todo.append(stem)
    print(f"kept {len(done)}, running {len(todo)}: {', '.join(todo)}")

    with ProcessPoolExecutor(max_workers=args.jobs) as pool:
        futures = {pool.submit(one, s, reqs[s]): s for s in todo}
        for f in as_completed(futures):
            s = futures[f]
            try:
                r = f.result()
            except Exception as e:                            # keep going; the cell is reported as failed
                r = dict(stem=s, cell=None, grid_from=GRID_FROM[s], sha256=None, minutes=None,
                         errors=[f"{type(e).__name__}: {e}"])
            print(f"{s}: {r['minutes']} min, {len(r['errors'])} errors", flush=True)
            done.append(r)

    done.sort(key=lambda r: r["stem"])
    lines = [f"Test-cell characterization (section 5), ngspice sha256 {sha}, image {IMAGE}", "",
             f"{'request':15s} {'cell':26s} {'grid from':26s} {'same ngspice':12s} {'minutes':>7s}  errors"]
    for r in done:
        same = "yes" if r["sha256"] == sha else "NO"
        mins = "kept" if r["minutes"] is None else f"{r['minutes']:.1f}"
        lines.append(f"{r['stem']:15s} {str(r['cell']):26s} {str(r['grid_from']):26s} {same:12s} {mins:>7s}  "
                     f"{len(r['errors'])}")
        lines += [f"    {e}" for e in r["errors"]]
    bad = [r["stem"] for r in done if r["errors"] or r["sha256"] != sha]
    lines += ["", f"{len(done) - len(bad)} of {len(done)} cells characterized with no error on one ngspice build: "
              f"{'PASS' if not bad else 'FAIL ' + ', '.join(bad)}"]
    OUT.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()

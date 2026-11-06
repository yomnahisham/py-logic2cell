"""Cell requests for the best candidates (option 2 handout, section 4, step 8; overview, Appendix A).

Everything comes from results/hd/ranked.json: by default a request for each candidate (step 8),
including those Option 1's structure cannot build, which the group may ask the instructor for
(overview, section 2, rule 3). --limit writes only the cells of the Liberty file (selected()),
--names the named ones, --final-set the cells of the final set (step 10). Each request is checked
with Option 1's own request reader (src.common.request) before it is written, so its expression
and truth table agree.

    python -m src.hd.request_writer [--limit 10 | --names <cell> ... | --final-set [<path>]]
        -> requests/candidates/<name>.json

The final set file is written by the greedy selection: {"cells": [<cell name>, ...]}, in the
order the cells were chosen.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.common.request import parse_request
from src.paths import ROOT

RANKED = ROOT / "results/hd/ranked.json"
FINAL_SET = ROOT / "results/hd/final_set.json"
OUT = ROOT / "requests/candidates"
LIMIT = 10      # the final set holds at most 10 new cells (handout, section 4, step 10)


def candidates(ranked=RANKED) -> list[dict]:
    return json.loads(ranked.read_text())["candidates"]


def final_set(path=FINAL_SET) -> list[str]:
    """The cell names of the final set, in the order the greedy selection chose them."""
    try:
        data = json.loads(Path(path).read_text())
    except FileNotFoundError:
        raise SystemExit(f"no final set yet: {path} (the greedy selection writes it)") from None
    names = data.get("cells") if isinstance(data, dict) else None
    if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
        raise SystemExit(f'{path} must hold {{"cells": [<cell name>, ...]}}')
    return names


def selected(limit: int = LIMIT, names: list[str] | None = None, ranked=RANKED) -> list[dict]:
    """The cells for the Liberty file: the named ones in the order given, or the best `limit`
    that have a positive saving and that Option 1's structure can build."""
    every = candidates(ranked)
    if names:
        by_name = {c["name"]: c for c in every}
        missing = [n for n in names if n not in by_name]
        if missing:
            raise SystemExit(f"not in {ranked}: {missing}")
        return [by_name[n] for n in dict.fromkeys(names)]
    return [c for c in every if c["saving_um2"]["total"] > 0 and c.get("buildable", True)][:limit]


def add_choice_arguments(parser: argparse.ArgumentParser, limit_default: int | None):
    """--limit, --names and --final-set, of which at most one is given."""
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--limit", type=int, default=limit_default,
                       help="the best N buildable cells with a positive saving")
    group.add_argument("--names", nargs="+", metavar="CELL", help="these cells")
    group.add_argument("--final-set", nargs="?", const=FINAL_SET, metavar="PATH",
                       help=f"the cells of the final set (default {FINAL_SET.relative_to(ROOT)})")


def chosen_names(args) -> list[str] | None:
    return final_set(args.final_set) if args.final_set else args.names


def request(c: dict) -> dict:
    data = dict(request_id=c["request_id"], name=c["name"], inputs=c["inputs"], output=c["output"],
                expression=c["expression"], truth_table=c["truth_table"], sizing="hd",
                estimated_area_um2=c["area_um2"])
    parse_request(data)     # raises if the expression and the truth table disagree
    return data


def main(argv: list[str]):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    add_choice_arguments(parser, limit_default=None)
    args = parser.parse_args(argv)
    names = chosen_names(args)
    chosen = selected(args.limit, names) if args.limit or names else candidates()
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.json"):
        old.unlink()
    for c in chosen:
        (OUT / f"{c['name']}.json").write_text(json.dumps(request(c), indent=2) + "\n")
        print(f"{c['rank']:3} {c['name']}: {'' if c.get('buildable', True) else '(not buildable) '}"
              f"{c['expression']}, {c['area_um2']} um2")


if __name__ == "__main__":
    main(sys.argv[1:])

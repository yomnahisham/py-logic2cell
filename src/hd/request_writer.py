"""Cell requests for the best candidates (option 2 handout, section 4, step 8; overview, Appendix A).

Everything comes from results/hd/ranked.json: the candidates with a positive estimated saving,
best first, at most `limit` of them. Each request is checked with Option 1's own request reader
(src.common.request) before it is written, so its expression and truth table agree.

    python -m src.hd.request_writer [--limit 10] [--names <cell> ...]  -> requests/candidates/<name>.json
"""

from __future__ import annotations

import argparse
import json
import sys

from src.common.request import parse_request
from src.paths import ROOT

RANKED = ROOT / "results/hd/ranked.json"
OUT = ROOT / "requests/candidates"
LIMIT = 10      # the final set holds at most 10 new cells (handout, section 4, step 10)


def selected(limit: int = LIMIT, names: list[str] | None = None, ranked=RANKED) -> list[dict]:
    """The candidates to write: the named ones, or the best `limit` with a positive saving."""
    candidates = json.loads(ranked.read_text())["candidates"]
    if names:
        chosen = [c for c in candidates if c["name"] in names]
        missing = set(names) - {c["name"] for c in chosen}
        if missing:
            raise SystemExit(f"not in {ranked}: {sorted(missing)}")
        return chosen
    return [c for c in candidates if c["saving_um2"]["total"] > 0][:limit]


def request(c: dict) -> dict:
    data = dict(request_id=c["request_id"], name=c["name"], inputs=c["inputs"], output=c["output"],
                expression=c["expression"], truth_table=c["truth_table"], sizing="hd",
                estimated_area_um2=c["area_um2"])
    parse_request(data)     # raises if the expression and the truth table disagree
    return data


def main(argv: list[str]):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--limit", type=int, default=LIMIT)
    parser.add_argument("--names", nargs="*")
    args = parser.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.json"):
        old.unlink()
    for c in selected(args.limit, args.names):
        (OUT / f"{c['name']}.json").write_text(json.dumps(request(c), indent=2) + "\n")
        print(f"{c['rank']:3} {c['name']}: {c['expression']}, {c['area_um2']} um2")


if __name__ == "__main__":
    main(sys.argv[1:])

"""Our counts for Table 4 of the option 2 handout, written to results/table4.txt.

    python -m src.hd.table4
"""

from collections import Counter
from itertools import permutations
from pathlib import Path

from src.common.stage import expression, single_stage
from src.hd.redundancy import _library, _classify, _permute_four

OUT = Path(__file__).resolve().parents[2] / "results/table4.txt"


def classes():
    perms = list(permutations(range(4)))
    seen, out = set(), {}
    for t in range(1 << 16):
        if t in seen or not all(any((t >> i & 1) != (t >> (i ^ 1 << k) & 1) for i in range(16)) for k in range(4)):
            continue
        orbit = {_permute_four(t, p) for p in perms}
        seen |= orbit
        out[min(orbit)] = _classify(min(orbit), _library())[0]
    return out


def main():
    c = classes()
    new = sorted(t for t, k in c.items() if k == "new")
    one = [t for t in new if single_stage(t, 4, max_series=12)]
    small = [t for t in new if (f := single_stage(t, 4)) and 2 * f.size <= 12]
    once = Counter(k for t, k in c.items() if (f := single_stage(t, 4)) and f.size == 4)
    lines = [f"classes up to input order, all 4 inputs used: {len(c)}"]
    lines += [f"{k}: {n}" for k, n in sorted(Counter(c.values()).items())]
    lines += [f"new, one static CMOS stage: {len(one)}",
              f"new, one stage, at most 3 in series and 12 transistors: {len(small)}"]
    for t in small:
        f = single_stage(t, 4)
        lines.append(f"  0x{t:04X}  {2 * f.size} transistors, series {f.down}/{f.up}  {expression(f, list('ABCD'))}")
    lines.append(f"one stage, every input used once: {sum(once.values())} ({dict(once)})")
    OUT.write_text("\n".join(lines) + "\n")
    print(OUT.read_text())


if __name__ == "__main__":
    main()

"""Read AIGER files (ASCII .aag or binary .aig) and write ASCII .aag."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class Aig:
    max_var: int
    inputs: list[int]                       # literals
    latches: list[tuple[int, ...]]          # (literal, next, [init])
    outputs: list[int]
    ands: list[tuple[int, int, int]]        # (lhs, rhs0, rhs1) literals


def read(path: str | Path) -> Aig:
    data = Path(path).read_bytes()
    end = data.index(b"\n")
    kind, *nums = data[:end].decode().split()
    m, i, l, o, a = map(int, nums[:5])
    pos = end + 1

    def line():
        nonlocal pos
        e = data.index(b"\n", pos)
        text = data[pos:e].decode()
        pos = e + 1
        return list(map(int, text.split()))

    if kind == "aag":
        inputs = [line()[0] for _ in range(i)]
        latches = [tuple(line()) for _ in range(l)]
        outputs = [line()[0] for _ in range(o)]
        ands = [tuple(line()) for _ in range(a)]
    elif kind == "aig":
        inputs = [2 * (k + 1) for k in range(i)]
        latches = [(2 * (i + k + 1), *line()) for k in range(l)]
        outputs = [line()[0] for _ in range(o)]

        def varint():
            nonlocal pos
            x, shift = 0, 0
            while True:
                b = data[pos]
                pos += 1
                x |= (b & 0x7F) << shift
                if b < 0x80:
                    return x
                shift += 7

        ands = []
        for k in range(a):
            lhs = 2 * (i + l + k + 1)
            rhs0 = lhs - varint()
            rhs1 = rhs0 - varint()
            ands.append((lhs, rhs0, rhs1))
    else:
        raise ValueError(f"{path} is not an AIGER file")
    return Aig(m, inputs, latches, outputs, ands)


def write_aag(aig: Aig, path: str | Path):
    lines = [f"aag {aig.max_var} {len(aig.inputs)} {len(aig.latches)} {len(aig.outputs)} {len(aig.ands)}"]
    lines += [str(x) for x in aig.inputs]
    lines += [" ".join(map(str, x)) for x in aig.latches]
    lines += [str(x) for x in aig.outputs]
    lines += [" ".join(map(str, x)) for x in aig.ands]
    Path(path).write_text("\n".join(lines) + "\n")

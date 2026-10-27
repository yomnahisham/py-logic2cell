"""Redundancy classification against the full HD Liberty library."""

from __future__ import annotations

from functools import lru_cache
from itertools import permutations, product
import os

from .liberty import Cell, parse_liberty_file


Classification = tuple[str, str | None, str]
_VALID_CLASSES = {"exists", "exists_inv", "contained", "new"}
_PERMS = tuple(permutations(range(4)))


def _expand(table: int, support_size: int, width: int = 4) -> int:
    if support_size > width:
        raise ValueError("HD function has more support inputs than the candidate")
    expanded = 0
    for assignment in range(1 << width):
        source = sum(
            ((assignment >> index) & 1) << index
            for index in range(support_size)
        )
        if (table >> source) & 1:
            expanded |= 1 << assignment
    return expanded


def _invert_input(table: int, input_index: int, width: int = 4) -> int:
    result = 0
    for assignment in range(1 << width):
        source = assignment ^ (1 << input_index)
        if (table >> source) & 1:
            result |= 1 << assignment
    return result


def _permute_four(table: int, permutation: tuple[int, ...]) -> int:
    result = 0
    for assignment in range(16):
        source = sum(
            ((assignment >> new_index) & 1) << old_index
            for new_index, old_index in enumerate(permutation)
        )
        if (table >> source) & 1:
            result |= 1 << assignment
    return result


def _tie(table: int, mapping: tuple[int, ...]) -> int:
    """The 4-input table of a cell whose input s is driven by candidate input mapping[s] (0-3), or 0 (4) or 1 (5)."""
    generated = 0
    for assignment in range(16):
        source = 0
        for source_index, destination in enumerate(mapping):
            if destination == 5 or (destination < 4 and (assignment >> destination) & 1):
                source |= 1 << source_index
        if (table >> source) & 1:
            generated |= 1 << assignment
    return generated


@lru_cache(maxsize=4)
def _index(cells: tuple[Cell, ...]) -> tuple[dict, dict, dict]:
    """Every 4-input table each test of Table 3 matches, with the first HD cell that gives it.

    Built once per library: every input order of every cell for exists, of its inverted
    output or one inverted input for exists_inv, and every way of tying its inputs to the
    candidate's inputs or to 0 or 1 for contained. Cells with the same function are done once.
    """
    exists: dict[int, tuple[str, str]] = {}
    exists_inv: dict[int, tuple[str, str]] = {}
    contained: dict[int, tuple[str, str]] = {}
    seen = set()
    for cell in cells:
        size = len(cell.support)
        if (cell.truth_table, size) in seen:
            continue
        seen.add((cell.truth_table, size))
        if size <= 4:
            table = _expand(cell.truth_table, size)
            variants = [(table ^ 0xFFFF, "equal after output inversion and input permutation")]
            variants += [(_invert_input(table, k), "equal after one input inversion and permutation")
                         for k in range(size)]
            for permutation in _PERMS:
                exists.setdefault(_permute_four(table, permutation), (cell.name, "equal after input permutation"))
                for variant, reason in variants:
                    exists_inv.setdefault(_permute_four(variant, permutation), (cell.name, reason))
        for mapping in product(range(6), repeat=size):
            contained.setdefault(_tie(cell.truth_table, mapping),
                                 (cell.name, "equal after input substitution and tying inputs"))
    return exists, exists_inv, contained


@lru_cache(maxsize=1)
def _library() -> tuple[Cell, ...]:
    path = os.environ.get("HD_LIB_FULL")
    if not path:
        raise RuntimeError("HD_LIB_FULL must point to the full Liberty library")
    if not os.path.isfile(path):
        raise RuntimeError(f"HD_LIB_FULL does not exist: {path}")
    return tuple(parse_liberty_file(path))


def _classify(tt16: int, cells: tuple[Cell, ...]) -> Classification:
    if not isinstance(tt16, int) or tt16 < 0 or tt16 > 0xFFFF:
        raise ValueError("tt16 must be an integer in the range 0x0000..0xffff")
    for name, found in zip(("exists", "exists_inv", "contained"), _index(cells)):
        if tt16 in found:
            return name, *found[tt16]
    return "new", None, "no HD function matched"


def classify(tt16: int) -> Classification:
    """Classify a four-input truth table against the full HD library."""

    return _classify(tt16, _library())

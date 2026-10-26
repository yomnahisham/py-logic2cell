"""Redundancy classification against the full HD Liberty library."""

from __future__ import annotations

from functools import lru_cache
from itertools import permutations, product
import os

from .classes import canonical_truth_table
from .liberty import Cell, parse_liberty_file


Classification = tuple[str, str | None, str]
_VALID_CLASSES = {"exists", "exists_inv", "contained", "new"}


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


def _candidate_permutations(table: int) -> set[int]:
    return {
        permute
        for permute in (
            _permute_four(table, permutation)
            for permutation in permutations(range(4))
        )
    }


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


def _cell_candidate_tables(cell: Cell) -> set[int]:
    base = _expand(cell.truth_table, len(cell.support))
    return _candidate_permutations(base)


def _contained(table: int, cell: Cell) -> bool:
    support_size = len(cell.support)
    if support_size > 4:
        return False
    for mapping in product(range(6), repeat=support_size):
        generated = 0
        for assignment in range(16):
            source = 0
            for source_index, destination in enumerate(mapping):
                if destination < 4 and (assignment >> destination) & 1:
                    source |= 1 << source_index
                elif destination == 5:
                    source |= 1 << source_index
            if (cell.truth_table >> source) & 1:
                generated |= 1 << assignment
        if generated in _candidate_permutations(table):
            return True
    return False


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
    candidate_class = canonical_truth_table(tt16, 4)
    tables: list[tuple[Cell, int]] = []
    for cell in cells:
        if len(cell.support) <= 4:
            tables.append((cell, _expand(cell.truth_table, len(cell.support))))

    for cell, table in tables:
        if canonical_truth_table(table, 4) == candidate_class:
            return "exists", cell.name, "equal after input permutation"

    for cell, table in tables:
        if canonical_truth_table(table ^ 0xFFFF, 4) == candidate_class:
            return "exists_inv", cell.name, "equal after output inversion and input permutation"
        for input_index in range(4):
            if canonical_truth_table(_invert_input(table, input_index), 4) == candidate_class:
                return "exists_inv", cell.name, "equal after one input inversion and permutation"

    for cell in cells:
        if _contained(tt16, cell):
            return "contained", cell.name, "equal after input substitution and tying inputs"

    return "new", None, "no HD function matched"


def classify(tt16: int) -> Classification:
    """Classify a four-input truth table against the full HD library."""

    return _classify(tt16, _library())

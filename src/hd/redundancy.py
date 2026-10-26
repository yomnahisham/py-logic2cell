"""Redundancy classification against the full HD Liberty library."""

from __future__ import annotations

from functools import lru_cache
from itertools import permutations, product
import os
from dataclasses import dataclass

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


def _substituted_tables(cell: Cell) -> set[int]:
    support_size = len(cell.support)
    tables: set[int] = set()
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
        tables.update(_candidate_permutations(generated))
    return tables


@dataclass(frozen=True)
class _ReferenceIndex:
    exact: dict[int, str]
    inverted: dict[int, str]
    contained: dict[int, str]


@lru_cache(maxsize=1)
def _reference_index(cells: tuple[Cell, ...]) -> _ReferenceIndex:
    exact: dict[int, str] = {}
    inverted: dict[int, str] = {}
    contained: dict[int, str] = {}
    for cell in cells:
        if len(cell.support) > 4:
            continue
        table = _expand(cell.truth_table, len(cell.support))
        for candidate_class in _candidate_permutations(table):
            exact.setdefault(candidate_class, cell.name)
        inverted.setdefault(
            canonical_truth_table(table ^ 0xFFFF, 4),
            cell.name,
        )
        for input_index in range(4):
            inverted.setdefault(
                canonical_truth_table(_invert_input(table, input_index), 4),
                cell.name,
            )
        for candidate_class in _substituted_tables(cell):
            contained.setdefault(candidate_class, cell.name)
    return _ReferenceIndex(exact, inverted, contained)


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
    index = _reference_index(cells)
    if candidate_class in index.exact:
        return "exists", index.exact[candidate_class], "equal after input permutation"
    if candidate_class in index.inverted:
        return (
            "exists_inv",
            index.inverted[candidate_class],
            "equal after output or one-input inversion and permutation",
        )
    if candidate_class in index.contained:
        return (
            "contained",
            index.contained[candidate_class],
            "equal after input substitution and tying inputs",
        )

    return "new", None, "no HD function matched"


def classify(tt16: int) -> Classification:
    """Classify a four-input truth table against the full HD library."""

    return _classify(tt16, _library())

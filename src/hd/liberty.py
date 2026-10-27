"""Small, deterministic Liberty parser for Boolean cell functions."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Callable, Iterator


@dataclass(frozen=True)
class Cell:
    name: str
    inputs: tuple[str, ...]
    output: str
    function: str
    truth_table: int
    support: tuple[str, ...]
    area: float | None


class LibertySyntaxError(ValueError):
    """Raised when a Boolean function or required Liberty group is invalid."""


Token = tuple[str, str]
_TOKEN_RE = re.compile(r"\s+|[A-Za-z_][A-Za-z0-9_]*|[01]|[!&|^'()*+]")


def _tokens(expression: str) -> Iterator[Token]:
    position = 0
    while position < len(expression):
        match = _TOKEN_RE.match(expression, position)
        if match is None:
            raise LibertySyntaxError(
                f"unexpected character at offset {position}: {expression[position]!r}"
            )
        text = match.group()
        position = match.end()
        if text.isspace():
            continue
        if text in "!&|^'()*+":
            yield text, text
        elif text in ("0", "1"):
            yield "constant", text
        else:
            yield "identifier", text
    yield "end", ""


class _ExpressionParser:
    def __init__(self, expression: str):
        self._tokens = list(_tokens(expression))
        self._index = 0
        self.names: list[str] = []

    def _peek(self) -> Token:
        return self._tokens[self._index]

    def _take(self, kind: str | None = None) -> Token:
        token = self._peek()
        if kind is not None and token[0] != kind:
            raise LibertySyntaxError(
                f"expected {kind}, got {token[0]} ({token[1]!r})"
            )
        self._index += 1
        return token

    def parse(self) -> Callable[[dict[str, bool]], bool]:
        result = self._parse_or()
        if self._peek()[0] != "end":
            raise LibertySyntaxError(f"unexpected token {self._peek()[1]!r}")
        return result

    def _parse_or(self) -> Callable[[dict[str, bool]], bool]:
        result = self._parse_xor()
        while self._peek()[1] in ("|", "+"):
            self._take()
            right = self._parse_xor()
            left = result
            result = lambda values, left=left, right=right: left(values) or right(values)
        return result

    def _parse_xor(self) -> Callable[[dict[str, bool]], bool]:
        result = self._parse_and()
        while self._peek()[1] == "^":
            self._take()
            right = self._parse_and()
            left = result
            result = lambda values, left=left, right=right: left(values) ^ right(values)
        return result

    def _starts_primary(self) -> bool:
        return self._peek()[0] in ("identifier", "constant") or self._peek()[1] in (
            "!",
            "(",
        )

    def _parse_and(self) -> Callable[[dict[str, bool]], bool]:
        result = self._parse_unary()
        while self._peek()[1] in ("&", "*") or self._starts_primary():
            if self._peek()[1] in ("&", "*"):
                self._take()
            right = self._parse_unary()
            left = result
            result = lambda values, left=left, right=right: left(values) and right(values)
        return result

    def _parse_unary(self) -> Callable[[dict[str, bool]], bool]:
        if self._peek()[1] == "!":
            self._take("!")
            operand = self._parse_unary()
            return lambda values, operand=operand: not operand(values)

        if self._peek()[1] == "(":
            self._take("(")
            result = self._parse_or()
            self._take(")")
        elif self._peek()[0] == "identifier":
            name = self._take("identifier")[1]
            if name not in self.names:
                self.names.append(name)
            result = lambda values, name=name: values[name]
        elif self._peek()[0] == "constant":
            result = lambda values, value=self._take("constant")[1] == "1": value
        else:
            raise LibertySyntaxError(f"expected expression, got {self._peek()[1]!r}")

        while self._peek()[1] == "'":
            self._take("'")
            operand = result
            result = lambda values, operand=operand: not operand(values)
        return result


def parse_function(expression: str) -> tuple[tuple[str, ...], Callable[[dict[str, bool]], bool]]:
    """Parse a Liberty Boolean function and return support names and evaluator."""

    parser = _ExpressionParser(expression)
    evaluator = parser.parse()
    return tuple(parser.names), evaluator


def truth_table(expression: str) -> tuple[tuple[str, ...], int]:
    """Return support names and a truth table using the project bit convention."""

    support, evaluator = parse_function(expression)
    table = 0
    for assignment in range(1 << len(support)):
        values = {
            name: bool(assignment & (1 << index))
            for index, name in enumerate(support)
        }
        if evaluator(values):
            table |= 1 << assignment
    return support, table


def _braced_groups(text: str, pattern: re.Pattern[str]) -> Iterator[tuple[str, str]]:
    for match in pattern.finditer(text):
        open_brace = text.find("{", match.end())
        if open_brace < 0:
            raise LibertySyntaxError(f"group {match.group(1)!r} has no body")
        depth = 1
        quoted = False
        escaped = False
        position = open_brace + 1
        while position < len(text) and depth:
            char = text[position]
            if quoted:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    quoted = False
            elif char == '"':
                quoted = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
            position += 1
        if depth:
            raise LibertySyntaxError(f"group {match.group(1)!r} is unterminated")
        yield match.group(1), text[open_brace + 1 : position - 1]


_CELL_GROUP = re.compile(r'\bcell\s*\(\s*"([^"]+)"\s*\)\s*')
_PIN_GROUP = re.compile(r'\bpin\s*\(\s*"([^"]+)"\s*\)\s*')
_FUNCTION = re.compile(r'\bfunction\s*:\s*"((?:\\.|[^"\\])*)"\s*;')
_DIRECTION = re.compile(r'\bdirection\s*:\s*"?\s*(input|output)\s*"?\s*;')
_AREA = re.compile(r"\barea\s*:\s*([0-9.eE+-]+)\s*;")


def _unescape(value: str) -> str:
    return value.replace(r"\"", '"').replace(r"\\", "\\")


def parse_liberty(text: str) -> list[Cell]:
    """Parse eligible single-output combinational cells from Liberty text."""

    cells: list[Cell] = []
    for cell_name, body in _braced_groups(text, _CELL_GROUP):
        if re.search(r"\b(?:ff|latch|statetable)\s*\(", body):
            continue
        pins = list(_braced_groups(body, _PIN_GROUP))
        inputs: list[str] = []
        outputs: list[tuple[str, str, bool]] = []
        for pin_name, pin_body in pins:
            direction = _DIRECTION.search(pin_body)
            if direction is None:
                continue
            if direction.group(1) == "input":
                inputs.append(pin_name)
                continue
            function_match = _FUNCTION.search(pin_body)
            if function_match is None:
                outputs.append((pin_name, "", False))
                continue
            has_three_state = re.search(r"\bthree_state\s*:", pin_body) is not None
            outputs.append((pin_name, _unescape(function_match.group(1)), has_three_state))
        if len(outputs) != 1 or outputs[0][2]:
            continue
        output_name, function, _ = outputs[0]
        support, table = truth_table(function)
        area_match = _AREA.search(body)
        area = float(area_match.group(1)) if area_match else None
        cells.append(
            Cell(
                name=cell_name,
                inputs=tuple(inputs),
                output=output_name,
                function=function,
                truth_table=table,
                support=support,
                area=area,
            )
        )
    return cells


def parse_liberty_file(path: str) -> list[Cell]:
    """Read and parse a Liberty file without modifying it."""

    with open(path, encoding="utf-8") as file:
        return parse_liberty(file.read())

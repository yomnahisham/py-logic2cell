"""Read cell requests and write responses (overview, Appendix A)."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
import sys
from pathlib import Path

from src.hd.liberty import LibertySyntaxError, parse_function

MAX_INPUTS = 4
SIZINGS = ("hd", "stack")
FIELDS = ("request_id", "name", "inputs", "output", "expression", "truth_table", "sizing")
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*$")
_ALLOWED = re.compile(r"[A-Za-z0-9_\s!&|^()]*$")


class RequestError(ValueError):
    def __init__(self, status: str, reason: str):
        super().__init__(reason)
        self.status = status
        self.reason = reason


@dataclass(frozen=True)
class Request:
    request_id: str
    name: str
    inputs: tuple[str, ...]
    output: str
    expression: str
    truth_table: int
    sizing: str
    estimated_area_um2: float | None


def truth_table(expression: str, inputs: tuple[str, ...]) -> int:
    """Bit i is the output when input k equals bit k of i (inputs[0] is the LSB)."""
    if not _ALLOWED.match(expression):
        raise RequestError("fail", f"bad character in expression {expression!r}")
    try:
        names, evaluate = parse_function(expression)
    except LibertySyntaxError as error:
        raise RequestError("fail", f"cannot parse expression: {error}") from None
    unknown = [name for name in names if name not in inputs]
    if unknown:
        raise RequestError("fail", f"expression uses {unknown}, which are not inputs")
    table = 0
    for i in range(1 << len(inputs)):
        if evaluate({name: bool(i >> k & 1) for k, name in enumerate(inputs)}):
            table |= 1 << i
    return table


def parse_request(data: dict) -> Request:
    missing = [key for key in FIELDS if key not in data]
    if missing:
        raise RequestError("fail", f"missing {missing}")

    inputs, output = data["inputs"], data["output"]
    if isinstance(output, list):
        if len(output) != 1:
            raise RequestError("unsupported", f"{len(output)} outputs")
        output = output[0]
    if not isinstance(inputs, list) or not inputs:
        raise RequestError("fail", "inputs must be a non-empty list")
    if len(inputs) > MAX_INPUTS:
        raise RequestError("unsupported", f"{len(inputs)} inputs, at most {MAX_INPUTS}")
    pins = [*inputs, output]
    if not all(isinstance(pin, str) and _NAME.match(pin) for pin in pins) or len(set(pins)) != len(pins):
        raise RequestError("fail", f"bad pin names {pins}")
    if not str(data["name"]).startswith("dd2_gc1__"):
        raise RequestError("fail", f"cell name must start with dd2_gc1__: {data['name']}")
    if data["sizing"] not in SIZINGS:
        raise RequestError("fail", f"sizing must be hd or stack: {data['sizing']}")

    try:
        given = int(str(data["truth_table"]), 16)
    except ValueError:
        raise RequestError("fail", f"truth_table is not hex: {data['truth_table']}") from None
    if given >> (1 << len(inputs)):
        raise RequestError("fail", f"truth_table {data['truth_table']} is too wide for {len(inputs)} inputs")
    computed = truth_table(data["expression"], tuple(inputs))
    if computed != given:
        raise RequestError("fail", f"expression gives 0x{computed:X}, truth_table is {data['truth_table']}")

    return Request(str(data["request_id"]), data["name"], tuple(inputs), output,
                   data["expression"], given, data["sizing"], data.get("estimated_area_um2"))


def read_request(path: str | Path) -> Request:
    try:
        data = json.loads(Path(path).read_text())
    except json.JSONDecodeError as error:
        raise RequestError("fail", f"not valid JSON: {error}") from None
    if not isinstance(data, dict):
        raise RequestError("fail", "request must be a JSON object")
    return parse_request(data)


def write_response(path: str | Path, request_id: str, status: str, reason: str | None = None, **fields) -> dict:
    if status not in ("pass", "fail", "unsupported"):
        raise ValueError(f"bad status {status}")
    if status != "pass" and not reason:
        raise ValueError("a failed response needs a reason")
    response = {"request_id": request_id, "status": status, "reason": reason, **fields}
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(response, indent=2) + "\n")
    return response


if __name__ == "__main__":
    try:
        request = read_request(sys.argv[1])
    except RequestError as error:
        print(f"{error.status}: {error.reason}")
        sys.exit(1)
    n = len(request.inputs)
    print(f"{request.name}: {request.output} = {request.expression}, truth table 0x{request.truth_table:0{max(1, (1 << n) // 4)}X}")

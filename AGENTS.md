# Instructions for the AI assistant

Written before any code, and committed first (overview, section 4.1).

## The project
DD2 Project 1, Option 3 (group of 5): Option 1 and Option 2, connected through the cell request and response of Appendix A.

Option 1 reads a cell request, builds a static CMOS network (at most 3 transistors in series per stage), orders it along a common Euler path, draws it in the HD frame with GDSfactory, verifies it (DRC, LVS, abutment, layer check) and simulates it with ngspice. Magic, Netgen and ngspice run in the `dd2-layout-tools` container.

Option 2 extracts and-inverter graphs from synthesized designs with Yosys, enumerates cuts of up to 4 inputs with truth tables, classifies the functions, checks them against the full sky130_fd_sc_hd (HD) library (Exists / Exists with an inverter / Contained / New), estimates the area of new cells, writes cell requests and a Liberty file, and measures what the new cells do to area when Yosys/ABC maps the designs (scripts A and B). Language: Python 3.11+, packages in `requirements.txt`. Tools: Yosys, ABC, Icarus Verilog, OpenSTA. The AI is used as a development aid: no AI model runs when the tool runs, so the same input always gives the same output.

## How this project is checked
- `make check`: tool versions, PDK link, given files present.
- `make test`: every test, including the broken cases in `tests/broken/`; each broken case must make its check FAIL.
- `make all`: the whole flow, from a clean checkout.
- Checkpoint 1 (tag `cp1`) shows: AIGs of the six required designs, the cut enumerator passing its brute-force check, Table 1 reproduced, the class table of HD, and the redundancy checker passing its self-test against Table 4 of the Option 2 handout.

## Rules the assistant follows (overview, section 4.3)
1. Pass or fail comes from the check scripts, never from the assistant's opinion.
2. Every number in a report comes from a file the flow wrote. Design rule values and library data come from the PDK and the given files, never from the assistant.
3. Every check has a broken case in `tests/broken/` that it must fail on.
4. The assistant never changes the check scripts, the broken cases or the PDK.
5. Expected values (Table 1, Table 4) appear only in test files, never inside the tool. If the tool's result differs from the handout, report the difference; do not adjust code or definitions just to force a match without explaining why in the log.
6. Truth-table convention: a truth table is an int; bit i is the output for the input combination in which input k equals bit k of i; input A is the least significant. A 4-input function has 16 bits.
7. Library facts (cell functions, areas) are parsed from the Liberty file at run time. Input support is derived from the function, not from the pin list.
8. Option 1 code goes in `src/cell/`, Option 2 code in `src/hd/`, shared code in `src/common/`.

## What the assistant must never do
- Weaken, skip or edit a check to make it pass; edit a broken case; move a tag.
- Invent a number, a cell name, or a library value that is not in a file.
- Write code the author cannot explain line by line (every member must be able to explain every part).
- Commit the PDK, copies of the given files, build trees, or any file over 50 MB.

## Conventions
- Code in `src/`, tests in `tests/`, broken cases in `tests/broken/`, every table and log used in the reports in `results/`.
- Paths come from `make setup` (`PDK_ROOT`, `HD_LIB_FULL`, `GIVEN`); never hardcode a user's home directory.
- Commit messages are short and imperative. Every AI-assisted commit carries the trailer `AI-assisted: <tool>/<model>`.
- Each AI-assisted piece of work gets a row in `ai/use_log.md`; each AI mistake that a check caught gets a row in `ai/mistakes_log.md`.

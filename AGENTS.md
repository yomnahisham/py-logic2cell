# Instructions for the AI assistant

Write this file before any code, and commit it first (overview, section 4.1).

## The project
DD2 Project 1, Option 3 (group GC1, 5 members): Option 1 and Option 2, connected through the cell request and response of Appendix A. Cell names start with `dd2_gc1__`.

Option 1 reads a cell request (a Boolean function of up to 4 inputs), builds a static CMOS network (at most 3 transistors in series per stage), orders it along a common Euler path, draws an sky130_fd_sc_hd-compatible cell in the HD frame with GDSfactory, verifies it (DRC, LVS, RC-LVS, abutment, layer check), simulates it with ngspice, and writes its extracted netlists, Liberty, Verilog model and report. Magic, Netgen and ngspice run in the `dd2-layout-tools` container.

Option 2 extracts and-inverter graphs from synthesized designs with Yosys, enumerates cuts of up to 4 inputs with truth tables, classifies the functions, checks them against the full sky130_fd_sc_hd (HD) library (Exists / Exists with an inverter / Contained / New), estimates the area of new cells, writes cell requests and a Liberty file, and measures what the new cells do to area when Yosys/ABC maps the designs (scripts A and B). Yosys 0.33 runs in the `dd2-yosys` container.

Language: Python 3.11+, packages in `requirements.txt`. The AI is used as a development aid: no AI model runs when the tool runs, so the same input always gives the same output.

## How this project is checked
Pass or fail comes from the check scripts, never from an assistant's opinion.

- `make check`: tool versions, PDK link, given files, the ngspice stress test (must print PASS), and Yosys 0.33 in `dd2-yosys`.
- `make test`: every test, including the broken cases in `tests/broken/`; each broken case must make its check FAIL.
- `make all`: the whole flow, from a clean checkout.
- `scripts/run_checks.sh`: reruns the finished checks and writes their output to `results/`.
- `src/frame_check.py`: the HD frame in `given/plan_hd.json` against Table 1 and the installed cells.
- `src/layer_check.py`: psdm and hvtp over PMOS diffusion, nsdm over NMOS diffusion, npc over poly contacts. Must PASS on the installed nand2_1.
- `src/common/request.py` and `src/cell/network.py`: request validation and the switch-level network check.
- `src/cell/verify.py`, `abutment.py`, `simulate.py`, `compare.py`: Magic DRC (zero errors, checked in a row with tap cells), Netgen LVS, RC-LVS, abutment, ngspice simulation and the comparison with installed HD cells, in the `dd2-layout-tools` container.
- Option 2: Table 1, the AIG sizes, the cut check, and the redundancy checker's self-test against Table 4, under `tests/m2/`.

## Rules the assistant follows (overview, section 4.3)
1. Pass or fail comes from the check scripts, never from the assistant's opinion.
2. Every number in a report comes from a file the flow wrote in `results/`. Design rule values and library data come from the PDK and the given files, never from the assistant.
3. Every check has a broken case in `tests/broken/` that it must fail on.
4. Expected values (Table 1, Table 2, Table 4) appear only in test files, never inside the tool. If the tool's result differs from the handout, report the difference; do not adjust code or definitions just to force a match.
5. Truth-table convention: a truth table is an int; bit i is the output for the input combination in which input k equals bit k of i; input A is the least significant. A 4-input function has 16 bits.
6. Library facts (cell functions, areas) are parsed from the Liberty file at run time. Input support is derived from the function, not from the pin list.
7. Option 1 code goes in `src/cell/`, Option 2 code in `src/hd/`, `src/aig/`, `src/cut_enum/` and `src/table1/`, shared code in `src/common/`.

## What the assistant must never do
1. Do NOT edit check scripts or broken cases: `src/frame_check.py`, `src/layer_check.py`, anything in `tests/` and `tests/broken/`. If a check seems wrong, say so and explain why; a human changes it.
2. Do NOT edit or copy anything from the PDK (`pdk/`) or the given files (`given/`). Both are read-only links and are not committed.
3. Do NOT change the frame in `given/plan_hd.json`, or move rails, n-well or implant edges.
4. Do NOT type design-rule values or layer numbers from memory. Take them from the PDK, the handout tables, or the files in `build/ref/`, and say where each came from.
5. Do NOT weaken a check or a test to make it pass, and do not report a pass without running it.
6. Do NOT use stock ngspice. Use the container's fixed ngspice 47 only.
7. Do NOT commit `pdk`, `given`, `build/`, `.venv`, copies of the given files, or files over 50 MB.
8. Do NOT invent a number, a cell name, or a library value that is not in a file.
9. Do NOT write code the author cannot explain line by line; every member must be able to explain every part.
10. Do NOT move a tag.
11. Say plainly when something is uncertain or unchecked.

## Conventions
- Code in `src/`, tests in `tests/`, broken cases in `tests/broken/`, every table and log used in the reports in `results/`.
- Paths come from `make setup` (`PDK_ROOT`, `HD_LIB_FULL`, `GIVEN`); never hardcode a user's home directory.
- Commit messages are short and imperative. AI-assisted commits carry the trailer `AI-assisted: <tool>/<model>`.
- Log AI use in `ai/use_log.md` and AI mistakes caught by checks in `ai/mistakes_log.md`.

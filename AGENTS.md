# Instructions for the AI assistant

Write this file before any code, and commit it first (overview, section 4.1).

## The project
<DD2 Project 1 option 1 (Boolean function to HD cell) is a tool that reads a Boolean function (up to 4 inputs) and produces an
sky130_fd_sc_hd-compatible cell's GDS, extracted netlists, Liberty, Verilog model, report>

## How this project is checked
Pass or fail comes from the check scripts, never from an assistant's opinion.

- make check: tool versions, PDK link, and the ngspice stress test (must print PASS).
- make test: every test, including the broken cases in tests/broken/.
- src/layer_check.py: psdm and hvtp over PMOS diffusion, nsdm over NMOS diffusion, npc over poly contacts. Must PASS on the installed nand2_1.

## What the assistant must never do
1. Do NOT edit check scripts or broken cases: `src/layer_check.py`, `src/request.py`,
   `src/network.py`, anything in `tests/` and `tests/broken/`. If a check seems wrong,
   say so and explain why; a human changes it.
2. Do NOT edit or copy anything from the PDK (`pdk/`) or the given files (`given/`).
   Both are read-only links and are not committed.
3. Do NOT change the frame in given/plan_hd.json, or move rails, n-well or implant edges.

## Conventions
<Python 3, code is in the src file, results in `results/`.
- AI-assisted commits carry the trailer `AI-assisted: <tool>/<model>`.
- Log AI use in `ai/use_log.md` and AI mistakes caught by checks in `ai/mistakes_log.md`.

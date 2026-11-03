# Project 1, Option 3: py-logic2cell

## 1. Group

GC1 · Option 3 (Options 1 and 2) · AI used as a development aid

| Name         | Student ID |
| ------------ | ---------- |
| Yomna Othman | 900231105  |
| Jacques Elia | 900233349  |

## 2. Quick start
Tools: Python 3.14.8 (gdsfactory 9.51.0, klayout 0.30.12), Magic 8.3.684, Netgen 1.5.133 (the git tag reports itself as 1.5.132), ngspice 47 with the BSIM4 fix (sha256 083dd184… as built on the machine of `results/ngspice_builds.txt`; the hash depends on where the image was built, so every Liberty file records its own), Yosys 0.33 and its ABC (in the `dd2-yosys` container), OpenSTA 3.1.0 (`dd2-opensta`, commit f2f431a), Icarus Verilog 13.0, Docker.

    make setup     # links pdk/ and given/, makes .venv, builds the two containers: ~20 min the first time, seconds after
    make check     # tool versions and the ngspice stress test: ~1 s
    make all       # the whole flow: ~1 min
    make test      # every test and broken case: ~40 s

`make setup` expects the student pack next to this repo (`GIVEN=../DD2_Project1_student_pack/given`) and searches for the PDK under `~/.ciel`; override with `GIVEN=...`, `PDK_ROOT=...`, or `PDK=...`.

## 3. What the tool does

Option 2 finds small functions that designs compute again and again and checks which ones HD lacks; Option 1 turns a function into a verified HD-compatible cell. They meet in the cell request and response of Appendix A (`docs/interface/`).

Option 1, per request: read and check the request → find the smallest single static CMOS stage (≤ 3 transistors in series) → switch-level check → common Euler path → draw the cell in the HD frame → DRC (in a row with tap cells), LVS, RC-LVS, abutment, layer check → DC and transient simulation of the extracted netlist → compare with the installed HD cell → response.

Option 2: map the designs onto the usable and reduced HD libraries (Table 1) → write the AIGs before and after ABC → enumerate checked 4-input cuts with truth tables → classify them against the full HD library (Table 3 classes) → estimate area, rank candidates, write cell requests, and generate a Liberty extension.

## 4. Commands

| Command                                            | Input                                     | Output                                                                                  |
| -------------------------------------------------- | ----------------------------------------- | --------------------------------------------------------------------------------------- |
| `make demo IN=<request.json>`                      | a cell request                            | `cells/<name>/` (GDS, schematic, report, response), work files in `build/cells/<name>/` |
| `python -m src.cell.build <request> [--hd <cell>]` | a request, and an HD cell to compare with | same as above, plus `vs_hd.png`                                                         |
| `python -m src.common.request <request>`           | a request                                 | its truth table, or why it is refused                                                   |
| `python -m src.cell.network <request>`             | a request                                 | the networks, switch-level check, Euler order, schematic                                |
| `python -m src.cell.rules`                         | `src/cell/layout.py`, PDK DRC decks       | `results/design_rules.csv`                                                              |
| `python -m src.map_library.table1`                 | `given/designs`, `given/*.lib`            | `results/table1.csv`, `build/map/*.log`                                                 |
| `python -m src.map_library.map_extended`           | `build/libs/hd_reduced_ext.lib`           | `results/table1_extended.csv`, `build/map_extended/*.log`                               |
| `python -m src.aig.aigs`                           | `given/designs`                           | `build/aigs/`, `results/aig_sizes.csv`                                                  |
| `python -m src.cut_enum.write_cuts`                | `build/aigs/`                             | checked raw/ABC cut tables in `results/cuts/`                                           |
| `python -m src.hd.cut_classes`                     | `results/cuts/`                           | `results/hd/cut_classes.csv`, `results/hd/a_node.csv`                                   |
| `python -m src.hd.area_model`                      | cut classes and PDK cell data             | `results/hd/area_model.csv`                                                             |
| `python -m src.hd.rank`                            | cut classes and area estimates            | `results/hd/candidates.csv`, `results/hd/ranked.json`                                   |
| `python -m src.hd.request_writer [--limit N]`      | ranked candidates                         | `requests/candidates/`                                                                  |
| `python -m src.hd.liberty_writer [--limit N]`      | ranked candidates and HD Liberty data     | `libs/new_cells.lib`, `build/libs/hd_reduced_ext.lib`                                   |
| `python -m src.hd.classes`                         | HD Liberty                                | `results/hd/hd_classes.csv`                                                             |
| `python -m src.hd.table4`                          | HD Liberty                                | `results/table4.txt`                                                                    |
| `python -m src.map_library.table5`                | designs and reduced/extended Liberty      | `results/table5.csv`, `build/equiv/*.log`                                               |
| `scripts/run_checks.sh`                            |                                           | frame, layer and front-end check logs in `results/`                                     |
| `make table5` | the six installed reference cells, HD TT Liberty | every row of Table 5 except the design level, in `results/` (~6 min) |
| `python -m src.cell.char_validate [--image dd2-ngspice-stock --tag _stock] [--full-ramp]` | installed HD cells | `results/char_validation<tag>.txt`, `_entries.csv`, `_caps.csv` |
| `python -m src.cell.liberty_write validation` | `build/char/*/..._timing.json` | `libs/char_validation.lib`, `build/sta/hd_tt_ours.lib` (HD with the six cells replaced) |
| `python -m src.cell.liberty_check <lib> ...` | Liberty files | `results/liberty_syntax.txt` (Yosys and OpenSTA) |

## 5. Layout

- `src/common/`: request reader and response writer, smallest single stage for a truth table, Yosys runner
- `src/cell/`: Option 1 (network, layout, verify, abutment, simulate, compare, build, rules)
- `src/hd/`, `src/aig/`, `src/cut_enum/`, `src/map_library/`: Option 2
- `src/frame_check.py`, `src/layer_check.py`, `src/extract_cells.py`: HD frame and layer checks
- `requests/`: cell requests; `cells/`: generated cells; `results/`: every table and log the reports use
- `tests/`: tests; `tests/broken/`: broken cases
- `docker/yosys/`: the Yosys 0.33 container; `docker/opensta/`: OpenSTA; `docker/ngspice-stock/`: stock ngspice 47, only for the Simulator row of Table 5
- `libs/`: Liberty files we write; `ai/`: AI logs; `report/`: reports

## 6. Results

- `cells/dd2_gc1__inv_1/`, `cells/dd2_gc1__nand2_1/`: both pass DRC (0 errors), LVS, RC-LVS, abutment (15 cases, 0 errors), the layer check and simulation; LVS-match the installed HD cells including W and L; 3 sites wide like HD; frame layers XOR to zero against HD.
- `results/design_rules.csv`: the rule behind every number in the layout; gate pitch 0.42 µm = poly.1a + 2 licon.11 + licon.1.
- `results/frame_check.txt`, `results/layer_check_*.txt`: the HD frame and layer checks.
- `results/table1.csv`: Table 1 reproduced exactly with Yosys 0.33.
- `results/table1_extended.csv`: the required designs mapped with the generated extended reduced library.
- `build/map/*.log`: complete baseline mapping logs used to split combinational and sequential area during ranking.
- `build/map_extended/*.log`: complete extended-library mapping logs.
- `results/aig_sizes.csv`: AIG sizes match Table 2 exactly (with `write_aiger -zinit`); ABC restructuring shrinks every design.
- `results/cuts/<design>_{raw,abc}.csv`: every non-trivial cut of up to four leaves, with its truth table and cone size; each table is checked against an independent simulation before being written.
- `results/hd/hd_classes.csv`: the class table of HD.
- Table 5 (characterizer validation, six reference cells, 7x7, 2744 entries): fixed ngspice median |error| 3.40% (`results/char_validation.txt`), every input capacitance within +5.3%; stock ngspice 5.26%, over the 5% limit (`results/char_validation_stock.txt`); full-ramp broken case flagged (`results/char_validation_fullramp.txt`); our Liberty loads in Yosys and OpenSTA with no errors (`results/liberty_syntax.txt`); the stress test passes on the course image and fails on the stock one (`results/ngspice_builds.txt`).
- `results/hd/cut_classes.csv`, `results/hd/a_node.csv`: NPN-reduced cut classes, occurrences, and per-design AND-node weights.
- `results/hd/area_model.csv`: transistor-to-site area estimates calibrated from the PDK's x1 cells.
- `results/hd/candidates.csv`, `results/hd/ranked.json`: Table 3 classification, buildability, estimated area, and cross-design candidate ranking.
- `requests/candidates/`: the top-ranked candidate requests; `libs/new_cells.lib` contains the corresponding Liberty groups and `build/libs/hd_reduced_ext.lib` combines them with the reduced HD library.
- `results/table4.txt`: Table 4 reproduced (24 / 20 / 38 / 3822, 9 one-stage, 6 + 2 read-once), except one row: we find 6 new single-stage functions within 3 in series and 12 transistors, the handout says 5. All 6 are listed.
- `results/table5.csv`: baseline reduced-library area, extended-library area, area reduction, generated-cell instances, and Yosys CEC equivalence for each design and mapping script.

## 7. Tests

`make test` runs pytest on `tests/` and the frame check. Each check and the broken case it must fail on:

| Check                      | Broken case                                                                                                                             |
| -------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| request reader             | wrong truth table, 5 inputs, 2 outputs, unknown input, Liberty syntax, swapped bit order, wrong group prefix (`tests/broken/requests/`) |
| switch-level network check | deleted pull-up, deleted pull-down, wrong table (`tests/broken/networks.json`)                                                          |
| design rule table          | contact 0.045 µm from the gate                                                                                                          |
| DRC                        | diffusion overlap of contact 0.03 µm (licon.5a)                                                                                         |
| LVS                        | 5 nm gap in the output wire                                                                                                             |
| abutment                   | n-well stopping short of the cell edge                                                                                                  |
| layer check                | hvtp removed (`tests/broken/make_no_hvtp.py`)                                                                                           |
| simulation                 | one pull-up deleted from the extracted netlist                                                                                          |
| frame check                | plan with the n-well moved up 0.1 µm                                                                                                    |
| Table 1, AIG sizes         | compared with the handout's numbers                                                                                                     |
| Table 5 CEC | tampered mapped netlist must be rejected (`tests/m2/test_table5.py`) |
| cut enumerator             | corrupted truth table, merge ignoring inverted edges, dominated cuts kept                                                               |
| cut and Liberty writers    | corrupted cut output, missing request fields, unclosed Liberty cell; Yosys 0.33 import and mapping smoke tests                          |
| redundancy checker         | every HD cell must come out Exists; Table 4 counts                                                                                      |

## 8. AI use

AGENTS.md · ai/use_log.md · ai/mistakes_log.md · report/ai_report.pdf

## 9. Limitations

- Generated cells are not characterized yet and there is no Verilog model, so the model-level simulation of section 4.2 is not run; the generated Liberty extension carries placeholder timing from `inv_1`.
- Option 2 works with estimated areas; real cells from Option 1 replace them in week 3.

## 10. Third-party files

| File                                                                                                            | Source                                                                      | Licence                                          |
| --------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------- | ------------------------------------------------ |
| `src/cell/verify.py` (Magic scripts, RC collapse), `src/cell/abutment.py` (placement idea), `src/cell/tools.py` | adapted from the course's Tutorial 3 code                                   | course material                                  |
| `docker/yosys/Dockerfile`                                                                                       | Ubuntu 24.04 `yosys` package                                                | ISC (Yosys)                                      |
| `given/` (designs, libraries, plan), `pdk/`                                                                     | student pack and SkyWater SKY130 PDK; linked by `make setup`, not committed | each design keeps its own notice; PDK Apache-2.0 |

# <Project 1, Option N: tool name>

## 1. Group
<names and student IDs> · Option <1, 2 or 3> · AI used as <a development aid | an agentic system>

## 2. Quick start
Tools: Yosys <version>, Icarus <version>, Magic <version>, ngspice <build and hash>, Python <version>

    make setup     # <minutes>
    make check     # <minutes>
    make all       # <minutes>

## 3. What the tool does
<one paragraph, then the order of the steps>

## 4. Commands
| Command | Input | Output |
|---|---|---|
| make demo IN=<file> | <request or design> | <what it writes, and where> |

## 5. Layout
<one line per folder>

## 6. Results
<one line per deliverable: where it is, and its headline number>

Member 2 CP1 results:
- `results/hd/hd_classes.csv`: 324 eligible full-HD combinational cells, 78 P-classes.
  The parser excludes sequential, multi-output, tri-state, and no-function outputs;
  constant-function cells are retained when they have one ordinary Boolean output.
- `results/hd/redundancy_selftest.txt`: 3,904 full-support P-classes classified as
  Exists 24, Exists with an inverter 20, Contained 38, and New 3,822.
- The class-table `single_stage` field uses the documented CP1 interpretation:
  `yes` means negative-unate in every functional input, matching a static-CMOS
  pull-down realization; `no` means the function is not negative-unate in every input.

## 7. Tests
<what make test checks; the broken case for each check>

Member 2: `make m2-check` runs the parser, class, and redundancy tests and the
intentional broken redundancy case. The current run passes 16 tests and catches
the broken case.

## 8. AI use
AGENTS.md · ai/use_log.md · ai/mistakes_log.md · report/ai_report.pdf

## 9. Limitations
<what does not work yet>

The shared top-level `make check`, `make test`, `make all`, and `make demo`
targets still require team integration with Member 1's flow. Member 2's
`m2-check` and `m2-all` targets are implemented.

## 10. Third-party files
<file, source, licence>

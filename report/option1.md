# Option 1: from a Boolean function to an HD cell

Source for the Option 1 sections of `report.pdf` (Option 1 handout, section 8.3). Every number is copied
from the file named next to it; regenerate that file and copy again, never edit a number by hand.
Sections marked TODO wait for files the flow has not written yet.

## Method

One command per cell, `python -m src.cell.build <request.json> [--hd <cell>]`, then
`python -m src.cell.deliver` and `python -m src.cell.model_check` (`make demo IN=<request>` runs all three).
The steps of handout section 4:

1. **Request.** `src/common/request.py` parses the expression, computes its truth table (input A is bit 0)
   and refuses the request if it disagrees with the request's table, or has more than 4 inputs or more than
   one output.
2. **Network.** If the function is negative unate in every input and has a factored form with at most 3
   transistors in series, one stage (`src/common/stage.py`); otherwise a split into stages
   (`network.split`). Pull-down from F (AND in series, OR in parallel), pull-up as its dual, every series
   order (`network.reorders`). Every variant is checked at switch level for all input combinations,
   including that VPWR never reaches VGND (`network.cell_check`).
3. **Sizing.** `hd`: every NMOS 0.65 um, every PMOS 1.00 um (for the reference cells, the widths read from
   the installed cell's SPICE netlist). `stack`: each transistor of the output stage multiplied by the depth
   of its series stack and folded to fit its row (`build.stacked`); inner stages x1.
4. **Ordering.** Every common Euler path of both rows (`network.euler_orders`, the method of Uehara and
   vanCleemput), fewest diffusion contacts first; where none exists, up to 3 diffusion breaks, cut only in
   the row whose net changes. Orders are placed narrowest lower bound first, in parallel, and an order whose
   bound is wider than a plan already found is skipped.
5. **Drawing.** GDSfactory, inside the frame of `given/plan_hd.json`. Gates on a 0.42 um pitch over a
   contacted column (poly.1a + 2 x licon.11 + licon.1) and 0.36 um over shared diffusion (poly.1a + poly.2),
   `results/design_rules.csv`, which lists the rule behind every number in the plan. Wiring on li1; met1
   inside the cell only where li1 cannot route, and an li1-only plan wins over a met1 plan of equal or
   smaller width.
6. **Verification.** Magic DRC in a row with tap cells, Netgen LVS and RC-LVS, abutment with tap, inv_1
   and fill (side by side, mirrored, flipped on both rails), the layer check (`src/layer_check.py`).
7. **Transistor-level simulation** of the RC-extracted netlist (`src/cell/simulate.py`).
8. **Characterization and views** (`src/cell/deliver.py`): SA and SB of every finger from the layout
   (`src/cell/stress.py`), every table on the grid of the HD cell with the same function (found by truth
   table over every pin order) or inv_1's for a new function; Liberty cell, Verilog model, response.
9. **Use** (`src/cell/model_check.py`, `src/cell/design_use.py`): the round trip of section 3.3, and SPM
   mapped onto HD plus our cells, simulated and timed.

## Ordering

TODO from `results/table6_vs_hd.csv` (`breaks_ours`, `breaks_hd`) and each `cells/<name>/build.log`
(the Euler orders tried and why each failed): which test functions have no common Euler path, and what the
breaks cost in width.

## Comparison with HD

TODO from `results/table6_vs_hd.csv`, `results/table6_timing.csv`, `results/timing_vs_hd.txt` and
`results/differences_vs_hd.md`.

## Sizing

The two sizings of !(A | B | C): `results/nor3_sizings.csv`. TODO numbers.

The stack sizing could not be drawn. Folded into three parallel chains, its PMOS row needs 18 transistors
in 9 gate columns, and the best order (C B A A B C C B A) leaves B in three separate runs of gates, each
needing its own poly contact in the one-track middle band; with a contact on almost every column, the
output has no column left to cross between the rows (`cells/dd2_gc1__nor3_1_stack/build.log`: "no room
for the B contact"; a much larger contact search fails the same way, so it is not the search budget). Its width is therefore given as
the generator's lower bound, and its delay from the schematic, beside the hd sizing's schematic delay so
the two compare like for like.

What high-Vt PMOS costs in rising delay: the `schematic, standard-Vt PMOS` rows of the same file. TODO.

## Candidates from Option 2 that we could not build (overview, section 2, rule 3)

TODO the final list from `cells/dd2_gc1__f*/response.json`. So far, two single-stage candidates are refused:
f011f (rank 1, `!((C & D) | ((A | B) & (C | D)))`) and f0017 (rank 5,
`!(D | ((A | B) & (C | (A & B))))`). Both have 12 transistors in one stage. Over every Euler order of every
series order (`cells/<name>/build.log`), half fail because the output has contacts on both sides of other
nets' contacts in both rows and cannot be joined between the rows on li, and the rest because a poly
contact finds no room in the middle band. Our generator joins the rows on li only and uses met1 just to
bridge contacts in the middle band, as the handout allows met1 only inside multi-stage cells; a met1 path
between the rows, or a split of these functions into two stages, would be the fix.

## Characterization

The characterizer against the shipped Liberty for the six reference cells (`results/char_validation.txt`):
median |error| 3.40% over 2744 delay and transition entries with the fixed ngspice (limit 5%), every input
capacitance within +5.3%. The largest error, +379.0%, is at a21oi_1 B1 cell_fall, slew 1.5 ns, load
0.0005 pF: the slowest input ramp into the smallest load, where the output switches while the input is still
moving and the delay is a small difference of two large times. With the stock ngspice the median is 5.26%
and fails the limit (`results/char_validation_stock.txt`): the stock BSIM4 code discards the stress effect
of SA and SB on mobility (stress test: current ratio 1.03504 with the fixed build, 1 with the stock one,
`results/ngspice_builds.txt`). The broken case, tables indexed by the full ramp, is flagged
(`results/char_validation_fullramp.txt`). Design level: our six cells in place of HD's change SPM's worst
path by +0.5 ps (+0.06%) (`results/spm_design_level.txt`).

## Function

Every cell is simulated at three levels: switch level (`build.log`, step 3), transistor level on the
RC-extracted netlist (`report.json`, key `simulation`), and model level (`cells/<name>/model_check.json`).
TODO: charge sharing found by the transient, from each `report.json`.

## Limits

Properties of a production cell that none of our checks covers:
- power: no leakage or internal-power tables in the Liberty;
- corners: TT only (no FF/SS), and no `when` (state-dependent) timing arcs; the side input is always the
  slowest setting;
- the LEF view, router pin access and a placement test (OpenROAD);
- electromigration and IR drop on the rails, antenna rules on long poly;
- a second simulator (Xyce) on a few points;
- reproducibility of a Liberty byte for byte from cached simulations (we record the ngspice hash only).

What our layout cannot do: rows with different gate orders or finger counts (the stack sizing of nor3),
double-height cells, and single stages too dense for one li track in the middle band, which now fall back
to a split into stages. A generator that routes on met2/met3 and puts pins there (as the public cellweaver
generator does: 7.82, 11.04 and 11.5 um wide on our three refused candidates, before its own DRC/LVS,
pins on met3, `results/cellweaver_comparison.txt`) would draw them, but its
cells would fail the pin and wiring rows of Table 4.

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

Every single-stage test function has a common Euler path: no Table 6 cell of one stage needed a
diffusion break (`results/table6_vs_hd.csv`, `breaks_ours`). HD's own a22oi_1 uses two
(`breaks_hd`), we use none at the same 6 sites. The breaks come from the multi-stage cells, where
stages share no diffusion node to run on: a21o_1 has 1 (HD 1), mux2_1 2 (HD 0) and xor2_1 2 (HD 1).
A break is cut only in the row whose net changes; where both rows keep the same net the row runs on
(network.joined), as in HD's a21o_1.

Cost: at a break the diffusion ends half a contact and licon.5a past the last contact and starts
again diff/tap.3 later, so two contact centres sit 0.17/2 + 0.04 + 0.27 + 0.04 + 0.17/2 = 0.52 um
apart where shared diffusion would have one contact (`results/design_rules.csv`: licon.1, licon.5a,
diff/tap.3), a little over one site (0.46 um) per break. That is xor2_1's second site over HD
(9 against 7 sites with 2 breaks against 1); mux2_1 absorbs its two breaks and stays at HD's 9 sites.

## Comparison with HD

Widths (`results/table6_vs_hd.csv`): of the 14 Table 6 functions with an HD cell, 10 are as wide as
HD and 4 wider: o21ai_1 and o22ai_1 by one site, maj3_1 by one, xor2_1 by two. All reference cells
match HD's transistors including every W and L, its frame, pins and wiring layers (Table 4);
`results/differences_vs_hd.md` gives each difference and its cause.

- o21ai_1 (5 against 4 sites): HD puts the A2 and B1 inputs in a diffusion row band, outside the npc
  band where Table 2 requires input pins; with all three pins in the npc band, the B1 contact needs a
  0.6 um gate pitch where HD has 0.42 to 0.48 (`cells/dd2_gc1__o21ai_1/report.json`, `compare.gates`).
- xor2_1: one break more than HD (Ordering).
- o22ai_1 (6 against 5 sites): the cause of o21ai_1 again. HD puts three of its four inputs (A2, B1,
  B2) in a row band and bends its poly, so its PMOS gates sit at 0.375, 0.615 and 0.36 um and its NMOS
  gates at 0.435, 0.505 and 0.42; ours keep all four inputs in the npc band at 0.42, 0.66 and 0.48 um.
- maj3_1 (9 against 8 sites): gate pitch. HD's seven gates are 0.36 to 0.42 um apart, mostly the pitch
  over shared diffusion (0.36 um, poly.1a + poly.2, `results/design_rules.csv`); ours are 0.60 to 0.66 um
  apart: the placer widens columns beyond 0.42 um until every poly contact and crossing finds room
  (`layout.place`), and for maj3_1 the narrowest plan it found has every column widened.
  (Comparison by `src/cell/compare.py`, which Table 6 runs for every pair.)

Delay and slew at the HD table point nearest 100 ps and 10 fF (`results/table6_vs_hd.csv`), against the
HD cell characterized by our own flow (the like-for-like comparison; the shipped value is in
`delay_hd_shipped_ns`). Where we are as wide as HD the slowest delay is within 4.5%, except three
multi-stage cells that are faster: and2_1 -17.6%, mux2_1 -18.7%, maj3_1 -17.6%. Their inner stages are
x1 (0.65/1.00 um, handout step 3) where HD's are 0.42/0.42 um (the installed cells' SPICE netlists in the
PDK against our `cell.spice`), so ours drive their output stage harder, at the price of more input
capacitance. The wider cells cost delay where the
extra site lengthens the output: o21ai_1 +2.4%, o22ai_1 +3.6%, xor2_1 +8.9%. Every pin's value is in
`results/table6_timing_pins.csv`.

For the six reference cells, characterized on their own HD grid (`results/timing_vs_hd.txt`): the
slowest arc differs from HD's by +0.1% (inv_1), +0.2% (nand2_1), +1.8% (nor2_1), -1.9% (nand3_1),
-0.9% (a21oi_1) and +2.4% (o21ai_1), all within the characterizer's own error against the shipped
Liberty (median 3.40%, Characterization), so none of these differences is a measured gain or loss.

Use: in the round trip of section 3.3, ABC picks our cell from the whole reduced library for 19 of the
25 delivered cells (`cells/<name>/model_check.json`, `chosen_freely`); the six it does not pick are
those HD covers more cheaply (o21ai_1, o22ai_1, a31oi_1, maj3_1, xor2_1, or_and_maj). Mapped onto HD
plus our cells, SPM uses 33 of them, 31 of them Option 2's candidate f077f, passes Tutorial 4's
testbench, and times at 0.9161 ns worst path against 0.7728 ns with HD alone
(`results/design_use.txt`, `results/spm_design_level.txt`): our cells make SPM slower, which is the
measurement and not a reason to change it.

## Sizing

The two sizings of !(A | B | C) (`results/nor3_sizings.csv`, `cells/dd2_gc1__nor3_1*/`):

- hd: every NMOS 0.65 um, every PMOS 1.00 um; 4 sites, 6 transistors.
- stack: each transistor times the depth of its series stack, folded to fit its row
  (`build.stacked`): NMOS 1 x 0.65 um each (depth 1), PMOS 3 fingers of 1.00 um each (depth 3, 3 um).
  The rows then have different finger counts, 3 against 9; the Euler walk gives the PMOS row columns of
  its own where the NMOS diffusion runs on under the gate, whose poly stops at the middle band. As HD
  folds its nor3_2 (A A B B C C), each input's fingers sit side by side under one poly contact
  (C C C B B B A A A), and the PMOS internal node p1, which then repeats along the row, is joined by
  a met1 line along it: 10 sites, every check passed (`cells/dd2_gc1__nor3_1_stack/build.log`).

Both extracted and characterized on nor3_1's grid, at the point nearest 100 ps and 10 fF
(`results/nor3_sizings.csv`, view `extracted`), stack against hd:

| Pin | cell_rise | cell_fall | rise_transition | fall_transition | input capacitance |
|---|---|---|---|---|---|
| A | -43.7% | +11.9% | -47.7% | +10.3% | +102.4% |
| B | -35.5% | +21.3% | -46.3% | +19.7% | +107.4% |
| C | -32.7% | +27.5% | -46.3% | +29.7% | +109.6% |

The stack sizing triples the PMOS stack's width, so the rise, through three PMOS in series, is a third
to almost half faster; the NMOS are the same 0.65 um, so the fall gets slower by the extra drain
capacitance on Y from nine PMOS fingers. It costs 12.512 um2 against 5.0048 (10 sites against 4) and
doubles every input's capacitance, which slows whatever drives it.

Which to put in a library: the hd sizing, as x1. At the same load the stack cell is a different drive
strength, two and a half times the area for a rise that is still slower than its fall; a library gets
that from a larger drive (HD's nor3_2 and nor3_4) and keeps its x1 cell small, as HD does: nor3_1 is
the hd sizing, transistor for transistor (`results/differences_vs_hd.md` for the reference cells,
`results/table6_vs_hd.csv`, `lvs_vs_hd` for nor3_1).

What high-Vt PMOS costs in rising delay, measured on the hd sizing's schematic with pfet_01v8_hvt and
again with pfet_01v8 (`results/nor3_sizings.csv`, views `schematic` and `schematic, standard-Vt PMOS`):
cell_rise is 31.6% (A), 31.8% (B) and 32.6% (C) slower with high Vt, rise_transition 25.7 to 25.8%
slower, and cell_fall unchanged (within 0.2%), since the NMOS do not change. In nor3 the rising output
goes through three high-Vt PMOS in series, which is where the high Vt costs most.

## Candidates from Option 2 (overview, section 2, rule 3)

Option 2's candidate requests (`requests/candidates/`, ranks from `results/hd/ranked.json`). Delivered,
each with its Liberty and Verilog views, model check and round trip passed, chosen freely by ABC, and
accepted by Option 2's intake (`results/hd/real_cells.csv`): f011f (rank 1), f17ff (rank 4), f077f
(rank 6), f17 (rank 9) and f001f. f077f is the cell SPM uses 31 times in step 9 (`results/design_use.txt`).

f011f and f17ff are one stage of 12 transistors, 8 sites each. On li alone no Euler order of them can be
drawn: the output has contacts on both sides of other nets' contacts in both rows, so its li cannot
reach the crossing between the rows, or a poly contact finds no room in the one-track middle band
(`cells/<name>/build.log`). Handout step 5 allows met1 where li cannot route; the generator then joins
such a net's contacts with a met1 line along its row, and crosses between the rows on met1 where its li
cannot (`layout.finish`), only after every order has failed on li, so no cell that draws on li changes.

TODO the remaining candidates (f0017, f2b, f02ab, f002b, f2bff) from the rebuild in progress
(`cells/dd2_gc1__f*/response.json`). A candidate that still cannot be built is reported with its reason,
and the group may ask the instructor for it (overview, section 2, rule 3).

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
All 25 delivered cells, and nor3_1_stack, pass all three. The transient visits every input
combination and toggles each input from every state, with the slew and load of the HD table point; Y
must come within 10% of the right rail before the next edge and never cross VDD/2 when it should hold
(`src/cell/simulate.py`). No cell failed either test, so the transient found no charge sharing large
enough to matter at that load, and we changed nothing for it. The deepest stacks (three in series:
nand3_1, nor3_1, a31oi_1, o31ai_1 and the 4-input cells) are where it would show first.

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

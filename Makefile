# DD2 Project 1: the targets the overview requires (section 5.1).

PDK_ROOT ?= $(HOME)/.ciel
GIVEN    ?= ../DD2_Project1_student_pack/given
IN       ?=
# Tutorial 4's folder: SPM, its testbench and constraints (step 9, src/cell/design_use.py)
TUT4     ?= ../../tut4/student
TOP      ?=
SV       ?=
TUT2     ?=
ROUNDS   ?= 2
PER_ROUND ?= 3

.PHONY: setup check test all real full demo demo2 loop clean table5 gls gls-real

PDK      ?= $(firstword $(wildcard $(PDK_ROOT)/sky130A $(PDK_ROOT)/ciel/sky130/versions/*/sky130A))
PY       := .venv/bin/python
export HD_LIB_FULL ?= pdk/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib

setup:            ## environment, and links to the PDK and the given files
	@test -n "$(PDK)" || (echo "no sky130A under $(PDK_ROOT), pass PDK=<path>" && exit 1)
	ln -sfn $(PDK) pdk
	ln -sfn $(GIVEN) given
	test -d .venv || python3 -m venv .venv
	$(PY) -m pip install -q -r requirements.txt
	docker run --rm dd2-layout-tools test -x /opt/dd2/stress_test/check_stress.sh 2>/dev/null \
		|| docker build -t dd2-layout-tools $(GIVEN)/../container
	docker build -q -t dd2-yosys docker/yosys
	docker build -q -t dd2-opensta docker/opensta
	docker build -q -t dd2-ngspice-stock docker/ngspice-stock

check:            ## tool versions, PDK, and the ngspice stress test for Option 1
	@test -d pdk || (echo "pdk link missing: run make setup" && exit 1)
	@test -f given/hd_reduced.lib || (echo "given files missing: run make setup" && exit 1)
	yosys -V
	iverilog -V 2>/dev/null | head -1
	$(PY) --version
	docker run --rm dd2-layout-tools magic --version
	docker run --rm dd2-layout-tools netgen -batch quit
	docker run --rm dd2-layout-tools /opt/dd2/stress_test/check_stress.sh
	docker run --rm dd2-yosys yosys -V | grep -q "Yosys 0.33" || (echo "dd2-yosys is not Yosys 0.33" && exit 1)
	@echo "check: OK"

test:             ## every test, including the broken cases in tests/broken/
	$(PY) -m src.hd.liberty_writer --limit 10    # the Liberty the mapping test reads, else it skips
	$(PY) -m src.cell.characterize hd inv_1 --grid 2 --tag _test > /dev/null    # SA/SB of inv_1 for test_characterize, else it skips
	$(PY) -m pytest -q tests
	$(PY) src/frame_check.py


all:              ## the whole flow with estimated areas (about 20-30 min)
	$(PY) -m src.map_library.table1
	$(PY) -m src.aig.aigs
	$(PY) -m src.hd.table4
	$(PY) -m src.cut_enum.write_cuts
	$(PY) -m src.hd.cut_classes
	$(PY) -m src.hd.area_model
	$(PY) -m src.hd.rank
	$(PY) -m src.hd.greedy
	$(PY) -m src.hd.request_writer --final-set
	$(PY) -m src.hd.liberty_writer --final-set
	$(PY) -m src.map_library.map_extended
	$(PY) -m src.map_library.table5
	$(PY) -m src.hd.classes
	$(PY) -m src.cell.rules
	for r in requests/hd/*.json; do $(PY) -m src.cell.build $$r --hd $$(basename $$r .json) || exit 1; done
	for r in requests/test/*.json; do $(PY) -m src.cell.build $$r || exit 1; done
	for r in requests/hd/*.json requests/test/*.json; do \
		$(PY) -m src.cell.deliver $$r && $(PY) -m src.cell.model_check $$r || exit 1; done
	for r in requests/candidates/*.json; do \
		$(PY) -m src.cell.build $$r && $(PY) -m src.cell.deliver $$r && $(PY) -m src.cell.model_check $$r \
		|| echo "$$r: not delivered, see its response.json"; done
	for r in requests/sizing/*.json; do $(PY) -m src.cell.build $$r && $(PY) -m src.cell.deliver $$r \
		|| echo "$$r: not delivered, see its response.json"; done
	# Option 2 with the cells Option 1 delivered (Appendix A responses)
	$(PY) -m src.hd.best_of_both
	$(PY) -m src.hd.curve
	$(PY) -m src.hd.real_cells --final-set
	$(PY) -m src.hd.sensitivity
	cp results/hd/sensitivity_30.txt results/hd/sensitivity_30_estimated.txt
	cp results/hd/sensitivity_30.csv results/hd/sensitivity_30_estimated.csv
	$(PY) -m src.hd.sta
	$(PY) -m src.hd.analysis
	$(PY) -m src.cell.table6
	$(PY) -m src.cell.char_validate      # the six installed cells, characterized: timing_vs_hd compares with them
	$(PY) -m src.cell.timing_vs_hd
	$(PY) -m src.cell.differences
	$(PY) -m src.cell.design_use $(TUT4)

real:             ## step 11: build the final set with Option 1, take real cells in, remap and measure
	for n in $$($(PY) -c "import json;print(' '.join(json.load(open('results/hd/final_set.json'))['cells']))"); do \
		$(PY) -m src.cell.build requests/candidates/$$n.json && $(PY) -m src.cell.deliver requests/candidates/$$n.json \
		&& $(PY) -m src.cell.model_check requests/candidates/$$n.json || true; done
	$(PY) -m src.hd.real_cells --final-set
	@if grep -Eq '^[^,]*,[^,]*,real,' results/hd/real_cells.csv; then \
		$(PY) -m src.hd.liberty_writer --final-set --real && \
		$(PY) -m src.map_library.table5 --real && \
		$(PY) -m src.hd.best_of_both --real && \
		$(PY) -m src.hd.curve --real && \
		$(PY) -m src.hd.sensitivity --real && \
		cp results/hd/sensitivity_30.txt results/hd/sensitivity_30_real.txt && \
		cp results/hd/sensitivity_30.csv results/hd/sensitivity_30_real.csv && \
		$(PY) -m src.hd.sta --libraries reduced extended real && \
		$(PY) -m src.hd.ppa; \
	else echo "real: no cell has an accepted Liberty file yet; the estimated results stand"; fi

full: all real    ## everything, start to finish


demo:             ## what the interview runs: make demo IN=<request or design>
	@test -n "$(IN)" || (echo "usage: make demo IN=<request or design>" && exit 1)
	$(PY) -m src.cell.build $(IN)
	$(PY) -m src.cell.deliver $(IN)
	$(PY) -m src.cell.model_check $(IN)

demo2:            ## option 2 on one design: make demo2 IN=<design.v> TOP=<top module> [SV=1 for SystemVerilog]
	@test -n "$(IN)" -a -n "$(TOP)" || (echo "usage: make demo2 IN=<design.v> TOP=<top module> [SV=1]" && exit 1)
	$(PY) -m src.hd.demo $(IN) $(TOP) $(if $(SV),--sv)

greedy:
	$(PY) -m src.hd.greedy

loop:             ## option 3 on one design, in rounds: make loop IN=<design.v> TOP=<top> [ROUNDS=2] [PER_ROUND=3] [SV=1]
	@test -n "$(IN)" -a -n "$(TOP)" || (echo "usage: make loop IN=<design.v> TOP=<top> [ROUNDS=2] [PER_ROUND=3]" && exit 1)
	$(PY) -m src.hd.loop $(IN) $(TOP) --rounds $(ROUNDS) --per-round $(PER_ROUND) $(if $(SV),--sv)

table5:           ## the characterizer validation of Table 5 (option 1 handout, section 5.1)
	$(PY) -m src.cell.char_validate
	$(PY) -m src.cell.char_validate --image dd2-ngspice-stock --tag _stock || true    # reported, not required to pass
	! $(PY) -m src.cell.char_validate --full-ramp                                      # the broken case must fail
	$(PY) -m src.cell.liberty_write validation
	$(PY) -m src.cell.liberty_check libs/char_validation.lib build/sta/hd_tt_ours.lib
	mkdir -p build && docker run --rm dd2-layout-tools tar -C /opt/dd2 -c stress_test | tar -C build -x
	for i in dd2-layout-tools dd2-ngspice-stock; do echo "== $$i"; \
		docker run --rm -v "$(CURDIR)/build/stress_test:/st" $$i sh /st/check_stress.sh; echo "exit $$?"; \
	done > results/ngspice_builds.txt


gls:              ## gate-level simulation of SPM and the multiplier: make gls TUT2=../tut_2/student TUT4=../tut_4/student
	@test -n "$(TUT2)" -a -n "$(TUT4)" || (echo "usage: make gls TUT2=<Tutorial 2 folder> TUT4=<Tutorial 4 folder>"; exit 1)
	$(PY) -m src.hd.gls --tut2 "$(TUT2)" --tut4 "$(TUT4)"

gls-real:         ## the same with the real-cell library (after make real)
	@test -n "$(TUT2)" -a -n "$(TUT4)" || (echo "usage: make gls-real TUT2=... TUT4=..."; exit 1)
	$(PY) -m src.hd.gls --tut2 "$(TUT2)" --tut4 "$(TUT4)" --real

clean:            ## removes build/ only; cells/ and results/ are committed outputs
	rm -rf build

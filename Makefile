# DD2 Project 1: the targets the overview requires (section 5.1).

PDK_ROOT ?= $(HOME)/.ciel
GIVEN    ?= ../DD2_Project1_student_pack/given
IN       ?=
TOP      ?=
SV       ?=

.PHONY: setup check test all demo demo2 clean table5

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
	$(PY) -m pytest -q tests
	$(PY) src/frame_check.py

all:              ## the whole flow
	$(PY) -m src.map_library.table1
	$(PY) -m src.aig.aigs
	$(PY) -m src.hd.table4
	$(PY) -m src.cut_enum.write_cuts
	$(PY) -m src.hd.cut_classes
	$(PY) -m src.hd.area_model
	$(PY) -m src.hd.rank
	$(PY) -m src.hd.request_writer --limit 10
	$(PY) -m src.hd.liberty_writer --limit 10
	$(PY) -m src.map_library.map_extended
	$(PY) -m src.map_library.table5
	$(PY) -m src.hd.real_cells
	$(PY) -m src.hd.sensitivity
	$(PY) -m src.hd.sta
	$(PY) -m src.hd.analysis
	$(PY) -m src.hd.classes
	$(PY) -m src.cell.rules
	for r in requests/hd/*.json; do $(PY) -m src.cell.build $$r --hd $$(basename $$r .json) || exit 1; done

demo:             ## what the interview runs: make demo IN=<request or design>
	@test -n "$(IN)" || (echo "usage: make demo IN=<request or design>" && exit 1)
	$(PY) -m src.cell.build $(IN)

demo2:            ## option 2 on one design: make demo2 IN=<design.v> TOP=<top module> [SV=1 for SystemVerilog]
	@test -n "$(IN)" -a -n "$(TOP)" || (echo "usage: make demo2 IN=<design.v> TOP=<top module> [SV=1]" && exit 1)
	$(PY) -m src.hd.demo $(IN) $(TOP) $(if $(SV),--sv)

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

clean:            ## removes build/ only; cells/ and results/ are committed outputs
	rm -rf build

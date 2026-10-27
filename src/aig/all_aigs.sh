#!/bin/bash
set -euo pipefail

DESIGNS=("cpu8" "dsp8" "arlet6502" "uart_apb" "risc8" "fir10")
TOPS=("cpu8" "dsp8" "cpu" "uart_apb_master" "cpu" "fir10")

for i in "${!DESIGNS[@]}"; do
    DESIGN="${DESIGNS[$i]}"
    TOP="${TOPS[$i]}"
    V_ABS=$(realpath "designs/${DESIGN}.v")

    echo "Processing design: ${DESIGN}"

    yosys -q << EOF
        read_verilog ${V_ABS}
        synth -flatten -top ${TOP}
        async2sync
        dffunmap
        aigmap
        write_aiger out/aigs/aig/${DESIGN}_raw.aig
        write_aiger -ascii out/aigs/aag/${DESIGN}_raw.aag
EOF
    yosys -q << EOF
        read_verilog ${V_ABS}
        synth -flatten -top ${TOP}
        async2sync
        dffunmap
        abc -script "+strash;dch"
        lut2mux
        aigmap
        write_aiger out/aigs/aig/${DESIGN}_abc.aig
        write_aiger -ascii out/aigs/aag/${DESIGN}_abc.aag
EOF

done

echo "All designs processed successfully."
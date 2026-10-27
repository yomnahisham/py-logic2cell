#!/bin/bash
set -euo pipefail

# 1. Update these two paths to point to where your global Liberty files are stored:
LIB_USABLE="given/hd_usable.lib"  # Usable HD library (307 cells)
LIB_REDUCED="given/hd_reduced.lib"                   # Reduced HD library (189 cells)

# 2. Required designs and their matching top modules from Table 2
DESIGNS=("cpu8" "dsp8" "arlet6502" "uart_apb" "risc8" "fir10")
TOPS=("cpu8" "dsp8" "cpu" "uart_apb_master" "cpu" "fir10")

printf "%-12s | %-8s | %-12s | %-12s\n" "Design" "Script" "Library" "Area (um2)"
echo "---------------------------------------------------------"

for i in "${!DESIGNS[@]}"; do
    DESIGN="${DESIGNS[$i]}"
    TOP="${TOPS[$i]}"
    VERILOG="given/designs/${DESIGN}.v"

    for SCRIPT in "A" "B"; do
        for LIB_TYPE in "usable" "reduced"; do
            if [ "$LIB_TYPE" = "usable" ]; then
                LIB="$LIB_USABLE"
            else
                LIB="$LIB_REDUCED"
            fi

            # Execute map.sh
            OUTPUT=$(bash ./src/table1/map.sh "$VERILOG" "$TOP" "$LIB" "$SCRIPT" 2>/dev/null)
            
            # Extract chip area line
            AREA=$(echo "$OUTPUT" | grep -i "Chip area" | awk '{print $NF}')

            printf "%-12s | %-8s | %-12s | %-12s\n" "$DESIGN" "$SCRIPT" "$LIB_TYPE" "$AREA"
        done
    done
done
#!/bin/bash
set -euo pipefail

if [ $# -lt 4 ]; then
    echo "usage: map.sh <design.v> <top> <liberty> <A|B> [-sv]"
    exit 2
fi

V="$1"
TOP="$2"
LIB="$3"
S="$4"
SV="${5:-}"

# Resolve absolute paths so ABC can locate files regardless of working directory[cite: 1]
LIB_ABS=$(realpath "$LIB")
V_ABS=$(realpath "$V")

case "$S" in
    A) SCRIPT="+strash; dch, -f; amap; topo" ;;
    B) SCRIPT="+strash; &get, -n; &dch, -f; &nf, -R, 1000; &put" ;;
    *) echo "error: script must be A or B"; exit 2 ;;
esac

# Create a temporary Yosys command file
YS_FILE=$(mktemp /tmp/yosys_map_XXXXXX.ys)
trap 'rm -f "$YS_FILE"' EXIT

cat << EOF > "$YS_FILE"
read_verilog $SV $V_ABS
synth -flatten -top $TOP
dfflibmap -liberty $LIB_ABS
abc -liberty $LIB_ABS -script "$SCRIPT"
opt_clean -purge
tee -o /dev/stdout stat -liberty $LIB_ABS
EOF

yosys -q "$YS_FILE" | grep -E "Number of cells|Chip area" | tail -2
#!/usr/bin/env bash
# Combinational proofs for the gray-code pointer scheme.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p reports
yosys -q -p "read_verilog -formal -sv formal/gray_props.sv; prep -top gray_props; write_smt2 -wires reports/gray_props.smt2"
yosys-smtbmc -s z3 -t 1 reports/gray_props.smt2 | tee reports/formal_result.txt

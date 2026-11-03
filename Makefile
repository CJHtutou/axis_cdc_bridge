# axis_cdc_bridge -- v0.1 skeleton
# usage: make sim | make perf | make regression | make mutations | make synth | make lint
SHELL := /bin/bash

PYTHON ?= python3
export PATH       := /opt/eda/bin:$(PATH)
export PYTHONPATH := $(CURDIR)/tb:$(CURDIR):$(PYTHONPATH)

SIM           ?= verilator
TOPLEVEL_LANG ?= verilog
TOPLEVEL       = axis_cdc_bridge_top
MODULE        ?= test_smoke
TESTCASE      ?= test_smoke

RTL_DIR := rtl

VERILOG_SOURCES := $(RTL_DIR)/cdc_sync_2ff.sv \
                   $(RTL_DIR)/cdc_gray_counter.sv \
                   $(RTL_DIR)/async_fifo_core.sv \
                   $(RTL_DIR)/axis_skid_buffer.sv \
                   $(RTL_DIR)/apb3_csr_regs.sv \
                   $(RTL_DIR)/axis_cdc_bridge_top.sv

COMPILE_ARGS += --timing -Wno-fatal -Wno-lint
DEFINES      ?=
COMPILE_ARGS += $(DEFINES)

# waveform on by default; regression/mutations override WAVES=0
WAVES ?= 1

# Verilator: FST waveform -- build with --trace-fst, enable at runtime with --trace
ifeq ($(WAVES),1)
COMPILE_ARGS += --trace-fst --trace-structs
SIM_ARGS     += --trace
endif

include $(shell cocotb-config --makefiles)/Makefile.sim

# cocotb 内部有一个名为 `regression` 的目标，`sim` 依赖它。
# 只在用户显式请求 make regression 时才定义同名目标，避免遮蔽它。
ifneq ($(filter regression,$(MAKECMDGOALS)),)
regression:
	$(PYTHON) scripts/run_regression.py
endif

apb:
	$(MAKE) MODULE=test_apb TESTCASE= WAVES=0 SIM_BUILD=sim_build_apb sim

packet:
	$(MAKE) MODULE=test_packet TESTCASE= WAVES=0 SIM_BUILD=sim_build_pkt sim

coverage:
	$(PYTHON) scripts/run_coverage.py

mutations:
	$(PYTHON) scripts/run_mutations.py

perf:
	$(MAKE) TESTCASE=test_perf WAVES=0 sim

synth:
	mkdir -p reports
	yosys -p "read_verilog -sv $(VERILOG_SOURCES); hierarchy -check -top axis_cdc_bridge_top; synth -top axis_cdc_bridge_top; stat" > reports/yosys_stat.txt 2>&1 || (tail -20 reports/yosys_stat.txt; exit 1); cat reports/yosys_stat.txt

lint:
	verilator --lint-only -Wall --top-module axis_cdc_bridge_top $(RTL_DIR)/*.sv

clean_all: clean
	rm -rf sim_build __pycache__ tb/__pycache__ results.xml

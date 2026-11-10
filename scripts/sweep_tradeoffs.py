#!/usr/bin/env python3
"""Synthesise the bridge for several FIFO depths / data widths and plot the
area trade-off curve (the report's "throughput-per-logic-cell" analysis,
reduced to what an open-source flow can honestly measure: cell count)."""
import csv
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports"
OUT.mkdir(exist_ok=True)

SOURCES = ["rtl/cdc_sync_2ff.sv", "rtl/cdc_gray_counter.sv", "rtl/async_fifo_core.sv",
           "rtl/axis_skid_buffer.sv", "rtl/apb3_csr_regs.sv", "rtl/axis_cdc_bridge_top.sv"]
DEPTHS = [8, 16, 32, 64]
WIDTHS = [32, 64]


def synth(depth, width):
    """Copy the RTL, patch the parameter defaults, synthesise exactly like
    `make synth` does (no `chparam` tricks), and return (cells, flops)."""
    tmp = Path(tempfile.mkdtemp(prefix=f"axis_sweep_{width}_{depth}_"))
    try:
        for src in SOURCES:
            shutil.copy(ROOT / src, tmp / Path(src).name)
        top = tmp / "axis_cdc_bridge_top.sv"
        text = top.read_text()
        text = re.sub(r"parameter int DATA_W = \d+", f"parameter int DATA_W = {width}", text)
        text = re.sub(r"parameter int DEPTH\s*=\s*\d+", f"parameter int DEPTH  = {depth}", text)
        top.write_text(text)

        script = ("read_verilog -sv " + " ".join(str(tmp / Path(f).name) for f in SOURCES) +
                  "; hierarchy -check -top axis_cdc_bridge_top; "
                  "synth -top axis_cdc_bridge_top; stat")
        proc = subprocess.run(["yosys", "-p", script], cwd=tmp, capture_output=True, text=True)
        if proc.returncode != 0:
            print(proc.stdout[-2000:], proc.stderr[-1000:])
            raise SystemExit(f"yosys failed for DEPTH={depth} DATA_W={width}")

        cells = int(re.findall(r"Number of cells:\s+(\d+)", proc.stdout)[-1])
        dffs = sum(int(n) for n in re.findall(r"\$_DFF\w*\s+(\d+)", proc.stdout))
        return cells, dffs
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    rows = []
    for width in WIDTHS:
        for depth in DEPTHS:
            cells, dffs = synth(depth, width)
            rows.append(dict(data_w=width, depth=depth, cells=cells, flops=dffs,
                             fifo_bits=depth * (width + width // 8 + 1)))
            print(f"DATA_W={width:>2}  DEPTH={depth:>2}  cells={cells:>5}  flops={dffs:>4}")

    with open(OUT / "tradeoff_sweep.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["data_w", "depth", "cells", "flops", "fifo_bits"])
        w.writeheader()
        w.writerows(rows)

    fig, ax = plt.subplots(figsize=(7, 4.2))
    for width in WIDTHS:
        pts = [(r["depth"], r["cells"]) for r in rows if r["data_w"] == width]
        ax.plot([p[0] for p in pts], [p[1] for p in pts], marker="o", label=f"DATA_W={width}")
    ax.set_xscale("log", base=2)
    ax.set_xticks(DEPTHS)
    ax.set_xticklabels([str(d) for d in DEPTHS])
    ax.set_xlabel("FIFO depth")
    ax.set_ylabel("synthesised cells (Yosys generic CMOS)")
    ax.set_title("axis_cdc_bridge: area vs FIFO depth")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(OUT / "tradeoff_curve.png", dpi=150)

    print(f"wrote {OUT / 'tradeoff_sweep.csv'} and {OUT / 'tradeoff_curve.png'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

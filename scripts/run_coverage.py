#!/usr/bin/env python3
"""Run the coverage sweep over 3 clock ratios and merge 12+12+12 = 36 bins."""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports"
OUT.mkdir(exist_ok=True)

CASES = [("fast", 10, 30), ("slow", 30, 10), ("near", 10, 9)]
MODES = ["cut_through", "packet"]
LENGTHS = ["short", "medium", "long"]
KEEPS = ["full", "partial"]

EXPECTED = {f"{t}|{m}|{l}|{k}" for t, _, _ in CASES
            for m in MODES for l in LENGTHS for k in KEEPS}


def run(tag, mclk, sclk):
    env = os.environ.copy()
    env.update(COVER_TAG=tag, MCLK_NS=str(mclk), SCLK_NS=str(sclk),
               WAVES="0", TESTCASE="", SIM_BUILD=f"sim_build_cover_{tag}")
    proc = subprocess.run(["make", "MODULE=test_cover", "sim"], cwd=ROOT, env=env,
                          capture_output=True, text=True)
    if proc.returncode != 0:
        print(proc.stdout[-3000:])
        return None
    hits = json.loads((OUT / f"coverage_{tag}.json").read_text())["hits"]
    return set(hits)


def main():
    merged = set()
    for tag, m, s in CASES:
        got = run(tag, m, s)
        if got is None:
            print(f"FAIL  {tag}")
            return 1
        merged |= got
        print(f"PASS  {tag:<5} {m}:{s} ns -> {len(got)}/12 bins")

    missing = sorted(EXPECTED - merged)
    pct = 100.0 * len(merged & EXPECTED) / len(EXPECTED)

    lines = ["# Functional coverage report", "",
             f"bins hit: {len(merged & EXPECTED)}/{len(EXPECTED)}  ({pct:.1f}%)", "",
             "| clock ratio | mode | length | tkeep | hit |", "|---|---|---|---|---|"]
    for t, _, _ in CASES:
        for m in MODES:
            for l in LENGTHS:
                for k in KEEPS:
                    key = f"{t}|{m}|{l}|{k}"
                    lines.append(f"| {t} | {m} | {l} | {k} | {'x' if key in merged else '-'} |")
    if missing:
        lines += ["", "missing: " + ", ".join(missing)]
    (OUT / "coverage_report.md").write_text("\n".join(lines) + "\n")

    print(f"\nfunctional coverage: {len(merged & EXPECTED)}/{len(EXPECTED)} ({pct:.1f}%)")
    return 0 if not missing else 1


if __name__ == "__main__":
    sys.exit(main())

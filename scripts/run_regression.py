#!/usr/bin/env python3
"""Run the cocotb regression across three clock-ratio scenarios.

Writes reports/regression_summary.json and exits non-zero on any failure.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports"
OUT.mkdir(exist_ok=True)

CASES = [
    dict(name="fast_write_slow_read", mclk=10, sclk=30, n_pkt=100),
    dict(name="slow_write_fast_read", mclk=30, sclk=10, n_pkt=100),
    dict(name="near_equal", mclk=10, sclk=9, n_pkt=100),
]


def run_case(case):
    env = os.environ.copy()
    env.update(
        RANDOM_SEED=os.getenv("RANDOM_SEED", "20261102"),
        MCLK_NS=str(case["mclk"]),
        SCLK_NS=str(case["sclk"]),
        N_PKT=str(case["n_pkt"]),
        WAVES="0",
        TESTCASE="test_smoke",
    )
    t0 = time.time()
    proc = subprocess.run(
        ["make", "sim"], cwd=ROOT, env=env,
        capture_output=True, text=True,
    )
    dt = time.time() - t0
    tail = [ln.strip() for ln in (proc.stdout or "").strip().splitlines()[-2:]]
    return dict(case=case["name"], mclk=case["mclk"], sclk=case["sclk"],
                n_pkt=case["n_pkt"], passed=proc.returncode == 0,
                secs=round(dt, 2), tail=tail)


def main():
    results = [run_case(c) for c in CASES]
    (OUT / "regression_summary.json").write_text(
        json.dumps({"seed": os.getenv("RANDOM_SEED", "20261102"),
                    "cases": results}, indent=2, ensure_ascii=False)
    )
    for r in results:
        print(f"{'PASS' if r['passed'] else 'FAIL'}  {r['case']:<22} "
              f"{r['mclk']}:{r['sclk']} ns  {r['secs']:>6}s  pkts={r['n_pkt']}")
    ok = all(r["passed"] for r in results)
    print(f"\n{sum(r['passed'] for r in results)}/{len(results)} cases passed")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

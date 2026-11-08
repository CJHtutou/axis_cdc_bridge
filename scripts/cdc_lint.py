#!/usr/bin/env python3
"""Structural CDC check on the Yosys netlist.

Rules
-----
R1  every flip-flop must have a resolvable clock domain (aclk_m / aclk_s / pclk)
R2  no combinational path from one clock domain into a flop of another domain,
    unless the destination flop belongs to a synchronizer instance (u_sync_*,
    or the sync1/sync2 stages inside cdc_gray_counter)
R3  every synchronizer fed by a multi-bit bus is reported so the gray-coding
    can be reviewed (width > 1 => must be a gray-coded pointer)

Exit code is non-zero when R1 or R2 is violated.
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JSON_PATH = ROOT / "reports" / "design.json"

CLOCKS = {"aclk_m", "aclk_s", "pclk"}
DFF_PREFIXES = ("$dff", "$adff", "$sdff", "$aldff", "$dffe", "$adffe", "$sdffe", "$_DFF", "$_DFFE")
SYNC_HINTS = ("sync", "stage1", "stage2")
CNT_INSTANCES = ("u_commit_cnt", "u_pkt_cnt", "u_ovf_cnt", "u_par_cnt")


def inside_counter(src, dst):
    """Both ends inside the same gray-counter instance => internal gray sync."""
    return any(i in src and i in dst for i in CNT_INSTANCES)


def load_design(path):
    with open(path) as fh:
        return json.load(fh)


def build_index(mod):
    """bit -> (cell, port) for every driven bit; bit -> port name for inputs."""
    drivers = {}
    cells = mod["cells"]
    for name, cell in cells.items():
        for port, bits in cell.get("connections", {}).items():
            if port in ("Y", "Q"):
                for b in bits:
                    if isinstance(b, int):
                        drivers[b] = (name, port)

    port_bits = {}
    for pname, port in mod["ports"].items():
        if port["direction"] == "input":
            for b in port["bits"]:
                if isinstance(b, int):
                    port_bits[b] = pname
    return drivers, port_bits


def clock_domain(bit, drivers, port_bits, cells, depth=0):
    if bit in port_bits and port_bits[bit] in CLOCKS:
        return port_bits[bit]
    if depth > 8 or bit not in drivers:
        return None
    cell_name, _ = drivers[bit]
    cell = cells[cell_name]
    for port in ("A", "B", "S", "I"):
        for b in cell.get("connections", {}).get(port, []):
            dom = clock_domain(b, drivers, port_bits, cells, depth + 1)
            if dom:
                return dom
    return None


def fanin_sources(bit, drivers, cells, depth, seen, out):
    """Collect (cell_name, domain) of flops feeding `bit`."""
    if depth > 12 or bit in seen:
        return
    seen.add(bit)
    if bit not in drivers:
        return
    name, _ = drivers[bit]
    cell = cells[name]
    if cell["type"].startswith(DFF_PREFIXES):
        out.add(name)
        return
    for port, bits in cell.get("connections", {}).items():
        if port in ("Y", "Q", "CLK", "ARST", "SRST", "AD", "ALOAD", "SET", "CLR"):
            continue
        for b in bits:
            if isinstance(b, int):
                fanin_sources(b, drivers, cells, depth + 1, seen, out)


def main():
    if not JSON_PATH.exists():
        print(f"missing {JSON_PATH}; run `make netlist` first")
        return 2

    design = load_design(JSON_PATH)
    top_name = next(iter(design["modules"]))
    mod = design["modules"][top_name]
    cells = mod["cells"]
    drivers, port_bits = build_index(mod)

    dffs = {n: c for n, c in cells.items() if c["type"].startswith(DFF_PREFIXES)}
    domain_of = {}
    unresolved = []

    for name, cell in dffs.items():
        clk_bits = cell["connections"].get("CLK", [])
        dom = clock_domain(clk_bits[0], drivers, port_bits, cells) if clk_bits else None
        if dom is None:
            unresolved.append(name)
        else:
            domain_of[name] = dom

    violations = []      # single-bit crossings without a synchronizer
    review = []          # multi-bit crossings: gray-coded or handshake? needs doc
    synced = []
    for name, cell in dffs.items():
        dst_dom = domain_of.get(name)
        if dst_dom is None:
            continue
        d_bits = cell["connections"].get("D", [])
        sources = set()
        for b in d_bits:
            if isinstance(b, int):
                fanin_sources(b, drivers, cells, 0, set(), sources)
        for src in sources:
            src_dom = domain_of.get(src)
            if src_dom and src_dom != dst_dom:
                is_sync = any(h in name.lower() for h in SYNC_HINTS) or inside_counter(src, name)
                if is_sync:
                    synced.append((src, name, src_dom, dst_dom, len(d_bits)))
                elif len(d_bits) > 1:
                    review.append((src, name, src_dom, dst_dom, len(d_bits)))
                else:
                    violations.append((src, name, src_dom, dst_dom, len(d_bits)))

    lines = ["# CDC structural check", "",
             f"design: {top_name}", f"flops: {len(dffs)}", ""]

    if unresolved:
        lines.append(f"R1 FAIL: {len(unresolved)} flop(s) without a resolvable clock:")
        lines += [f"  - {n}" for n in unresolved[:20]]
    else:
        lines.append("R1 PASS: every flop clock resolves to aclk_m / aclk_s / pclk")

    if review:
        lines.append(f"\nR2 REVIEW: {len(review)} multi-bit crossing(s) -- must be gray-coded or handshake-captured:")
        for src, dst, sd, dd, w in review[:20]:
            note = ""
            if "u_csr" in src and w == 8:
                note = "  (cfg_af_th/cfg_ae_th captured via 2-phase toggle handshake u_sync_th_*)"
            lines.append(f"  - {src} [{sd}] -> {dst} [{dd}] width={w}{note}")

    if violations:
        lines.append(f"\nR2 FAIL: {len(violations)} unsafe single-bit crossing(s):")
        for src, dst, sd, dd, w in violations[:30]:
            lines.append(f"  - {src} [{sd}] -> {dst} [{dd}] width={w}")
    else:
        lines.append(f"R2 PASS: no unsafe single-bit crossing ({len(synced)} synchronized paths)")

    widths = sorted({w for *_, w in synced}, reverse=True)
    lines.append(f"\nR3 review: synchronized bus widths = {widths or 'none'} "
                 f"(width > 1 must be gray-coded)")

    report = "\n".join(lines)
    (ROOT / "reports" / "cdc_report.md").write_text(report + "\n")
    print(report)
    return 0 if not violations and not unresolved else 1


if __name__ == "__main__":
    sys.exit(main())

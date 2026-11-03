"""Functional coverage sweep.

36 bins = 3 clock ratios x 2 transfer modes x 3 packet-length classes x 2 tkeep classes.
Each simulation run covers one clock ratio (12 bins) and writes
reports/coverage_<TAG>.json; scripts/run_coverage.py merges the runs.
"""
import json
import os

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer

TAG   = os.getenv("COVER_TAG", "fast")
MCLK  = float(os.getenv("MCLK_NS", "10"))
SCLK  = float(os.getenv("SCLK_NS", "30"))
PCLK  = 20

ADDR_CTRL = 0x00

MODES = [("cut_through", 0x1), ("packet", 0x3)]
LENGTHS = [("short", 1), ("medium", 3), ("long", 6)]
KEEPS = [("full", 0xF), ("partial", 0x5)]

HITS = set()


async def apb_write(dut, addr, data):
    await RisingEdge(dut.pclk)
    await Timer(1, unit="ns")
    dut.psel.value = 1; dut.penable.value = 0; dut.pwrite.value = 1
    dut.paddr.value = addr; dut.pwdata.value = data; dut.pstrb.value = 0xF
    await RisingEdge(dut.pclk)
    await Timer(1, unit="ns")
    dut.penable.value = 1
    await RisingEdge(dut.pclk)
    await Timer(1, unit="ns")
    dut.psel.value = 0; dut.penable.value = 0


def par(data, keep):
    return (bin(data).count("1") + bin(keep).count("1")) & 1


async def send_beat(dut, data, last, keep):
    await RisingEdge(dut.aclk_m)
    await Timer(1, unit="ns")
    dut.s_axis_tdata.value = data
    dut.s_axis_tkeep.value = keep
    dut.s_axis_tlast.value = last
    dut.s_axis_tuser.value = par(data, keep)
    dut.s_axis_tvalid.value = 1
    while True:
        await Timer(MCLK / 2.0 - 1.0, unit="ns")
        if int(dut.s_axis_tready.value) == 1:
            await RisingEdge(dut.aclk_m)
            break
        await RisingEdge(dut.aclk_m)
        await Timer(1, unit="ns")
    await Timer(1, unit="ns")
    dut.s_axis_tvalid.value = 0


@cocotb.test()
async def test_coverage(dut):
    dut.psel.value = 0; dut.penable.value = 0; dut.pwrite.value = 0
    dut.paddr.value = 0; dut.pwdata.value = 0; dut.pstrb.value = 0
    dut.presetn.value = 0; dut.aresetn_m.value = 0; dut.aresetn_s.value = 0
    dut.s_axis_tvalid.value = 0; dut.s_axis_tdata.value = 0
    dut.s_axis_tkeep.value = 0; dut.s_axis_tlast.value = 0; dut.s_axis_tuser.value = 0
    dut.m_axis_tready.value = 1

    cocotb.start_soon(Clock(dut.aclk_m, MCLK, unit="ns").start())
    cocotb.start_soon(Clock(dut.aclk_s, SCLK, unit="ns").start())
    cocotb.start_soon(Clock(dut.pclk, PCLK, unit="ns").start())

    await Timer(150, unit="ns")
    dut.presetn.value = 1; dut.aresetn_m.value = 1; dut.aresetn_s.value = 1
    await Timer(100, unit="ns")

    for mode_name, ctrl in MODES:
        await apb_write(dut, ADDR_CTRL, ctrl)
        await Timer(200, unit="ns")
        for len_name, n_beats in LENGTHS:
            for keep_name, keep in KEEPS:
                for i in range(n_beats):
                    await send_beat(dut, 0xC0DE_0000 + (i << 8) + n_beats,
                                    1 if i == n_beats - 1 else 0, keep)
                # drain: at least n_beats slave cycles plus sync margin
                await Timer(int((n_beats + 6) * SCLK), unit="ns")
                HITS.add(f"{TAG}|{mode_name}|{len_name}|{keep_name}")

    os.makedirs("reports", exist_ok=True)
    with open(f"reports/coverage_{TAG}.json", "w") as fh:
        json.dump({"tag": TAG, "mclk": MCLK, "sclk": SCLK, "hits": sorted(HITS)}, fh, indent=2)

    dut._log.info(f"coverage run '{TAG}' -> {len(HITS)}/12 bins")

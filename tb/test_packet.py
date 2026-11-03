"""Packet (store-and-forward) mode and parity-error tests."""
import os

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer

PCLK_NS = 20
ADDR_CTRL    = 0x00
ADDR_ERR_CNT = 0x10
ADDR_PKT_CNT = 0x0C


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


async def apb_read(dut, addr):
    await RisingEdge(dut.pclk)
    await Timer(1, unit="ns")
    dut.psel.value = 1; dut.penable.value = 0; dut.pwrite.value = 0
    dut.paddr.value = addr; dut.pwdata.value = 0; dut.pstrb.value = 0
    await RisingEdge(dut.pclk)
    await Timer(1, unit="ns")
    dut.penable.value = 1
    await RisingEdge(dut.pclk)
    await Timer(1, unit="ns")
    val = int(dut.prdata.value)
    dut.psel.value = 0; dut.penable.value = 0
    return val


async def init(dut):
    dut.psel.value = 0; dut.penable.value = 0; dut.pwrite.value = 0
    dut.paddr.value = 0; dut.pwdata.value = 0; dut.pstrb.value = 0
    dut.presetn.value = 0; dut.aresetn_m.value = 0; dut.aresetn_s.value = 0
    dut.s_axis_tvalid.value = 0; dut.s_axis_tdata.value = 0
    dut.s_axis_tkeep.value = 0; dut.s_axis_tlast.value = 0; dut.s_axis_tuser.value = 0
    dut.m_axis_tready.value = 0

    cocotb.start_soon(Clock(dut.aclk_m, 10, unit="ns").start())
    cocotb.start_soon(Clock(dut.aclk_s, 20, unit="ns").start())
    cocotb.start_soon(Clock(dut.pclk, PCLK_NS, unit="ns").start())

    await Timer(120, unit="ns")
    dut.presetn.value = 1; dut.aresetn_m.value = 1; dut.aresetn_s.value = 1
    await Timer(80, unit="ns")


def parity(data, keep):
    return (bin(data).count("1") + bin(keep).count("1")) & 1


async def send_beat(dut, data, last, good_parity=True, keep=0xF):
    """Drive exactly one AXI-Stream beat and wait until it is accepted."""
    await RisingEdge(dut.aclk_m)
    await Timer(1, unit="ns")
    dut.s_axis_tdata.value = data
    dut.s_axis_tkeep.value = keep
    dut.s_axis_tlast.value = last
    p = parity(data, keep)
    dut.s_axis_tuser.value = p if good_parity else (p ^ 1)
    dut.s_axis_tvalid.value = 1

    while True:
        await Timer(4, unit="ns")              # middle of the 10 ns cycle
        if int(dut.s_axis_tready.value) == 1:
            await RisingEdge(dut.aclk_m)       # beat is consumed here
            break
        await RisingEdge(dut.aclk_m)
        await Timer(1, unit="ns")

    await Timer(1, unit="ns")
    dut.s_axis_tvalid.value = 0


@cocotb.test()
async def test_packet_mode(dut):
    """In packet mode nothing may come out until TLAST has been written."""
    await init(dut)
    dut.m_axis_tready.value = 1

    # enable bridge + packet mode (CTRL[1])
    await apb_write(dut, ADDR_CTRL, 0x0000_0003)
    await Timer(100, unit="ns")

    beats = [(0x1111_1111, 0), (0x2222_2222, 0), (0x3333_3333, 0), (0x4444_4444, 1)]
    seen = []

    async def watch():
        while True:
            await RisingEdge(dut.aclk_s)
            await Timer(1, unit="ns")
            if int(dut.m_axis_tvalid.value) and int(dut.m_axis_tready.value):
                seen.append(int(dut.m_axis_tdata.value))

    watcher = cocotb.start_soon(watch())

    # drive the first three beats with long gaps
    for data, last in beats[:-1]:
        await send_beat(dut, data, last)
        await Timer(300, unit="ns")
        assert not seen, f"packet mode leaked a beat before TLAST: {seen}"

    # final beat completes the packet -> now it must come out
    await send_beat(dut, beats[-1][0], 1)
    dut.s_axis_tvalid.value = 0
    await Timer(400, unit="ns")

    assert seen == [b[0] for b in beats], f"packet mode output mismatch: {seen}"
    dut._log.info(f"PACKET MODE PASS -- {len(seen)} beats emitted only after TLAST")
    watcher.cancel()


@cocotb.test()
async def test_cut_through(dut):
    """In cut-through mode beats must flow before TLAST arrives."""
    await init(dut)
    dut.m_axis_tready.value = 1
    await apb_write(dut, ADDR_CTRL, 0x0000_0001)   # enable, cut-through
    await Timer(100, unit="ns")

    seen = []

    async def watch():
        while True:
            await RisingEdge(dut.aclk_s)
            await Timer(1, unit="ns")
            if int(dut.m_axis_tvalid.value) and int(dut.m_axis_tready.value):
                seen.append(int(dut.m_axis_tdata.value))

    watcher = cocotb.start_soon(watch())

    await send_beat(dut, 0xA5A5_A5A5, 0)
    await Timer(300, unit="ns")
    assert seen and seen[0] == 0xA5A5_A5A5, f"cut-through should emit early, got {seen}"

    dut.s_axis_tvalid.value = 0
    dut._log.info(f"CUT-THROUGH PASS -- emitted {len(seen)} beat(s) before TLAST")
    watcher.cancel()


@cocotb.test()
async def test_parity_error_counter(dut):
    await init(dut)
    dut.m_axis_tready.value = 1
    # enable bridge + parity checking (CTRL[2])
    await apb_write(dut, ADDR_CTRL, 0x0000_0005)
    await Timer(100, unit="ns")

    # 6 good beats -> no parity errors
    for i in range(6):
        await send_beat(dut, 0x1000 + i, 0)
    await Timer(200, unit="ns")
    err0 = await apb_read(dut, ADDR_ERR_CNT)
    assert (err0 & 0xFFFF) == 0, f"unexpected parity errors: {err0:#x}"

    # 5 bad-parity beats
    for i in range(5):
        await send_beat(dut, 0x2000 + i, 0, good_parity=False)
    await Timer(300, unit="ns")
    err1 = await apb_read(dut, ADDR_ERR_CNT)
    par = err1 & 0xFFFF
    dut._log.info(f"ERR_CNT={err1:#010x} parity_errors={par}")
    assert par == 5, f"expected 5 parity errors, got {par}"

    # W1C clears them
    await apb_write(dut, ADDR_ERR_CNT, 0x0000_FFFF)
    await Timer(200, unit="ns")
    err2 = await apb_read(dut, ADDR_ERR_CNT)
    assert (err2 & 0xFFFF) == 0, f"W1C failed: {err2:#x}"
    dut._log.info("PARITY COUNTER PASS -- 5 errors detected and cleared")

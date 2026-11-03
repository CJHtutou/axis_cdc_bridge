"""APB3 control-plane tests: register access, RO protection, W1C, counters."""
import os
import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer

PCLK_NS = 20
SEED = int(os.getenv("RANDOM_SEED", "20261102"))

ADDR_CTRL     = 0x00
ADDR_THRESH   = 0x04
ADDR_STATUS   = 0x08
ADDR_PKT_CNT  = 0x0C
ADDR_ERR_CNT  = 0x10
ADDR_IRQ_MASK = 0x14


async def apb(dut, addr, data=None, strb=0xF):
    """One APB3 transfer; returns (rdata, pslverr).

    Timing (period T): edge A -> SETUP, edge A+1 -> ACCESS (pready high),
    pslverr/prdata sampled 1 ns into the ACCESS cycle.
    """
    period = PCLK_NS

    await RisingEdge(dut.pclk)
    await Timer(1, unit="ns")
    dut.psel.value = 1
    dut.penable.value = 0
    dut.pwrite.value = 0 if data is None else 1
    dut.paddr.value = addr
    dut.pwdata.value = 0 if data is None else data
    dut.pstrb.value = 0 if data is None else strb

    await RisingEdge(dut.pclk)          # enter SETUP
    await Timer(1, unit="ns")
    dut.penable.value = 1

    await RisingEdge(dut.pclk)          # enter ACCESS
    await Timer(1, unit="ns")
    err = int(dut.pslverr.value)
    rdata = int(dut.prdata.value)

    await Timer(period - 1.0, unit="ns")
    dut.psel.value = 0
    dut.penable.value = 0
    return rdata, err


async def init(dut):
    dut.psel.value = 0
    dut.penable.value = 0
    dut.pwrite.value = 0
    dut.paddr.value = 0
    dut.pwdata.value = 0
    dut.pstrb.value = 0
    dut.presetn.value = 0
    dut.aresetn_m.value = 0
    dut.aresetn_s.value = 0
    dut.s_axis_tvalid.value = 0
    dut.s_axis_tdata.value = 0
    dut.s_axis_tkeep.value = 0
    dut.s_axis_tlast.value = 0
    dut.s_axis_tuser.value = 0
    dut.m_axis_tready.value = 0

    cocotb.start_soon(Clock(dut.aclk_m, 10, unit="ns").start())
    cocotb.start_soon(Clock(dut.aclk_s, 30, unit="ns").start())
    cocotb.start_soon(Clock(dut.pclk, PCLK_NS, unit="ns").start())

    await Timer(100, unit="ns")
    dut.presetn.value = 1
    dut.aresetn_m.value = 1
    dut.aresetn_s.value = 1
    await Timer(60, unit="ns")


@cocotb.test()
async def test_registers(dut):
    await init(dut)

    ctrl, err = await apb(dut, ADDR_CTRL)
    assert err == 0, "CTRL read must not error"
    assert ctrl & 0x1, f"bridge should be enabled out of reset, CTRL={ctrl:#x}"

    # THRESH write / read-back with byte strobes
    _, err = await apb(dut, ADDR_THRESH, 0x0000_0A05)
    assert err == 0
    val, _ = await apb(dut, ADDR_THRESH)
    assert val == 0x0000_0A05, f"THRESH readback {val:#x}"

    # byte-strobe write: only byte 0 changes (pwdata low byte = 0x0C)
    _, err = await apb(dut, ADDR_THRESH, 0x0000_000C, strb=0b0001)
    val, _ = await apb(dut, ADDR_THRESH)
    assert val == 0x0000_0A0C, f"pstrb write failed: {val:#x}"

    # CTRL mode bit
    _, err = await apb(dut, ADDR_CTRL, 0x0000_0003)
    val, _ = await apb(dut, ADDR_CTRL)
    assert val == 0x0000_0003

    # read-only register write must raise pslverr
    _, err = await apb(dut, ADDR_STATUS, 0xDEAD_BEEF)
    assert err == 1, "write to STATUS must assert pslverr"
    _, err = await apb(dut, ADDR_PKT_CNT, 0x1)
    assert err == 1, "write to PKT_CNT must assert pslverr"

    # illegal address must raise pslverr
    _, err = await apb(dut, 0x20)
    assert err == 1, "illegal address must assert pslverr"

    # STATUS flags readable
    st, err = await apb(dut, ADDR_STATUS)
    assert err == 0
    dut._log.info(f"STATUS={st:#010x} (full={st & 1}, empty={(st >> 1) & 1})")

    # IRQ mask default
    mask, _ = await apb(dut, ADDR_IRQ_MASK)
    assert mask == 0xF, f"IRQ_MASK default {mask:#x}"
    dut._log.info("APB register test PASS")


@cocotb.test()
async def test_error_counter_w1c(dut):
    await init(dut)

    # fill the FIFO completely, then keep pushing -> overflow attempts counted
    dut.s_axis_tkeep.value = 0xF
    dut.s_axis_tlast.value = 0
    dut.s_axis_tvalid.value = 1
    for i in range(40):
        await RisingEdge(dut.aclk_m)
        await Timer(1, unit="ns")
        dut.s_axis_tdata.value = 0x1000 + i
    await Timer(200, unit="ns")
    dut.s_axis_tvalid.value = 0

    cnt, _ = await apb(dut, ADDR_ERR_CNT)
    ovf = (cnt >> 16) & 0xFFFF
    dut._log.info(f"ERR_CNT={cnt:#010x} overflow_attempts={ovf}")
    assert ovf > 0, "overflow attempts should have been counted"

    # W1C: clear the overflow half-word
    _, err = await apb(dut, ADDR_ERR_CNT, 0xFFFF_0000)
    assert err == 0
    await Timer(100, unit="ns")
    cnt2, _ = await apb(dut, ADDR_ERR_CNT)
    assert ((cnt2 >> 16) & 0xFFFF) == 0, f"W1C failed, still {cnt2:#x}"
    dut._log.info("APB W1C test PASS")


@cocotb.test()
async def test_packet_counter(dut):
    await init(dut)
    rng = random.Random(SEED)

    # 20 single-beat packets, downstream always ready
    dut.m_axis_tready.value = 1
    dut.s_axis_tkeep.value = 0xF
    dut.s_axis_tlast.value = 1

    for i in range(20):
        dut.s_axis_tdata.value = rng.getrandbits(32)
        dut.s_axis_tvalid.value = 1
        await RisingEdge(dut.aclk_m)
        await Timer(1, unit="ns")
        while not int(dut.s_axis_tready.value):
            await RisingEdge(dut.aclk_m)
            await Timer(1, unit="ns")
    dut.s_axis_tvalid.value = 0
    await Timer(1, unit="us")

    pkt, _ = await apb(dut, ADDR_PKT_CNT)
    dut._log.info(f"PKT_CNT={pkt}")
    assert pkt == 20, f"expected 20 packets, got {pkt}"
    dut._log.info("APB packet counter test PASS")

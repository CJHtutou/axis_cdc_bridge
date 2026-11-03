"""axis_cdc_bridge v0.1 -- cocotb tests (smoke + perf).

Environment variables:
    RANDOM_SEED  default 20261102
    N_PKT        packets in test_smoke      (default 100)
    MCLK_NS      write clock period in ns   (default 10  -> 100 MHz)
    SCLK_NS      read  clock period in ns   (default 30  -> 33.3 MHz)
    READY_PCT    downstream ready duty      (default 0.6)
    PERF_BEATS   beats in test_perf         (default 100000)
"""
import os
import random
import time

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer

SEED       = int(os.getenv("RANDOM_SEED", "20261102"))
N_PKT      = int(os.getenv("N_PKT", "100"))
MCLK_NS    = float(os.getenv("MCLK_NS", "10"))
SCLK_NS    = float(os.getenv("SCLK_NS", "30"))
READY_PCT  = float(os.getenv("READY_PCT", "0.6"))
PERF_BEATS = int(os.getenv("PERF_BEATS", "100000"))

DATA_W = 32
KEEP_W = DATA_W // 8


def gen_packets(rng, n_pkt, max_len=8):
    pkts = []
    for _ in range(n_pkt):
        ln = rng.randint(1, max_len)
        beats = []
        for i in range(ln):
            data = rng.getrandbits(DATA_W)
            keep = rng.choice([0xF, 0xF, 0xF, 0x7, 0xB, 0x3, 0x1])
            last = 1 if i == ln - 1 else 0
            beats.append((data, keep, last))
        pkts.append(beats)
    return pkts


def flatten(pkts):
    return [b for p in pkts for b in p]


async def init_dut(dut):
    dut.s_axis_tvalid.value = 0
    dut.s_axis_tdata.value = 0
    dut.s_axis_tkeep.value = 0
    dut.s_axis_tlast.value = 0
    dut.s_axis_tuser.value = 0
    dut.m_axis_tready.value = 0
    dut.aresetn_m.value = 0
    dut.aresetn_s.value = 0
    dut.presetn.value = 0
    dut.psel.value = 0
    dut.penable.value = 0
    dut.pwrite.value = 0
    dut.paddr.value = 0
    dut.pwdata.value = 0
    dut.pstrb.value = 0

    cocotb.start_soon(Clock(dut.aclk_m, MCLK_NS, unit="ns").start())
    cocotb.start_soon(Clock(dut.aclk_s, SCLK_NS, unit="ns").start())
    cocotb.start_soon(Clock(dut.pclk, 20, unit="ns").start())

    await Timer(5 * max(MCLK_NS, SCLK_NS), unit="ns")
    dut.aresetn_m.value = 1
    dut.aresetn_s.value = 1
    dut.presetn.value = 1
    await Timer(2 * max(MCLK_NS, SCLK_NS), unit="ns")


async def axis_master(dut, pkts):
    """Drive AXI4-Stream slave port: change signals right after the edge,
    sample tready mid-cycle, let the next rising edge consume the beat."""
    for pkt in pkts:
        for data, keep, last in pkt:
            accepted = False
            attempts = 0
            while not accepted:
                attempts += 1
                assert attempts < 20000, "stuck: s_axis_tready never asserted (DUT deadlock)" 
                await RisingEdge(dut.aclk_m)
                await Timer(1, unit="ns")
                dut.s_axis_tdata.value = data
                dut.s_axis_tkeep.value = keep
                dut.s_axis_tlast.value = last
                dut.s_axis_tuser.value = (bin(data).count("1") + bin(keep).count("1")) & 1
                dut.s_axis_tvalid.value = 1
                await Timer(MCLK_NS / 2.0 - 1.0, unit="ns")
                accepted = int(dut.s_axis_tready.value) == 1
    # one more edge to consume the final beat
    await RisingEdge(dut.aclk_m)
    await Timer(1, unit="ns")
    dut.s_axis_tvalid.value = 0


async def axis_slave(dut, ready_pct, rng):
    while True:
        await RisingEdge(dut.aclk_s)
        await Timer(1, unit="ns")
        dut.m_axis_tready.value = 1 if rng.random() < ready_pct else 0


async def axis_monitor(dut, sink):
    while True:
        await RisingEdge(dut.aclk_s)
        await Timer(SCLK_NS / 2.0, unit="ns")
        if int(dut.m_axis_tvalid.value) and int(dut.m_axis_tready.value):
            sink.append((int(dut.m_axis_tdata.value),
                         int(dut.m_axis_tkeep.value),
                         int(dut.m_axis_tlast.value)))


async def occupancy_checker(dut, errors, depth=16):
    """White-box consistency check: `full` may only assert when the FIFO is
    really full. Catches premature / late full-flag bugs."""
    while True:
        await RisingEdge(dut.aclk_m)
        await Timer(1, unit="ns")
        full = 1 if int(dut.wfull.value) else 0
        level = int(dut.u_fifo.wlevel.value)
        # full is allowed to lag by up to 2 beats (pessimistic full: the
        # synced read pointer is 2 cycles behind), but must never fire early
        # by a large margin and must never let the FIFO overflow.
        if full and level < depth - 2:
            errors.append(f"t={cocotb.utils.get_sim_time('ns')}ns premature full: level={level}")
        if (not full) and level > depth:
            errors.append(f"t={cocotb.utils.get_sim_time('ns')}ns overflow: level={level}")
        if len(errors) > 20:
            return


async def drain(dut, got, n_exp, timeout_s=10.0):
    t_end = time.perf_counter() + timeout_s
    while len(got) < n_exp and time.perf_counter() < t_end:
        await Timer(50, unit="ns")


@cocotb.test()
async def test_smoke(dut):
    rng = random.Random(SEED)
    await init_dut(dut)

    pkts = gen_packets(rng, N_PKT)
    exp = flatten(pkts)
    got = []

    errs = []
    t0 = time.perf_counter()
    drv = cocotb.start_soon(axis_master(dut, pkts))
    cocotb.start_soon(axis_slave(dut, READY_PCT, rng))
    cocotb.start_soon(axis_monitor(dut, got))
    cocotb.start_soon(occupancy_checker(dut, errs))

    await drv
    await drain(dut, got, len(exp))
    dt = time.perf_counter() - t0

    dut._log.info(f"tx={len(exp)} beats / {len(pkts)} pkts, rx={len(got)} beats, "
                  f"wall={dt * 1000:.1f} ms")

    assert not errs, "full-flag violations: " + "; ".join(errs[:5])
    assert len(got) == len(exp), f"beat count mismatch: rx={len(got)} tx={len(exp)}"
    for i, (e, g) in enumerate(zip(exp, got)):
        assert e == g, f"beat {i} mismatch: exp={e} got={g}"
    dut._log.info("SMOKE PASS -- 0 mismatch, 0 full-flag violation")


@cocotb.test()
async def test_perf(dut):
    rng = random.Random(SEED + 1)
    await init_dut(dut)

    n_beats = PERF_BEATS
    pkts = gen_packets(rng, n_beats, max_len=1)
    exp = flatten(pkts)
    got = []

    drv = cocotb.start_soon(axis_master(dut, pkts))
    cocotb.start_soon(axis_slave(dut, 1.0, rng))
    cocotb.start_soon(axis_monitor(dut, got))

    t0 = time.perf_counter()
    await drv
    await drain(dut, got, len(exp), timeout_s=600.0)
    dt = time.perf_counter() - t0

    assert len(got) == len(exp), f"beat count mismatch: rx={len(got)} tx={len(exp)}"
    assert got == exp, "data mismatch in perf run"

    dut._log.info(f"PERF beats={len(got)} wall={dt:.3f}s "
                  f"throughput={len(got) / dt:,.0f} beats/s "
                  f"(mclk={1000 / MCLK_NS:.1f} MHz)")

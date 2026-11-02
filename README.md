# axis_cdc_bridge

AXI4-Stream 跨时钟域（CDC）异步桥接 IP + cocotb 验证平台（v0.1 skeleton）。

> 目标岗位：数字 IC 前端（RTL）/ 数字 IC 验证（DV）/ FPGA 逻辑开发。
> 核心考点：格雷码指针同步、2-FF 同步器、AXI4-Stream 握手反压、Skid Buffer、
> 自动化回归与突变测试。

## 现状（v0.1）

| 能力 | 状态 |
|---|---|
| 参数化异步 FIFO（格雷码 + 2-FF，N+1 位指针） | ✅ 已实现并验证 |
| AXI4-Stream 从/主接口 + 2 入口 Skid Buffer | ✅ |
| 双时钟随机反压、跨时钟域数据完整性 | ✅ 3 种频比 100% 通过 |
| 突变测试（受控缺陷注入） | ✅ 2/2 检出 |
| Yosys 综合与面积统计 | ✅ 1502 cells（默认 32bit / 深度 16） |
| APB3 配置寄存器（CTRL/THRESH/STATUS/…） | ⏳ v0.2 |
| Packet 整包转发模式、奇偶校验、覆盖率收集 | ⏳ v0.2 |
| SpyGlass CDC / SDC 约束 | ⏳ v0.3 |

## 目录结构

```
axis_cdc_bridge/
├── rtl/
│   ├── cdc_sync_2ff.sv          # 2-FF 同步器（ASYNC_REG 属性）
│   ├── async_fifo_core.sv       # 格雷码异步 FIFO + 可编程水位
│   ├── axis_skid_buffer.sv      # 2 入口流水线缓冲（无反压气泡）
│   └── axis_cdc_bridge_top.sv   # 顶层：tdata/tkeep/tlast 打包过域
├── tb/
│   └── test_smoke.py            # cocotb：smoke / perf 两个 test
├── scripts/
│   ├── run_regression.py        # 3 种时钟频比回归
│   └── run_mutations.py         # 突变测试矩阵
├── docs/
│   └── micro_arch_spec.md       # 微架构与设计取舍
├── reports/                     # 回归/突变/综合产物
└── .github/workflows/regression_ci.yml
```

## 快速开始

```bash
# 依赖：Ubuntu + Verilator >= 5.036 + Python >= 3.10
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

make sim          # 冒烟仿真，生成 dump.fst 波形
make perf         # 10 万拍吞吐压测
make regression   # 3 种频比 × 100 包
make mutations    # 受控缺陷注入
make synth        # Yosys 综合 → reports/yosys_stat.txt
```

看波形：`gtkwave dump.fst`（或 Windows 原生 GTKWave 打开共享目录里的文件）。

## 设计要点

1. **格雷码 + N+1 位指针**：每次递增只有 1 bit 翻转，跨域采样不会出现非法中间态；
   判满用"高两位同时取反、其余位相同"，判空用"完全相等"。
2. **2-FF 同步器**：`ASYNC_REG = "TRUE"`，后端布局时强制放同一 slice。
3. **悲观但安全**：同步延迟 2 拍 → 可能伪满/伪空，但绝不会溢出或读出未写数据。
4. **Skid Buffer**：读端 2 入口缓冲，切断 `m_ready → s_ready` 组合路径，
   稳态 1.0 beat/cycle。
5. **突变测试**：`BUG_2_EMPTY_CMP` / `BUG_3_FULL_COND` 必须被 testbench 100% 检出，
   用来证明 Scoreboard 与断言不是"漏报空壳"。

## 已知限制（诚实声明）

- `BUG_1_BIN_SYNC`（二进制指针直接跨域）在**零延迟 RTL 仿真中不可观测**：
  Verilator 中所有比特在同一 delta 周期更新，不会产生总线偏斜。
  该缺陷需要 SDF 反标或 SpyGlass CDC 结构检查才能捕获，因此未纳入突变矩阵。
- 当前未做 APB3、覆盖率收集、形式化与 STA；v0.2/v0.3 补齐。
- 综合结果基于 Yosys 通用 CMOS 映射，仅用于相对面积对比，不代表商业工艺流片面积。

## License

MIT

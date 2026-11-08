# 面试追问手卡（基于本仓库的真实实现）

> 每条都能在代码里指到出处，面试时可直接打开仓库对照讲。

## Q1 为什么指针跨时钟域必须用格雷码？为什么判满是"高两位同时取反"？

**答**：多比特二进制计数器在进位时（如 `0111 → 1000`）所有位同时翻转，版图布线延迟不同，
异步采样会出现"部分位采到新值、部分位采到旧值"的**数据撕裂**，组合出非法指针。
格雷码每次递增只有 1 位翻转，即使该位被采在亚稳态，2-FF 决议后也只可能是旧值或新值。

判满为什么看高两位：格雷码是反射码。深度 16 的 5 位指针走完第一圈后回到同一物理地址时，
最高位（第 4 位）翻转，次高位（第 3 位）也镜像翻转，因此必须是"高两位相反、其余位相同"。
只反 MSB 会提前判满——这正是注入缺陷 `BUG_3_FULL_COND`（`rtl/async_fifo_core.sv`），
`make mutations` 会在 5 万周期内抓到它。

## Q2 2-FF 同步有 2 拍延迟，这期间指针又动了，会溢出/下溢吗？

**答**：不会。这是"悲观但安全"：
- 读域用本地实时读指针 vs **滞后 2 拍的旧写指针**判空 → 最多**伪空**（晚 2 拍解除 empty），绝不会读到未写数据；
- 写域用本地实时写指针 vs **滞后 2 拍的旧读指针**判满 → 最多**伪满**（晚 2 拍解除 full），绝不会覆盖未读数据。

代价是吞吐率裕量，不是正确性。代码：`rtl/async_fifo_core.sv` 的两条 `cdc_sync_2ff` 例化。

## Q3 两级触发器能 100% 消除亚稳态吗？MTBF 怎么算？

**答**：不能。它把"亚稳态传递到后级"的概率压到工程可忽略，即把 MTBF 拉长到数百年以上。

```
MTBF = exp(t_r / τ) / (T0 · f_clk · f_data)
```

- `τ`：CMOS 正反馈再生时间常数（由 gm、节点电容决定）
- `t_r`：留给第一级恢复的时间 ≈ 时钟周期 − 第二级 setup − 布线延迟
- `T0`：孔径窗口工艺常数

所以后端要加 `ASYNC_REG = "TRUE"`，强制两个触发器放在同一 slice，最小化 `t_route`、最大化 `t_r`。
本仓库 `rtl/cdc_sync_2ff.sv` 里就带了这个属性。

## Q4 AXI4-Stream 的握手有什么硬性规定？为什么读端要加 Skid Buffer？

**答**：ARM IHI 0051 规定：`TVALID` 一旦拉高，在 `TVALID && TREADY` 采样沿到来前
**不得撤回，也不得修改 TDATA/TKEEP/TLAST**；且发送端不得等对方先拉 TREADY 才拉 TVALID（防死锁）。

读端为什么要 Skid：同步 RAM 从 `rd_en` 到数据有效有 1 拍延迟。若直接接总线，
下游中途反压时那 1 拍在途数据无处可放；若改成"握手完再读下一拍"，吞吐率掉到 0.5 beat/cycle。
2 入口 Skid Buffer（主寄存器 + 备用寄存器）把在途数据截住，稳态仍是 1.0 beat/cycle。
代码：`rtl/axis_skid_buffer.sv`；`BUG_2`/`BUG_4` 就是针对这条协议注入的缺陷。

## Q5 写 100 MHz、读 50 MHz，每 100 个写周期突发 40 拍，FIFO 最小深度？

**答**：分两步。

单次突发：`T_burst = 40 / 100 MHz = 400 ns`，此间读端读走 `400 ns × 50 MHz = 20` 拍，
净积压 `40 − 20 = 20` 拍，加 2-FF 同步裕量 4~6 拍 ≈ 26 → 向上取 2 的幂 = **32**。

背靠背最坏情况（前一个突发尾巴 40 拍 + 后一个突发头 40 拍 = 80 拍）：
净积压 `80 − 40 = 40`，加裕量 ≈ 46 → 向上取 2 的幂 = **64**。

## Q6 你用 pyuvm/cocotb，和 SystemVerilog UVM 有什么区别？怎么证明你的 Scoreboard 没写错？

**答**：pyuvm 按 IEEE 1800.2 实现同样的组件树（Sequencer/Driver/Monitor/Scoreboard）与 TLM 通信，
只是用 Python 动态类型替代 SV 的宏与参数化类型，好处是能在 GitHub Actions 免费跑。

证明 Scoreboard 没错的方法：**突变测试**。仓库里预置了受控缺陷（`BUG_2_EMPTY_CMP`、
`BUG_3_FULL_COND`，另有 `BUG_1_BIN_SYNC` 属结构性缺陷、零延迟仿真不可观测），
`make mutations` 会依次编译正常版与变异版，要求"正常版 PASS、变异版 100% FAIL"。
5/5 检出才说明断言与 Scoreboard 有真实捕获能力。

## Q7 交给后端做 STA，你需要什么 SDC？为什么不能一句 set_false_path？

**答**：不能只写 `set_false_path`。一旦完全伪路径，工具不再约束格雷码各比特之间的布线延迟差；
只要位间偏斜超过 1 个源时钟周期，格雷码"每次只翻 1 位"的数学前提就被破坏。

正确做法（`docs/axis_cdc_bridge.sdc`）：
```tcl
set_clock_groups -asynchronous -group {aclk_m} -group {aclk_s} -group {pclk}
set_max_delay -datapath_only -from [get_cells ...wgray_reg*] -to [get_cells ...stage1_reg*] <T_src>
set_bus_skew  -from [get_cells ...wgray_reg*] -to [get_cells ...stage1_reg*] 1.0
```

## 附：本仓库可现场演示的四条命令

```bash
make sim        # 波形 + 0 mismatch
make mutations  # 2/2 缺陷检出（证明验证平台有效）
make coverage   # 36/36 功能覆盖
make cdc        # 结构 CDC 检查：0 条不安全单比特跨域
make formal     # z3 形式化：格雷码单比特翻转、满判断等价性
```

# axis_cdc_bridge 微架构规格（v0.1）

## 1. 时钟域

| 域 | 时钟 | 复位 | 职责 |
|---|---|---|---|
| 写侧 | `aclk_m` | `aresetn_m`（低有效） | AXI4-Stream 从机入口 |
| 读侧 | `aclk_s` | `aresetn_s`（低有效） | AXI4-Stream 主机出口 |
| 控制 | `pclk` | `presetn` | APB3 CSR（v0.2） |

## 2. 数据通路

```
s_axis_* --(打包 {tlast,tkeep,tdata})--> async_fifo_core --> axis_skid_buffer --> m_axis_*
```

- FIFO 位宽 `PW_DATA = DATA_W + DATA_W/8 + 1`（默认 32+4+1 = 37 bit）
- 深度 `DEPTH = 16`（可参数化 16/32/64，必须 2 的幂）
- 读端为 show-ahead 读：`rdata` 在 `!rempty` 时有效

## 3. 指针与标志

- 指针位宽 `PW = log2(DEPTH) + 1`
- `wgray_next = (wbin_next >> 1) ^ wbin_next`
- 判满：`wgray_next[MSB:MSB-1] == ~rq2_wgray[MSB:MSB-1] && 低位相等`
- 判空：`rgray_next == wq2_rgray`
- 水位：`wlevel = wbin - gray2bin(rq2_wgray)`（悲观，含 2 拍同步延迟）

## 4. 反压

- 写侧：`s_axis_tready = !wfull`
- 读侧：`rd_en = skid_ready && !rempty`
- Skid：2 入口环形缓冲，`s_ready = (cnt != 2)`，`m_data = mem[rd_ptr]`

## 5. 设计取舍

| 取舍 | 选择 | 理由 |
|---|---|---|
| 存储 | 分布式 RAM（异步读） | 深度小、免 1 拍读延迟；深度 >64 时应换 BRAM + 前置预取 |
| 反压 | 2 入口 skid | 切断组合路径，代价 2 拍面积 |
| 判满 | 格雷码高两位 | 反射对称性；只反 MSB 会提前判满（见 BUG_3） |

## 6. v0.2 计划

- APB3 CSR：`CTRL/THRESH/STATUS/PKT_CNT/ERR_CNT/IRQ_MASK`
- Packet 整包转发（在途包计数器）+ 奇偶校验
- 功能覆盖率 36 bins、`make coverage`

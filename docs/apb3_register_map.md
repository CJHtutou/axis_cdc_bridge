# APB3 寄存器映射（v0.2）

基地址对齐：`paddr[7:0]`，4 字节对齐，未列出的地址返回 `pslverr = 1`。

| 偏移 | 名称 | 类型 | 复位值 | 位域 |
|---|---|---|---|---|
| 0x00 | CTRL | R/W | 0x0000_0001 | [0] EN 全局使能<br>[1] MODE 0=Cut-Through（v0.3）<br>[2] PARITY_EN（v0.3）<br>[3] SOFT_RST 自清零脉冲 |
| 0x04 | THRESH | R/W | 0x0000_040C | [7:0] AF_TH<br>[15:8] AE_TH |
| 0x08 | STATUS | RO | — | [0] FULL<br>[1] EMPTY<br>[2] ALMOST_FULL<br>[3] ALMOST_EMPTY<br>[15:8] LEVEL |
| 0x0C | PKT_CNT | RO | 0 | 已完成包计数（TLAST 握手） |
| 0x10 | ERR_CNT | RO/W1C | 0 | [15:0] PARITY_ERR<br>[31:16] OVF_ATTEMPT |
| 0x14 | IRQ_MASK | R/W | 0x0000_000F | [0] PARITY_ERR<br>[1] OVF<br>[2] ALMOST_FULL<br>[3] ALMOST_EMPTY |

## 时序

- `pready` 恒为 1（零等待），ACCESS 周期完成传输。
- 非法地址 / 只读写：`pslverr` 在 ACCESS 周期为高，写操作不生效。
- `pstrb` 按字节选通，`pstrb=0` 的字节保持原值。

## W1C 实现说明

`ERR_CNT` 的两个半字是**单调递增**的跨域计数器。W1C 采用「偏移量」实现：
写 1 到某个半字时记录当前计数值作为 offset，读回 `live - offset`。
好处是不需要在源时钟域做清零握手；代价是计数器回绕（2^32）时会失效，本项目生命周期内不会发生。

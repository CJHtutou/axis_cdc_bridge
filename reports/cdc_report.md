# CDC structural check

design: axis_cdc_bridge_top
flops: 62

R1 PASS: every flop clock resolves to aclk_m / aclk_s / pclk

R2 REVIEW: 2 multi-bit crossing(s) -- must be gray-coded or handshake-captured:
  - $flatten\u_csr.$procdff$669 [pclk] -> $procdff$644 [aclk_s] width=8  (cfg_af_th/cfg_ae_th captured via 2-phase toggle handshake u_sync_th_*)
  - $flatten\u_csr.$procdff$669 [pclk] -> $procdff$654 [aclk_m] width=8  (cfg_af_th/cfg_ae_th captured via 2-phase toggle handshake u_sync_th_*)
R2 PASS: no unsafe single-bit crossing (21 synchronized paths)

R3 review: synchronized bus widths = [32, 5, 1] (width > 1 must be gray-coded)

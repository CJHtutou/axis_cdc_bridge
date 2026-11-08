// apb3_csr_regs.sv -- AMBA 3 APB slave with the bridge control/status registers
`timescale 1ns/1ps
`default_nettype none

module apb3_csr_regs #(
    parameter int unsigned AF_TH_DEFAULT = 12,
    parameter int unsigned AE_TH_DEFAULT = 4
) (
    // APB3
    input  logic        pclk,
    input  logic        presetn,
    input  logic        psel,
    input  logic        penable,
    input  logic        pwrite,
    input  logic [7:0]  paddr,
    input  logic [31:0] pwdata,
    input  logic [3:0]  pstrb,
    output logic [31:0] prdata,
    output logic        pready,
    output logic        pslverr,

    // status from the data-plane domains (already synchronized to pclk)
    input  logic        st_full,
    input  logic        st_empty,
    input  logic        st_almost_full,
    input  logic        st_almost_empty,
    input  logic [7:0]  st_level,
    input  logic [31:0] pkt_cnt,
    input  logic [31:0] err_cnt,

    // configuration to the data plane
    output logic        cfg_enable,
    output logic        cfg_mode,
    output logic        cfg_parity_en,
    output logic        cfg_soft_rst,
    output logic [7:0]  cfg_af_th,
    output logic [7:0]  cfg_ae_th,
    output logic        cfg_thresh_toggle,   // flips on every THRESH write

    output logic        irq_out
);
    // ---------------- register addresses ----------------
    localparam logic [7:0] ADDR_CTRL     = 8'h00;
    localparam logic [7:0] ADDR_THRESH   = 8'h04;
    localparam logic [7:0] ADDR_STATUS   = 8'h08;
    localparam logic [7:0] ADDR_PKT_CNT  = 8'h0C;
    localparam logic [7:0] ADDR_ERR_CNT  = 8'h10;
    localparam logic [7:0] ADDR_IRQ_MASK = 8'h14;

    // ---------------- APB state machine ----------------
    typedef enum logic [1:0] {IDLE, SETUP, ACCESS} apb_state_e;
    apb_state_e state_q, state_d;

    logic access_q;          // a transfer is completing this cycle
    logic addr_valid;
    logic addr_ro;

    assign addr_valid = (paddr == ADDR_CTRL)   || (paddr == ADDR_THRESH) ||
                        (paddr == ADDR_STATUS) || (paddr == ADDR_PKT_CNT) ||
                        (paddr == ADDR_ERR_CNT)|| (paddr == ADDR_IRQ_MASK);

    assign addr_ro    = (paddr == ADDR_STATUS) || (paddr == ADDR_PKT_CNT);

    always_comb begin
        state_d = state_q;
        case (state_q)
            IDLE:   if (psel && !penable) state_d = SETUP;
            SETUP:  if (penable)          state_d = ACCESS;
            ACCESS:                       state_d = IDLE;
            default:                      state_d = IDLE;
        endcase
    end

    always_ff @(posedge pclk or negedge presetn) begin
        if (!presetn) state_q <= IDLE;
        else          state_q <= state_d;
    end

    assign access_q = (state_q == ACCESS);
    assign pready   = 1'b1;                       // zero wait states
    // error on illegal address, or on a write to a read-only register
    assign pslverr  = access_q & (~addr_valid | (pwrite & addr_ro));

    // ---------------- register file ----------------
    function automatic logic [31:0] apply_strb(input logic [31:0] old_v,
                                               input logic [31:0] new_v,
                                               input logic [3:0]  strb);
        for (int i = 0; i < 4; i++) begin
            apply_strb[i*8 +: 8] = strb[i] ? new_v[i*8 +: 8] : old_v[i*8 +: 8];
        end
    endfunction

    logic [31:0] ctrl_q, thresh_q, irq_mask_q;
    // W1C via a monotonic-counter offset: counters never decrease, so
    // "clear" = remember the current value and report (live - offset).
    logic [31:0] err_off_q;
    logic        soft_rst_q;
    logic        thresh_toggle_q;

    logic        wr_en;
    assign wr_en = access_q & pwrite & addr_valid & ~addr_ro;

    always_ff @(posedge pclk or negedge presetn) begin
        if (!presetn) begin
            ctrl_q     <= 32'h0000_0001;   // enabled out of reset
            thresh_q   <= {16'h0, AE_TH_DEFAULT[7:0], AF_TH_DEFAULT[7:0]};
            irq_mask_q <= 32'h0000_000F;
            err_off_q  <= 32'h0;
            soft_rst_q <= 1'b0;
            thresh_toggle_q <= 1'b0;
        end else begin
            soft_rst_q <= 1'b0;
            case ({wr_en, paddr})
                {1'b1, ADDR_CTRL}: begin
                    ctrl_q     <= apply_strb(ctrl_q, pwdata, pstrb);
                    soft_rst_q <= pwdata[3] & pstrb[0];
                end
                {1'b1, ADDR_THRESH}: begin
                    thresh_q        <= apply_strb(thresh_q, pwdata, pstrb);
                    thresh_toggle_q <= ~thresh_toggle_q;
                end
                {1'b1, ADDR_ERR_CNT}: begin
                    // W1C: writing 1 to a half-word clears everything counted so far
                    if (pwdata[15:0]  != 16'h0) err_off_q[15:0]  <= err_cnt[15:0];
                    if (pwdata[31:16] != 16'h0) err_off_q[31:16] <= err_cnt[31:16];
                end
                {1'b1, ADDR_IRQ_MASK}: irq_mask_q <= apply_strb(irq_mask_q, pwdata, pstrb);
                default: ;
            endcase
        end
    end

    assign prdata = (paddr == ADDR_CTRL)     ? ctrl_q :
                    (paddr == ADDR_THRESH)   ? thresh_q :
                    (paddr == ADDR_STATUS)   ? {16'h0, st_level,
                                               4'b0, st_almost_empty, st_almost_full,
                                               st_empty, st_full} :
                    (paddr == ADDR_PKT_CNT)  ? pkt_cnt :
                    (paddr == ADDR_ERR_CNT)  ? err_vis :
                    (paddr == ADDR_IRQ_MASK) ? irq_mask_q : 32'h0;

    assign cfg_enable    = ctrl_q[0];
    assign cfg_mode      = ctrl_q[1];
    assign cfg_parity_en = ctrl_q[2];
    assign cfg_soft_rst  = soft_rst_q;
    assign cfg_af_th     = thresh_q[7:0];
    assign cfg_ae_th     = thresh_q[15:8];
    assign cfg_thresh_toggle = thresh_toggle_q;

    // ---------------- interrupt ----------------
    logic [31:0] err_vis;
    assign err_vis = err_cnt - err_off_q;

    assign irq_out = ((err_vis[15:0]  != 16'h0) & irq_mask_q[0]) |
                     ((err_vis[31:16] != 16'h0) & irq_mask_q[1]) |
                     (st_almost_full               & irq_mask_q[2]) |
                     (st_almost_empty              & irq_mask_q[3]);
endmodule

`default_nettype wire

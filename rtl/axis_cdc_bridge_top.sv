// axis_cdc_bridge_top.sv -- AXI4-Stream async CDC bridge + APB3 control plane
`timescale 1ns/1ps
`default_nettype none

module axis_cdc_bridge_top #(
    parameter int DATA_W = 32,       // 32 or 64
    parameter int DEPTH  = 16        // 16/32/64
) (
    // master-side (write) domain
    input  logic                aclk_m,
    input  logic                aresetn_m,
    input  logic                s_axis_tvalid,
    output logic                s_axis_tready,
    input  logic [DATA_W-1:0]   s_axis_tdata,
    input  logic [DATA_W/8-1:0] s_axis_tkeep,
    input  logic                s_axis_tlast,
    input  logic                s_axis_tuser,   // expected parity of {tdata,tkeep}
    // slave-side (read) domain
    input  logic                aclk_s,
    input  logic                aresetn_s,
    output logic                m_axis_tvalid,
    input  logic                m_axis_tready,
    output logic [DATA_W-1:0]   m_axis_tdata,
    output logic [DATA_W/8-1:0] m_axis_tkeep,
    output logic                m_axis_tlast,
    // APB3 control plane
    input  logic                pclk,
    input  logic                presetn,
    input  logic                psel,
    input  logic                penable,
    input  logic                pwrite,
    input  logic [7:0]          paddr,
    input  logic [31:0]         pwdata,
    input  logic [3:0]          pstrb,
    output logic [31:0]         prdata,
    output logic                pready,
    output logic                pslverr,
    output logic                irq_out
);
    localparam int KEEP_W  = DATA_W / 8;
    localparam int PW_DATA = DATA_W + KEEP_W + 1;
    localparam int AW      = $clog2(DEPTH);
    localparam int PW      = AW + 1;

    logic [PW_DATA-1:0] wdata_p, rdata_p, mdata_p;
    logic               wfull, walmost_full;
    logic               rempty, ralmost_empty;
    logic               wr_en, skid_ready, rd_en;
    logic [PW-1:0]      level_w;

    logic               cfg_enable, cfg_mode, cfg_parity_en, cfg_soft_rst;
    logic [7:0]         cfg_af_th, cfg_ae_th;

    // pclk-domain status
    logic               st_full, st_empty, st_af, st_ae;
    logic [7:0]         st_level;
    logic [31:0]        pkt_cnt, ovf_cnt, par_cnt, err_cnt;
    logic [31:0]        w_committed_r, r_consumed;
    logic               pkt_mode_r, parity_en_m;
    logic               pkt_avail, parity_err;

    // ---------------- data plane ----------------
    assign wr_en         = s_axis_tvalid && !wfull && cfg_enable;
    assign s_axis_tready = !wfull && cfg_enable;
    assign wdata_p       = {s_axis_tlast, s_axis_tkeep, s_axis_tdata};

    // parity: tuser carries the expected XOR of every tdata/tkeep bit
    logic calc_par;
    assign calc_par = ^s_axis_tdata ^ ^s_axis_tkeep;
    assign parity_err = wr_en && parity_en_m && (s_axis_tuser != calc_par);

    // packet (store-and-forward) mode: reads only start on a complete packet
    assign pkt_avail = (w_committed_r != r_consumed);
    logic  rd_valid;
    assign rd_valid  = !rempty && (!pkt_mode_r || pkt_avail);
    assign rd_en     = skid_ready && rd_valid;

    async_fifo_core #(
        .DATA_W (PW_DATA),
        .DEPTH  (DEPTH)
    ) u_fifo (
        .af_th        (cfg_af_th),
        .ae_th        (cfg_ae_th),
        .wclk         (aclk_m),
        .wrst_n       (aresetn_m),
        .wr_en        (wr_en),
        .wdata        (wdata_p),
        .wfull        (wfull),
        .walmost_full (walmost_full),
        .rclk         (aclk_s),
        .rrst_n       (aresetn_s),
        .rd_en        (rd_en),
        .rdata        (rdata_p),
        .rempty       (rempty),
        .ralmost_empty(ralmost_empty),
        .wlevel_o     (level_w)
    );

    axis_skid_buffer #(
        .W (PW_DATA)
    ) u_skid (
        .clk    (aclk_s),
        .rst_n  (aresetn_s),
        .s_valid(rd_valid),
        .s_ready(skid_ready),
        .s_data (rdata_p),
        .m_valid(m_axis_tvalid),
        .m_ready(m_axis_tready),
        .m_data (mdata_p)
    );

    assign m_axis_tdata = mdata_p[DATA_W-1:0];
    assign m_axis_tkeep = mdata_p[DATA_W +: KEEP_W];
    assign m_axis_tlast = mdata_p[PW_DATA-1];

    // ---------------- status into pclk domain ----------------
    cdc_sync_2ff #(.W(1)) u_sync_full   (.clk(pclk), .rst_n(presetn), .d(wfull),         .q(st_full));
    cdc_sync_2ff #(.W(1)) u_sync_afull  (.clk(pclk), .rst_n(presetn), .d(walmost_full), .q(st_af));
    cdc_sync_2ff #(.W(1)) u_sync_empty  (.clk(pclk), .rst_n(presetn), .d(rempty),        .q(st_empty));
    cdc_sync_2ff #(.W(1)) u_sync_aempty (.clk(pclk), .rst_n(presetn), .d(ralmost_empty), .q(st_ae));

    // fill level: gray-coded in the write domain, decoded in pclk
    logic [PW-1:0] level_gray, level_sync, level_bin;
    assign level_gray = (level_w >> 1) ^ level_w;
    cdc_sync_2ff #(.W(PW)) u_sync_level (
        .clk(pclk), .rst_n(presetn), .d(level_gray), .q(level_sync)
    );

    integer li;
    always_comb begin
        level_bin[PW-1] = level_sync[PW-1];
        for (li = PW-2; li >= 0; li = li - 1) begin
            level_bin[li] = level_bin[li+1] ^ level_sync[li];
        end
    end
    assign st_level = {{(8-PW){1'b0}}, level_bin};

    // ---------------- packet-mode bookkeeping ----------------
    // committed packets are counted in the write domain and gray-synced to the
    // read domain; consumed packets are counted locally in the read domain.
    cdc_gray_counter #(.W(32)) u_commit_cnt (
        .src_clk(aclk_m), .src_rst_n(aresetn_m), .inc(wr_en && s_axis_tlast),
        .dst_clk(aclk_s), .dst_rst_n(aresetn_s), .dst_value(w_committed_r)
    );

    always_ff @(posedge aclk_s or negedge aresetn_s) begin
        if (!aresetn_s) r_consumed <= '0;
        else if (m_axis_tvalid && m_axis_tready && m_axis_tlast) r_consumed <= r_consumed + 1'b1;
    end

    cdc_sync_2ff #(.W(1)) u_sync_mode (.clk(aclk_s), .rst_n(aresetn_s), .d(cfg_mode),      .q(pkt_mode_r));
    cdc_sync_2ff #(.W(1)) u_sync_par  (.clk(aclk_m), .rst_n(aresetn_m), .d(cfg_parity_en), .q(parity_en_m));

    // ---------------- event counters ----------------
    logic pkt_inc, ovf_inc;
    assign pkt_inc = m_axis_tvalid && m_axis_tready && m_axis_tlast;
    assign ovf_inc = s_axis_tvalid && wfull && cfg_enable;

    cdc_gray_counter #(.W(32)) u_pkt_cnt (
        .src_clk(aclk_s), .src_rst_n(aresetn_s), .inc(pkt_inc),
        .dst_clk(pclk),   .dst_rst_n(presetn),   .dst_value(pkt_cnt)
    );

    cdc_gray_counter #(.W(32)) u_ovf_cnt (
        .src_clk(aclk_m), .src_rst_n(aresetn_m), .inc(ovf_inc),
        .dst_clk(pclk),   .dst_rst_n(presetn),   .dst_value(ovf_cnt)
    );

    // [31:16] overflow attempts, [15:0] parity errors (v0.3)
    cdc_gray_counter #(.W(32)) u_par_cnt (
        .src_clk(aclk_m), .src_rst_n(aresetn_m), .inc(parity_err),
        .dst_clk(pclk),   .dst_rst_n(presetn),   .dst_value(par_cnt)
    );

    // [31:16] overflow attempts, [15:0] parity errors
    assign err_cnt = {ovf_cnt[15:0], par_cnt[15:0]};

    // ---------------- APB3 control plane ----------------
    apb3_csr_regs u_csr (
        .pclk(pclk), .presetn(presetn),
        .psel(psel), .penable(penable), .pwrite(pwrite),
        .paddr(paddr), .pwdata(pwdata), .pstrb(pstrb),
        .prdata(prdata), .pready(pready), .pslverr(pslverr),
        .st_full(st_full), .st_empty(st_empty),
        .st_almost_full(st_af), .st_almost_empty(st_ae),
        .st_level(st_level),
        .pkt_cnt(pkt_cnt), .err_cnt(err_cnt),
        .cfg_enable(cfg_enable), .cfg_mode(cfg_mode),
        .cfg_parity_en(cfg_parity_en), .cfg_soft_rst(cfg_soft_rst),
        .cfg_af_th(cfg_af_th), .cfg_ae_th(cfg_ae_th),
        .irq_out(irq_out)
    );

    // reserved for v0.3 (packet mode / parity / soft reset) -- keep lint quiet
    logic unused_cfg;
    assign unused_cfg = cfg_mode ^ cfg_parity_en ^ cfg_soft_rst;
endmodule

`default_nettype wire

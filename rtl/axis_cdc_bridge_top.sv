// axis_cdc_bridge_top.sv -- AXI4-Stream async CDC bridge (v0.1, data plane)
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
    // slave-side (read) domain
    input  logic                aclk_s,
    input  logic                aresetn_s,
    output logic                m_axis_tvalid,
    input  logic                m_axis_tready,
    output logic [DATA_W-1:0]   m_axis_tdata,
    output logic [DATA_W/8-1:0] m_axis_tkeep,
    output logic                m_axis_tlast
);
    localparam int KEEP_W  = DATA_W / 8;
    localparam int PW_DATA = DATA_W + KEEP_W + 1;

    logic [PW_DATA-1:0] wdata_p, rdata_p, mdata_p;
    logic               wfull, walmost_full;
    logic               rempty, ralmost_empty;
    logic               wr_en, skid_ready, rd_en;

    assign wr_en         = s_axis_tvalid && !wfull;
    assign s_axis_tready = !wfull;
    assign wdata_p       = {s_axis_tlast, s_axis_tkeep, s_axis_tdata};

    assign rd_en = skid_ready && !rempty;

    async_fifo_core #(
        .DATA_W (PW_DATA),
        .DEPTH  (DEPTH)
    ) u_fifo (
        .wclk        (aclk_m),
        .wrst_n      (aresetn_m),
        .wr_en       (wr_en),
        .wdata       (wdata_p),
        .wfull       (wfull),
        .walmost_full(walmost_full),
        .rclk        (aclk_s),
        .rrst_n      (aresetn_s),
        .rd_en       (rd_en),
        .rdata       (rdata_p),
        .rempty      (rempty),
        .ralmost_empty(ralmost_empty)
    );

    axis_skid_buffer #(
        .W (PW_DATA)
    ) u_skid (
        .clk    (aclk_s),
        .rst_n  (aresetn_s),
        .s_valid(!rempty),
        .s_ready(skid_ready),
        .s_data (rdata_p),
        .m_valid(m_axis_tvalid),
        .m_ready(m_axis_tready),
        .m_data (mdata_p)
    );

    assign m_axis_tdata = mdata_p[DATA_W-1:0];
    assign m_axis_tkeep = mdata_p[DATA_W +: KEEP_W];
    assign m_axis_tlast = mdata_p[PW_DATA-1];
endmodule

`default_nettype wire

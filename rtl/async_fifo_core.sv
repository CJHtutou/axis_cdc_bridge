// async_fifo_core.sv -- gray-code dual-clock FIFO (Cummings style)
`timescale 1ns/1ps
`default_nettype none

module async_fifo_core #(
    parameter int DATA_W = 32,
    parameter int DEPTH  = 16,               // must be a power of two
    parameter int AF_TH  = (DEPTH > 4) ? (DEPTH - 4) : 1,
    parameter int AE_TH  = 1
) (
    input  logic              wclk,
    input  logic              wrst_n,
    input  logic              wr_en,
    input  logic [DATA_W-1:0] wdata,
    output logic              wfull,
    output logic              walmost_full,

    input  logic              rclk,
    input  logic              rrst_n,
    input  logic              rd_en,
    output logic [DATA_W-1:0] rdata,
    output logic              rempty,
    output logic              ralmost_empty
);
    localparam int AW = $clog2(DEPTH);
    localparam int PW = AW + 1;

    localparam logic [PW-1:0] AF_TH_V = AF_TH;
    localparam logic [PW-1:0] AE_TH_V = AE_TH;

    logic [DATA_W-1:0] mem [0:DEPTH-1];

    logic [PW-1:0] wbin, wbin_next, wgray, wgray_next;
    logic [PW-1:0] rbin, rbin_next, rgray, rgray_next;
    logic [PW-1:0] rq2_wgray;              // read gray synced into write domain
    logic [PW-1:0] rptr_sync_w;            // read pointer (gray or binary) in write domain
    logic [PW-1:0] rbin_bin_sync;          // BUG_1 only: raw binary pointer
    logic [PW-1:0] wq2_rgray;              // write gray synced into read domain
    logic [PW-1:0] rbin_sync_w, wbin_sync_r;
    logic [PW-1:0] wlevel, rlevel;
    logic          wfull_val, rempty_val;

    // ---------------- storage ----------------
    always_ff @(posedge wclk) begin
        if (wr_en && !wfull) mem[wbin[AW-1:0]] <= wdata;
    end

    assign rdata = mem[rbin[AW-1:0]];

    // ---------------- write pointer ----------------
    assign wbin_next  = wbin + {{(PW-1){1'b0}}, (wr_en && !wfull)};
    assign wgray_next = (wbin_next >> 1) ^ wbin_next;

    always_ff @(posedge wclk or negedge wrst_n) begin
        if (!wrst_n) begin
            wbin  <= '0;
            wgray <= '0;
        end else begin
            wbin  <= wbin_next;
            wgray <= wgray_next;
        end
    end

    // ---------------- read pointer ----------------
    assign rbin_next  = rbin + {{(PW-1){1'b0}}, (rd_en && !rempty)};
    assign rgray_next = (rbin_next >> 1) ^ rbin_next;

    always_ff @(posedge rclk or negedge rrst_n) begin
        if (!rrst_n) begin
            rbin   <= '0;
            rgray  <= '0;
            rempty <= 1'b1;
        end else begin
            rbin   <= rbin_next;
            rgray  <= rgray_next;
            rempty <= rempty_val;
        end
    end

    // ---------------- gray <-> binary ----------------
    // Yosys-friendly gray -> binary (assignment to the function name, no `return`)
    function automatic logic [PW-1:0] gray2bin(input logic [PW-1:0] g);
        logic [PW-1:0] b;
        integer i;
        begin
            b[PW-1] = g[PW-1];
            for (i = PW-2; i >= 0; i = i - 1) begin
                b[i] = b[i+1] ^ g[i];
            end
            gray2bin = b;
        end
    endfunction

    // ---------------- synchronizers ----------------
`ifdef BUG_1_BIN_SYNC
    // MUTATION: multi-bit binary pointer crosses the clock domain directly
    cdc_sync_2ff #(.W(PW)) u_sync_r2w (
        .clk(wclk), .rst_n(wrst_n), .d(rbin), .q(rbin_bin_sync)
    );
    assign rptr_sync_w = rbin_bin_sync;
`else
    cdc_sync_2ff #(.W(PW)) u_sync_r2w (
        .clk(wclk), .rst_n(wrst_n), .d(rgray), .q(rq2_wgray)
    );
    assign rptr_sync_w = gray2bin(rq2_wgray);
`endif

    cdc_sync_2ff #(.W(PW)) u_sync_w2r (
        .clk(rclk), .rst_n(rrst_n), .d(wgray), .q(wq2_rgray)
    );

    // ---------------- flags ----------------
`ifdef BUG_1_BIN_SYNC
    assign wfull_val = (wbin_next == {~rptr_sync_w[PW-1], rptr_sync_w[PW-2:0]});
`else
  `ifdef BUG_3_FULL_COND
    // MUTATION: only the MSB is inverted -- breaks gray reflection symmetry
    assign wfull_val = (wgray_next[PW-1] == ~rq2_wgray[PW-1]) &&
                       (wgray_next[PW-2:0] == rq2_wgray[PW-2:0]);
  `else
    assign wfull_val = (wgray_next[PW-1:PW-2] == ~rq2_wgray[PW-1:PW-2]) &&
                       (wgray_next[PW-3:0] == rq2_wgray[PW-3:0]);
  `endif
`endif

`ifdef BUG_2_EMPTY_CMP
    // MUTATION: inverted empty comparison -- reads start before data is written
    assign rempty_val = (rgray_next != wq2_rgray);
`else
    assign rempty_val = (rgray_next == wq2_rgray);
`endif

    always_ff @(posedge wclk or negedge wrst_n) begin
        if (!wrst_n) wfull <= 1'b0;
        else         wfull <= wfull_val;
    end

    // ---------------- occupancy / almost flags ----------------
    assign rbin_sync_w = rptr_sync_w;
    assign wbin_sync_r = gray2bin(wq2_rgray);

    assign wlevel = wbin - rbin_sync_w;
    assign rlevel = rbin - wbin_sync_r;

    assign walmost_full  = (wlevel >= AF_TH_V);
    assign ralmost_empty = (rlevel <= AE_TH_V);
endmodule

`default_nettype wire

// cdc_gray_counter.sv -- event counter crossing a clock domain as gray code
`timescale 1ns/1ps
`default_nettype none

module cdc_gray_counter #(
    parameter int W = 32
) (
    input  logic         src_clk,
    input  logic         src_rst_n,
    input  logic         inc,
    input  logic         dst_clk,
    input  logic         dst_rst_n,
    output logic [W-1:0] dst_value
);
    logic [W-1:0] bin_q;
    logic [W-1:0] gray;
    logic [W-1:0] sync1, sync2;
    logic [W-1:0] bin_out;

    always_ff @(posedge src_clk or negedge src_rst_n) begin
        if (!src_rst_n) bin_q <= '0;
        else if (inc)   bin_q <= bin_q + 1'b1;
    end

    assign gray = (bin_q >> 1) ^ bin_q;

    always_ff @(posedge dst_clk or negedge dst_rst_n) begin
        if (!dst_rst_n) begin
            sync1 <= '0;
            sync2 <= '0;
        end else begin
            sync1 <= gray;
            sync2 <= sync1;
        end
    end

    // gray -> binary
    logic [W-1:0] b;
    integer i;
    always_comb begin
        b[W-1] = sync2[W-1];
        for (i = W-2; i >= 0; i = i - 1) begin
            b[i] = b[i+1] ^ sync2[i];
        end
        bin_out = b;
    end

    assign dst_value = bin_out;
endmodule

`default_nettype wire

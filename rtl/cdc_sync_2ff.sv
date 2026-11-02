// cdc_sync_2ff.sv -- 2-FF synchronizer for multi-bit gray-coded pointers
`timescale 1ns/1ps
`default_nettype none

module cdc_sync_2ff #(
    parameter int W = 1
) (
    input  logic         clk,
    input  logic         rst_n,
    input  logic [W-1:0] d,
    output logic [W-1:0] q
);
    (* ASYNC_REG = "TRUE" *) logic [W-1:0] stage1;
    (* ASYNC_REG = "TRUE" *) logic [W-1:0] stage2;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            stage1 <= '0;
            stage2 <= '0;
        end else begin
            stage1 <= d;
            stage2 <= stage1;
        end
    end

    assign q = stage2;
endmodule

`default_nettype wire

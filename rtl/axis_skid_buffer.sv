// axis_skid_buffer.sv -- 2-entry AXI-Stream register slice (skid buffer v0)
// Registered output, no combinational m_ready -> s_ready path.
`timescale 1ns/1ps
`default_nettype none

module axis_skid_buffer #(
    parameter int W = 32
) (
    input  logic         clk,
    input  logic         rst_n,
    input  logic         s_valid,
    output logic         s_ready,
    input  logic [W-1:0] s_data,
    output logic         m_valid,
    input  logic         m_ready,
    output logic [W-1:0] m_data
);
    localparam int DEPTH = 2;

    logic [W-1:0] mem [0:DEPTH-1];
    logic [1:0]   cnt;
    logic         rd_ptr, wr_ptr;

    assign s_ready = (cnt != 2'd2);
    assign m_valid = (cnt != 2'd0);
    assign m_data  = mem[rd_ptr];

    logic push, pop;
    assign push = s_valid && s_ready;
    assign pop  = m_valid && m_ready;

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cnt    <= 2'd0;
            rd_ptr <= 1'b0;
            wr_ptr <= 1'b0;
        end else begin
            if (push) begin
                mem[wr_ptr] <= s_data;
                wr_ptr      <= ~wr_ptr;
            end
            if (pop) begin
                rd_ptr <= ~rd_ptr;
            end
            cnt <= cnt + {1'b0, push} - {1'b0, pop};
        end
    end
endmodule

`default_nettype wire

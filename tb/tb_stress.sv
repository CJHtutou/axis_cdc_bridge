// tb_stress.sv -- pure-RTL stress bench: measures raw Verilator throughput
// (no cocotb / Python in the loop). 100k beats, back-to-back, no backpressure.
`timescale 1ns/1ps
module tb_stress;
    localparam int N_BEATS = 100000;

    logic aclk_m = 0, aclk_s = 0;
    logic rst_n = 0;
    logic s_valid = 0, s_ready;
    logic [31:0] s_data = 0;
    logic [3:0]  s_keep = 4'hF;
    logic        s_last = 0;
    logic m_valid, m_ready = 1;
    logic [31:0] m_data;
    logic [3:0]  m_keep;
    logic        m_last;

    always #5  aclk_m = ~aclk_m;   // 100 MHz
    always #15 aclk_s = ~aclk_s;   // 33.3 MHz

    axis_cdc_bridge_top dut (
        .aclk_m(aclk_m), .aresetn_m(rst_n),
        .s_axis_tvalid(s_valid), .s_axis_tready(s_ready),
        .s_axis_tdata(s_data), .s_axis_tkeep(s_keep), .s_axis_tlast(s_last),
        .aclk_s(aclk_s), .aresetn_s(rst_n),
        .m_axis_tvalid(m_valid), .m_axis_tready(m_ready),
        .m_axis_tdata(m_data), .m_axis_tkeep(m_keep), .m_axis_tlast(m_last)
    );

    int unsigned sent = 0, recv = 0;
    logic [31:0] lfsr = 32'hACE1_2345;

    initial begin
        repeat (4) @(posedge aclk_m);
        rst_n <= 1;
        repeat (4) @(posedge aclk_m);
        fork
            // source
            forever begin
                @(posedge aclk_m);
                if (sent < N_BEATS) begin
                    s_valid <= 1'b1;
                    lfsr    <= {lfsr[30:0], lfsr[31] ^ lfsr[21] ^ lfsr[1] ^ lfsr[0]};
                    s_data  <= lfsr;
                    s_last  <= ((sent % 5) == 4);
                end else begin
                    s_valid <= 1'b0;
                end
                if (s_valid && s_ready) sent <= sent + 1;
            end
            // sink
            forever begin
                @(posedge aclk_s);
                if (m_valid && m_ready) begin
                    recv <= recv + 1;
                    if (recv + 1 >= N_BEATS) begin
                        $display("STRESS DONE sent=%0d recv=%0d", sent, recv + 1);
                        $finish;
                    end
                end
            end
        join
    end

    initial begin
        #20_000_000;   // 20 ms watchdog
        $display("STRESS TIMEOUT sent=%0d recv=%0d", sent, recv);
        $finish;
    end
endmodule

// gray_props.sv -- combinational formal properties of the gray-code pointer scheme
//
// proven with:  yosys -p "read_verilog -formal -sv formal/gray_props.sv;
//                         prep -top gray_props; write_smt2 -wires"
//               yosys-smtbmc -s z3 -t 1
module gray_props #(
    parameter int W     = 5,
    parameter int DEPTH = 16
);
    (* anyseq *) logic [W-1:0] bin_w;
    (* anyseq *) logic [W-1:0] bin_r;

    function automatic logic [W-1:0] gray(input logic [W-1:0] b);
        gray = (b >> 1) ^ b;
    endfunction

    logic [W-1:0] wbin_next, wgray, wgray_next, rgray;

    assign wbin_next  = bin_w + 1'b1;
    assign wgray      = gray(bin_w);
    assign wgray_next = gray(wbin_next);
    assign rgray      = gray(bin_r);

    // P1: incrementing a gray-coded pointer flips exactly one bit
    always_comb begin
        p1_single_bit: assert ($countones(wgray ^ wgray_next) == 1);
    end

    // P2: "two MSBs inverted, rest equal" is exactly occupancy == DEPTH
    logic full_cond;
    logic [W-1:0] occ_next;

    assign full_cond = (wgray_next[W-1:W-2] == ~rgray[W-1:W-2]) &&
                       (wgray_next[W-3:0]   ==  rgray[W-3:0]);
    assign occ_next  = wbin_next - bin_r;

    always_comb begin
        p2_full_equiv: assert (full_cond == (occ_next == DEPTH));
    end
endmodule

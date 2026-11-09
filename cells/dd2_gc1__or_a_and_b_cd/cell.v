module dd2_gc1__or_a_and_b_cd (A, B, C, D, Y);
    input A;
    input B;
    input C;
    input D;
    output Y;
    assign Y = ~(A | (B & (C | D)));
endmodule

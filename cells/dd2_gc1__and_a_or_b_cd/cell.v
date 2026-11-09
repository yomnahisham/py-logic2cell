module dd2_gc1__and_a_or_b_cd (A, B, C, D, Y);
    input A;
    input B;
    input C;
    input D;
    output Y;
    assign Y = ~(A & (B | (C & D)));
endmodule

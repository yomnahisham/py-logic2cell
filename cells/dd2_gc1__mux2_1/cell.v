module dd2_gc1__mux2_1 (A, B, C, Y);
    input A;
    input B;
    input C;
    output Y;
    assign Y = (A & ~C) | (B & C);
endmodule

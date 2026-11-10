module dd2_gc1__f17ff_1 (A, B, C, D, Y);
    input A;
    input B;
    input C;
    input D;
    output Y;
    assign Y = ~(D & ((A & B) | (C & (A | B))));
endmodule

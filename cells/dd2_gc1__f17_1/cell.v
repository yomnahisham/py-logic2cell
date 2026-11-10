module dd2_gc1__f17_1 (A, B, C, Y);
    input A;
    input B;
    input C;
    output Y;
    assign Y = ~((A & B) | (C & (A | B)));
endmodule

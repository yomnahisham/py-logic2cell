module dd2_gc1__nand3_1 (A, B, C, Y);
    input A;
    input B;
    input C;
    output Y;
    assign Y = ~(A & B & C);
endmodule

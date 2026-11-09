module dd2_gc1__nand2_1 (A, B, Y);
    input A;
    input B;
    output Y;
    assign Y = ~(A & B);
endmodule

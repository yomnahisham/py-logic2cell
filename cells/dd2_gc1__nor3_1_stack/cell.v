module dd2_gc1__nor3_1_stack (A, B, C, Y);
    input A;
    input B;
    input C;
    output Y;
    assign Y = ~(A | B | C);
endmodule

module dd2_gc1__nor2_1 (A, B, Y);
    input A;
    input B;
    output Y;
    assign Y = ~(A | B);
endmodule

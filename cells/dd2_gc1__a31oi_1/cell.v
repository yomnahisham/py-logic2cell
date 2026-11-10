module dd2_gc1__a31oi_1 (A1, A2, A3, B1, Y);
    input A1;
    input A2;
    input A3;
    input B1;
    output Y;
    assign Y = ~((A1 & A2 & A3) | B1);
endmodule

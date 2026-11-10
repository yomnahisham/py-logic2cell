module dd2_gc1__or_and_maj (A, B, C, D, Y);
    input A;
    input B;
    input C;
    input D;
    output Y;
    assign Y = (C & D) | (A & B & (C | D));
endmodule

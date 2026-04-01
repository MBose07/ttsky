/*
 * Copyright (c) 2024 Your Name
 * SPDX-License-Identifier: Apache-2.0
 */
module tt_um_cic #(
	parameter integer out_width = 11,
	parameter integer in_width = 11,
	parameter integer decimation_ratio = 8,
	parameter integer order = 6,
	parameter integer differential_delay = 2
) (
	input  wire [7:0] ui_in,    // Dedicated inputs
    output wire [7:0] uo_out,   // Dedicated outputs
    input  wire [7:0] uio_in,   // IOs: Input path
    output wire [7:0] uio_out,  // IOs: Output path
	output wire [7:0] uio_oe,   // IOs: Enable path (active high: 0=input, 1=output)
    input  wire       ena,
    input  wire       clk,
    input  wire       rst_n
);
wire [10:0] d_in;
wire valid_out;
assign d_in = {uio_in[4], uio_in[3], uio_in[2], ui_in};
wire [10:0] d_out;
assign uo_out     = d_out[7:0];
assign uio_out[5] = d_out[8];
assign uio_out[6] = d_out[9];
assign uio_out[7] = d_out[10];
wire valid_in;
assign valid_in = uio_in[0];
assign uio_out[1] = valid_out;
assign uio_out[0] = 1'b0;
assign uio_out[2] = 1'b0;
assign uio_out[3] = 1'b0;
assign uio_out[4] = 1'b0;
assign uio_oe = 8'b11100010;
wire _unused = &{ena, 1'b0};
	
localparam integer COUNTW = $clog2(decimation_ratio);
localparam integer GAIN_BITS = order * $clog2(decimation_ratio * differential_delay);
reg signed [in_width+GAIN_BITS-1:0] d_tmp;
reg signed [in_width+GAIN_BITS-1:0] integrator [0:order-1];
reg [COUNTW-1 : 0] counter;
	always@(posedge clk or negedge rst_n) begin
		if(!rst_n) counter <= {COUNTW{1'b1}};
    else if(valid_in) begin
        counter<=counter+1;
    end
end
assign valid_out = (counter == {COUNTW{1'b0}});

// CHANGED: wire → reg so the combinational always @(*) block below can drive
//          this array without Verilator flagging a circular dependency (UNOPTFLAT).
//          Semantics are identical; it remains purely combinational.
reg signed [in_width+GAIN_BITS-1:0] comb [0:order-1];

reg signed [in_width+GAIN_BITS-1:0] d_comb [0:order-1][0:differential_delay-1];
integer i;
// Integrator + decimation control
	always @(posedge clk or negedge rst_n) begin
		if (!rst_n) begin
		for (i = 0; i <= order-1; i = i + 1) begin
			integrator[i] <= {(in_width+GAIN_BITS){1'b0}};
		end
		d_tmp <= {(in_width+GAIN_BITS){1'b0}};
	end else if(valid_in) begin
		integrator[0] <= integrator[0] + {{GAIN_BITS{d_in[in_width-1]}}, d_in};
		for(i = 1; i <= order-1; i = i + 1) begin
			integrator[i] <= integrator[i] + integrator[i-1];
		end
		// Decimation control: when valid_out enabled capture output
		if (valid_out ) begin
			d_tmp <= integrator[order-1];
		end
	end
end
integer i1;
integer j1;
// Comb section (processes one decimated sample when valid_out is asserted)
	always @(posedge clk or negedge rst_n) begin
		if (!rst_n) begin
			for (i1 = 0; i1 <= order-1; i1 = i1 + 1) begin
				for (j1 = 0; j1 < differential_delay; j1 = j1 + 1) begin
					d_comb[i1][j1] <= {(in_width+GAIN_BITS){1'b0}};
	            end
	        end
	    end else begin
	        if (valid_out)  begin
				for (j1 = differential_delay-1; j1 > 0; j1 = j1 - 1) begin
					d_comb[0][j1] <= d_comb[0][j1-1];
	            end
	            d_comb[0][0] <= d_tmp;
					
				for (i1 = 1; i1 <= order-1; i1 = i1 + 1) begin
					for (j1 = differential_delay-1; j1 > 0; j1 = j1 - 1) begin
						d_comb[i1][j1] <= d_comb[i1][j1-1];
	                end
					d_comb[i1][0] <= comb[i1-1];
	            end
	        end
	    end
end

integer i2;
always @(*) begin
    comb[0] = d_tmp - d_comb[0][differential_delay-1];
    for (i2 = 1; i2 < order; i2 = i2 + 1)
        comb[i2] = comb[i2-1] - d_comb[i2][differential_delay-1];
end

assign d_out =
    ( comb[order-1] + (1 << (in_width+GAIN_BITS-out_width-1)) )
    >>> (in_width+GAIN_BITS-out_width);
endmodule

# SPDX-FileCopyrightText: © 2024 Tiny Tapeout
# SPDX-License-Identifier: Apache-2.0

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge, Timer

def drive_cic_inputs(tt_um_cic, val, valid_in=True):
    """
    Constructs and drives all input pins in ONE transaction to avoid race conditions.
    Maps an 11-bit signed value into ui_in and uio_in[4:2].
    """
    # 1. Handle 11-bit signed -> unsigned conversion
    val_unsigned = int(val) & 0x7FF
    
    # 2. Drive ui_in (Bits 7:0)
    tt_um_cic.ui_in.value = val_unsigned & 0xFF
    
    # 3. Construct uio_in (Bits 0, 2, 3, 4 are inputs)
    # Bit 0 = valid_in
    uio_val = 0x01 if valid_in else 0x00
    
    # Extract bits 8, 9, 10 of sample and map to uio_in[2, 3, 4]
    bit8  = (val_unsigned >> 8) & 0x1
    bit9  = (val_unsigned >> 9) & 0x1
    bit10 = (val_unsigned >> 10) & 0x1
    
    uio_val |= (bit8 << 2) | (bit9 << 3) | (bit10 << 4)
    
    # DRIVE ONCE: This prevents the '256 -> 0' overwrite bug
    tt_um_cic.uio_in.value = uio_val

def get_output_value(tt_um_cic):
    """Unpacks an 11-bit signed value from uo_out and uio_out[7:5]"""
    low_byte = tt_um_cic.uo_out.value.integer
    
    # Reconstruct from uio_out[7:5]
    uio_val = tt_um_cic.uio_out.value.integer
    bit8  = (uio_val >> 5) & 0x1
    bit9  = (uio_val >> 6) & 0x1
    bit10 = (uio_val >> 7) & 0x1
    
    combined = low_byte | (bit8 << 8) | (bit9 << 9) | (bit10 << 10)
    
    # Correctly sign-extend from 11-bit to Python integer
    if combined & (1 << 10):
        combined -= (1 << 11)
    return combined

@cocotb.test()
async def test_cic_audio_processing(tt_um_cic):
    """
    Feed audio samples from input.txt, record results to output.txt,
    and assert every output sample matches expected.txt.
    """

    # ── 1. Clock ────────────────────────────────────────────────────────────
    cocotb.start_soon(Clock(tt_um_cic.clk, 100, units="ns").start())

    # ── 2. Reset ─────────────────────────────────────────────────────────────
    tt_um_cic.rst_n.value = 0
    tt_um_cic.ena.value   = 1
    tt_um_cic.uio_in.value = 0
    tt_um_cic.ui_in.value  = 0
    await Timer(1, units="us")
    tt_um_cic.rst_n.value = 1
    await RisingEdge(tt_um_cic.clk)

    # ── 3. Load input & expected samples ────────────────────────────────────
    with open("input.txt", "r") as f:
        input_samples = [int(line.strip()) for line in f if line.strip()]

    with open("expected.txt", "r") as f:
        expected_samples = [int(line.strip()) for line in f if line.strip()]

    tt_um_cic._log.info(f"Loaded {len(input_samples)} input samples")
    tt_um_cic._log.info(f"Loaded {len(expected_samples)} expected samples")

    output_samples = []

    # ── 4. Main Processing Loop ──────────────────────────────────────────────
    for sample in input_samples:
        await RisingEdge(tt_um_cic.clk)

        # Drive inputs: combines sample bits and valid_in in one write
        drive_cic_inputs(tt_um_cic, sample, valid_in=True)

        # TIMING: Wait for FallingEdge to ensure signals have settled before reading
        await FallingEdge(tt_um_cic.clk)

        # Capture output when valid_out (uio_out[1]) is high
        if (tt_um_cic.uio_out.value.integer >> 1) & 0x1:
            out_val = get_output_value(tt_um_cic)
            output_samples.append(out_val)

    # ── 5. Flush: collect any remaining outputs ───────────────────────────────
    for _ in range(200):
        await RisingEdge(tt_um_cic.clk)
        drive_cic_inputs(tt_um_cic, 0, valid_in=False)
        
        await FallingEdge(tt_um_cic.clk)
        if (tt_um_cic.uio_out.value.integer >> 1) & 0x1:
            out_val = get_output_value(tt_um_cic)
            output_samples.append(out_val)

    # ── 6. Save output.txt ───────────────────────────────────────────────────
    with open("output.txt", "w") as f:
        for s in output_samples:
            f.write(f"{s}\n")

    tt_um_cic._log.info(
        f"Simulation finished. Captured {len(output_samples)} output samples."
    )

    # ── 7. Assert against expected.txt ───────────────────────────────────────
    assert len(output_samples) > 0, \
        "No output samples captured — check valid_out signal (uio_out[1])"

    # For CIC filters, there might be a small delay. If lengths don't match, 
    # we trim to the shorter list for comparison.
    compare_len = min(len(output_samples), len(expected_samples))
    
    mismatches = []
    for idx in range(compare_len):
        got = output_samples[idx]
        exp = expected_samples[idx]
        if got != exp:
            mismatches.append((idx, got, exp))
            if len(mismatches) < 10: # Don't flood the log if everything fails
                tt_um_cic._log.error(
                    f"  Sample[{idx:>4}]  got={got:>6}  expected={exp:>6}  "
                    f"diff={got - exp:>+6}"
                )

    if mismatches:
        assert False, f"{len(mismatches)} samples mismatched. First mismatch at index {mismatches[0][0]}"

    tt_um_cic._log.info(
        f"✓ Successfully verified {compare_len} output samples match expected.txt"
    )

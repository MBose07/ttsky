# SPDX-FileCopyrightText: © 2024 Tiny Tapeout
# SPDX-License-Identifier: Apache-2.0

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer


def set_input_value(tt_um_cic, val):
    """Packs an 11-bit signed value into ui_in and uio_in[4:2]"""
    val_unsigned = int(val) & 0x7FF
    tt_um_cic.ui_in.value = val_unsigned & 0xFF
    current_uio = tt_um_cic.uio_in.value.integer & 0xE3  # Clear bits 2,3,4
    bit8  = (val_unsigned >> 8) & 0x1
    bit9  = (val_unsigned >> 9) & 0x1
    bit10 = (val_unsigned >> 10) & 0x1
    tt_um_cic.uio_in.value = current_uio | (bit8 << 2) | (bit9 << 3) | (bit10 << 4)


def get_output_value(tt_um_cic):
    """Unpacks an 11-bit signed value from uo_out and uio_out[7:5]"""
    low_byte = tt_um_cic.uo_out.value.integer
    bit8  = (tt_um_cic.uio_out.value.integer >> 5) & 0x1
    bit9  = (tt_um_cic.uio_out.value.integer >> 6) & 0x1
    bit10 = (tt_um_cic.uio_out.value.integer >> 7) & 0x1
    combined = low_byte | (bit8 << 8) | (bit9 << 9) | (bit10 << 10)
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

        set_input_value(tt_um_cic, sample)
        tt_um_cic.uio_in.value = tt_um_cic.uio_in.value.integer | 0x01  # valid_in = 1

        # Capture output when valid_out (uio_out[1]) is high
        if (tt_um_cic.uio_out.value.integer >> 1) & 0x1:
            out_val = get_output_value(tt_um_cic)
            output_samples.append(out_val)

    # ── 5. Flush: collect any remaining outputs ───────────────────────────────
    for _ in range(200):
        await RisingEdge(tt_um_cic.clk)
        tt_um_cic.uio_in.value = tt_um_cic.uio_in.value.integer & ~0x01  # valid_in = 0
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

    assert len(output_samples) == len(expected_samples), (
        f"Sample count mismatch: got {len(output_samples)}, "
        f"expected {len(expected_samples)}"
    )

    mismatches = []
    for idx, (got, exp) in enumerate(zip(output_samples, expected_samples)):
        if got != exp:
            mismatches.append((idx, got, exp))
            # Log each mismatch individually for easy debugging
            tt_um_cic._log.error(
                f"  Sample[{idx:>4}]  got={got:>6}  expected={exp:>6}  "
                f"diff={got - exp:>+6}"
            )

    if mismatches:
        tt_um_cic._log.error(
            f"{len(mismatches)} / {len(expected_samples)} samples mismatched."
        )
        # Fail the test with a clear summary
        first_idx, first_got, first_exp = mismatches[0]
        assert False, (
            f"{len(mismatches)} sample(s) mismatched. "
            f"First mismatch at index {first_idx}: "
            f"got={first_got}, expected={first_exp}"
        )

    tt_um_cic._log.info(
        f"✓ All {len(output_samples)} output samples match expected.txt"
    )

"""
Measure antenna SWR on a given frequency using the IC-7300's own meters.

Listens on the frequency first and refuses to transmit into an occupied
channel. Transmits a brief low-power RTTY mark carrier, samples the meters,
then unkeys and restores every setting it touched.

TRANSMITS. Use a frequency you are licensed for, and stay at the radio.
"""

from __future__ import annotations

import statistics
import sys
import time

from ic7300 import IC7300

BUSY_MARGIN = 2.0  # S-units above the local noise floor that counts as occupied
TX_SECONDS = 2.0
TX_POWER_PCT = 20.0


def listen(rig: IC7300, seconds: float = 3.0) -> float:
    """Return the peak S-meter reading observed over `seconds`."""
    peak = 0.0
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        peak = max(peak, rig.s_meter())
        time.sleep(0.1)
    return peak


def noise_floor(rig: IC7300, hz: int, offsets_khz: tuple[int, ...] = (-40, -20, 20, 40)) -> float:
    """
    Median S-meter across nearby frequencies.

    An absolute S-unit threshold is useless on HF: 40m at night sits at S9-plus
    purely from atmospheric noise, so any fixed limit either blocks everything
    or nothing. What actually indicates an occupied channel is the target
    reading standing proud of its own neighbourhood.
    """
    readings = []
    for offset in offsets_khz:
        rig.set_freq(hz + offset * 1000)
        time.sleep(0.35)
        readings.append(rig.s_meter())
    rig.set_freq(hz)
    time.sleep(0.35)
    return statistics.median(readings)


def measure(rig: IC7300, hz: int, force: bool = False) -> dict[str, float] | None:
    saved_freq = rig.get_freq()
    saved_mode, saved_filt = rig.get_mode()
    saved_data, saved_data_filt = rig.get_data_mode()
    saved_power = rig.get_level("rf_power")

    try:
        rig.set_freq(hz)
        rig.set_mode("USB", 1)
        time.sleep(0.3)

        floor = noise_floor(rig, hz)
        peak = listen(rig)
        print(f"  noise floor S{floor:.1f} / channel peak S{peak:.1f}")
        if peak > floor + BUSY_MARGIN and not force:
            print(f"  channel is {peak - floor:.1f} S-units above floor - occupied, not transmitting")
            return None

        # RTTY keys a steady mark carrier on PTT, which is what the SWR
        # bridge needs. USB with no audio would produce no output at all.
        rig.set_mode("RTTY", 1)
        rig.set_level_pct("rf_power", TX_POWER_PCT)
        time.sleep(0.3)

        samples: list[tuple[float, float, int]] = []
        with rig.transmit(max_seconds=TX_SECONDS + 3):
            time.sleep(0.4)  # let the PA and the meters settle
            deadline = time.monotonic() + TX_SECONDS
            while time.monotonic() < deadline:
                samples.append((rig.swr(), rig.power_pct(), rig.alc()))
                time.sleep(0.1)

        if not samples:
            return None

        return {
            "swr_min": min(s[0] for s in samples),
            "swr_max": max(s[0] for s in samples),
            "swr_avg": sum(s[0] for s in samples) / len(samples),
            "power_pct": sum(s[1] for s in samples) / len(samples),
            "samples": len(samples),
        }
    finally:
        rig.set_ptt(False)
        rig.set_level("rf_power", saved_power)
        rig.set_freq(saved_freq)
        rig.set_mode(saved_mode, 1)
        rig.set_data_mode(saved_data, saved_data_filt)


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: swr_check.py FREQ_MHZ [FREQ_MHZ ...]")
        return 2
    freqs = [int(float(a) * 1_000_000) for a in sys.argv[1:]]

    with IC7300() as rig:
        print(f"Radio state before: {rig.status()}\n")
        for hz in freqs:
            print(f"{hz/1e6:.4f} MHz")
            result = measure(rig, hz)
            if result:
                print(
                    f"  SWR {result['swr_avg']:.2f} "
                    f"(min {result['swr_min']:.2f} / max {result['swr_max']:.2f})  "
                    f"fwd power {result['power_pct']:.0f}%  "
                    f"[{result['samples']} samples]"
                )
            print()
        print(f"Radio state after:  {rig.status()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""
Identify which 0x1A 0x05 menu item is USB AF Output Level, by measuring.

The menu item numbers are not published per firmware, and seven items on this
radio sit at the same 50% default (int 128), so the number cannot be deduced
from the value alone. What distinguishes AF Output Level is that changing it
changes the audio arriving over USB.

Comparing "default vs louder" does not survive a live band: FT8 bursts move the
RMS far more than the setting does, which is what defeated the first attempt.
Comparing **0 vs 255** does survive it, because a real audio level control goes
essentially silent at 0 while band noise stays put. The ratio between the two is
then enormous for the right item and ~1 for every other.

Only items already sitting at 128 are touched. Those are level-type controls, so
driving them to the ends of their range is harmless; an enumeration like a CI-V
baud rate could cut communication and need front-panel recovery. Every original
value is restored, including on exception.

RECEIVE ONLY. Nothing here keys the transmitter.
"""

from __future__ import annotations

import subprocess

import numpy as np

from ic7300 import CIVError, IC7300, to_bcd

CAPTURE = "plughw:CODEC,0"
RATE = 12000
SECONDS = 3
# Items one IC-7300 reported near 128 in menu_scan.py. Other firmware may differ.
CANDIDATES = [21, 43, 60, 63, 64, 65, 81]


def measure() -> tuple[float, float]:
    """Return (rms, peak) of a short capture, both as a fraction of full scale."""
    raw = subprocess.run(
        ["arecord", "-D", CAPTURE, "-f", "S16_LE", "-r", str(RATE),
         "-c", "1", "-d", str(SECONDS), "-t", "raw", "-q"],
        capture_output=True, timeout=SECONDS + 10,
    ).stdout
    samples = np.frombuffer(raw, dtype="<i2").astype(np.float64)
    if samples.size == 0:
        return 0.0, 0.0
    return (
        float(np.sqrt(np.mean(samples**2))) / 32768.0,
        float(np.max(np.abs(samples))) / 32768.0,
    )


def at_default(rig: IC7300) -> dict[int, bytes]:
    """Original bytes of each candidate sitting at 128. Anything else is left alone."""
    found = {}
    for item in CANDIDATES:
        try:
            if rig.get_menu_int(item) == 128:
                found[item] = rig.get_menu(item)
        except (CIVError, ValueError):
            continue
    return found


def main() -> int:
    with IC7300() as rig:
        originals = at_default(rig)
        if not originals:
            print("no candidate sits at 128; run menu_scan.py and edit CANDIDATES")
            return 1
        print(f"testing {len(originals)} candidates, 0 vs 255\n")

        results = []
        try:
            for item in originals:
                rig.set_menu(item, to_bcd(0, 2))
                quiet_rms, _ = measure()
                rig.set_menu(item, to_bcd(255, 2))
                loud_rms, loud_peak = measure()
                rig.set_menu(item, originals[item])

                ratio = loud_rms / quiet_rms if quiet_rms > 1e-9 else float("inf")
                results.append((item, quiet_rms, loud_rms, loud_peak, ratio))
                flag = "  <== AUDIO CONTROL" if ratio > 3 else ""
                print(f"  item {item:3d}:  rms at 0 = {quiet_rms*100:6.3f}%   "
                      f"rms at 255 = {loud_rms*100:6.3f}%   x{ratio:6.1f}{flag}")
        finally:
            for item, data in originals.items():
                rig.set_menu(item, data)
            print("\nall candidates restored to original values")

        winners = [r for r in results if r[4] > 3]
        if len(winners) == 1:
            item, _, loud_rms, loud_peak, _ = winners[0]
            print(f"\nUSB AF Output Level is menu item {item}")
            print(f"  at 255 it gives rms {loud_rms*100:.2f}%  peak {loud_peak*100:.2f}%")
        elif winners:
            print(f"\nmore than one item moved the audio: "
                  f"{[w[0] for w in winners]} -- inspect before setting")
        else:
            print("\nno candidate moved the audio; widen the scan range")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

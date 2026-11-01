"""
Closed-loop calibration of transmit audio drive against the IC-7300's own
ALC meter.

Digital modes want ZERO ALC action. Any ALC deflection means the audio is
driving the transmitter into compression, which distorts the waveform. The
far end still hears a signal -- it just can't decode it, so it never replies
and the connection times out with no useful error anywhere.

Setting this by ear is guesswork. Instead we sweep the soundcard's PCM level,
transmit ardopcf's two-tone test at each step, and read the ALC meter back off
the radio. The right level is the highest one that still produces no ALC.

Nothing here needs the operator to touch the radio.

TRANSMITS on whatever frequency and power the radio is set to, with no check
that the channel is clear, and needs ardopcf running on port 8515. Use a clear
frequency or a dummy load, and stay at the radio. Nothing keys until you pass
--transmit.

usage: calibrate_drive.py --transmit [level ...]
"""

from __future__ import annotations

import re
import socket
import subprocess
import sys
import time

from tx_monitor import Rigctld

CARD = "CODEC"
CONTROL = "PCM"
MIXER_MAX = 128

# The IC-7300 reports ALC 0..255 raw; hamlib normalises to 0..1. Icom puts the
# top of the acceptable zone at raw 120 (~0.47). For data modes we want the
# needle not to move at all, so we aim well below that.
ALC_SILENT = 0.02
ALC_ICOM_MAX = 0.47

TX_SECONDS = 3.5
COOLDOWN = 2.5


def set_mixer(level: int) -> None:
    subprocess.run(
        ["amixer", "-c", CARD, "sset", CONTROL, str(level)],
        capture_output=True,
        check=True,
    )


def get_mixer() -> int:
    out = subprocess.run(
        ["amixer", "-c", CARD, "sget", CONTROL], capture_output=True, text=True
    ).stdout
    # Lines look like:  Front Left: Playback 105 [82%] [-23.00dB] [on]
    match = re.search(r"Playback (\d+) \[", out)
    if not match:
        raise RuntimeError(f"could not read mixer level from:\n{out}")
    return int(match.group(1))


def measure(rig: Rigctld, ardop: socket.socket) -> tuple[float, float]:
    """Transmit a two-tone burst; return (peak ALC, peak forward power)."""
    peak_alc = peak_pwr = 0.0
    rig.set_ptt(True)
    try:
        ardop.sendall(b"TWOTONETEST\r")
        time.sleep(0.5)  # let the PA settle before believing the meters
        deadline = time.monotonic() + TX_SECONDS
        while time.monotonic() < deadline:
            alc = rig.level("ALC")
            pwr = rig.level("RFPOWER_METER")
            if alc is not None:
                peak_alc = max(peak_alc, alc)
            if pwr is not None:
                peak_pwr = max(peak_pwr, pwr)
            time.sleep(0.1)
    finally:
        rig.set_ptt(False)
    return peak_alc, peak_pwr


def main() -> int:
    args = sys.argv[1:]
    if "--transmit" not in args:
        print(__doc__)
        return 2
    levels = [int(a) for a in args if a != "--transmit"] or [105, 90, 78, 66, 54, 42, 30, 20]

    rig = Rigctld()
    ardop = socket.create_connection(("localhost", 8515), timeout=5)
    ardop.settimeout(0.5)
    original = get_mixer()
    results: list[tuple[int, float, float]] = []

    print(f"starting mixer level: {original}/{MIXER_MAX} ({original*100//MIXER_MAX}%)")
    print(f"{'level':>6} {'pct':>5} {'ALC':>6} {'power':>6}  verdict")

    try:
        for level in levels:
            set_mixer(level)
            time.sleep(0.3)
            alc, pwr = measure(rig, ardop)
            results.append((level, alc, pwr))

            if alc <= ALC_SILENT:
                verdict = "clean - no ALC action"
            elif alc <= ALC_ICOM_MAX:
                verdict = "some ALC - still compressing"
            else:
                verdict = "OVERDRIVEN"
            print(f"{level:>6} {level*100//MIXER_MAX:>4}% {alc:>6.2f} {pwr:>6.2f}  {verdict}")
            time.sleep(COOLDOWN)
    finally:
        rig.set_ptt(False)
        try:
            ardop.close()
        except OSError:
            pass

    clean = [(lv, alc, pwr) for lv, alc, pwr in results if alc <= ALC_SILENT and pwr > 0.01]
    print()
    if clean:
        best = max(clean, key=lambda r: r[0])
        print(f"RECOMMENDED: mixer level {best[0]} ({best[0]*100//MIXER_MAX}%) "
              f"- ALC {best[1]:.2f}, power {best[2]:.2f}")
        set_mixer(best[0])
        print(f"mixer set to {get_mixer()}")
    else:
        print("No level produced zero ALC. Restoring original and reporting raw data.")
        set_mixer(original)

    rig.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

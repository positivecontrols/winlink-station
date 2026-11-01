#!/usr/bin/env python3
"""Force the QMX into USB mode before ARDOP is brought up.

ARDOP-over-soundcard requires the radio in a standard SSB mode so its
multi-tone audio gets linearly mixed as real sidebands. Found 2026-09-06:
the QMX was sitting in FSK mode (direct carrier-shift keying, not audio
mixing) -- PTT keyed fine and put out strong real RF, but frame decode was
consistently garbage (SNR ~-13 to -15 dB) at the receiving end. Setting it
to USB fixed decode SNR to +8 to +12 dB and let a real Winlink message
complete end to end.

Run this BEFORE rigctld grabs the serial port (start_pat_qmx.sh calls it
first) -- qmx.py's direct CAT connection and rigctld can't both hold
/dev/qmx at once.

Exits 0 on success. Exits nonzero (but doesn't raise a scary traceback) if
the radio isn't reachable, so a startup script can decide whether that's
fatal.
"""
import sys

from qmx import QMX, CATError

try:
    with QMX() as r:
        before = r.get_mode()
        if before != "USB":
            r.set_mode(2)  # USB
            import time
            time.sleep(0.3)
            after = r.get_mode()
        else:
            after = before
    print(f"QMX mode: {before} -> {after}")
    sys.exit(0 if after == "USB" else 1)
except (CATError, OSError) as e:
    print(f"set_usb_mode: could not reach QMX ({e}) -- is it plugged in?", file=sys.stderr)
    sys.exit(1)

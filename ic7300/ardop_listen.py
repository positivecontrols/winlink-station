"""
Attach to ardopcf's host port and print its asynchronous status messages.

Audio reaching ALSA (see rx_check.py) does not prove it reaches the *modem*.
ardopcf reports channel activity to
its host as asynchronous `BUSY TRUE`/`BUSY FALSE` lines, driven by its own
receive DSP -- so pointing the radio at a loud channel and watching this port
tests the modem's capture path end to end.

This issues no connect request, but LISTEN TRUE lets the modem answer if
another station calls your callsign, and answering transmits.

usage: MYCALL=N0CALL ardop_listen.py [seconds]
"""

from __future__ import annotations

import os
import socket
import sys
import time


def main() -> int:
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 40.0
    mycall = os.environ.get("MYCALL")
    if not mycall:
        print(__doc__)
        return 2

    sock = socket.create_connection(("localhost", 8515), timeout=5)
    sock.settimeout(1.0)
    # Ask for state we can sanity-check, then just listen.
    for cmd in ("VERSION", "PROTOCOLMODE", f"MYCALL {mycall}", "LISTEN TRUE"):
        sock.sendall((cmd + "\r").encode())
        time.sleep(0.2)

    print(f"listening to ardopcf host port for {seconds:.0f}s...\n")
    deadline = time.monotonic() + seconds
    buf = b""
    busy_true = 0
    lines = 0
    while time.monotonic() < deadline:
        try:
            chunk = sock.recv(4096)
        except socket.timeout:
            continue
        if not chunk:
            break
        buf += chunk
        while b"\r" in buf:
            line, _, buf = buf.partition(b"\r")
            text = line.decode("ascii", "replace").strip()
            if not text:
                continue
            lines += 1
            print(f"  [{time.strftime('%H:%M:%S')}] {text}")
            if text.upper().startswith("BUSY TRUE"):
                busy_true += 1
    sock.close()

    print()
    print(f"  status lines received : {lines}")
    print(f"  BUSY TRUE events      : {busy_true}")
    if busy_true:
        print("\nThe modem's receive DSP is seeing the channel. Capture path is good.")
    else:
        print("\nNo busy detections. On a channel known to be loud, that means the")
        print("modem is not getting usable audio even though ALSA and jt9 are fine.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

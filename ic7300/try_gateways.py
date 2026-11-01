"""
Call a list of Winlink ARDOP gateways in turn and report what each one did.

Calling a single gateway cannot distinguish "that station is off the air" from
"this station cannot reach anyone" -- and Winlink's gateway list is
self-reported, so stale entries are normal. Sweeping several nearby gateways
separates the two: one timeout is uninformative, five is a station problem.

Each attempt is bounded, and the modem's own log is checked afterwards for
whether anything was actually heard, since a timeout alone says nothing about
whether the receiver saw the other station.

TRANSMITS. The operator should be present and the antenna connected.

Each attempt stops after ATTEMPT_SECONDS, which can cut off a slow session that
did connect, so raise it for weak links.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time

LOG = "/tmp/ARDOPDebug8515_{}.log"
ATTEMPT_SECONDS = 110  # must exceed ardopcf's 90 s ARQ timeout, or we cut sessions short


def log_path() -> str:
    return LOG.format(time.strftime("%Y%m%d"))


def log_lines() -> int:
    """Current length of the modem log, used to bound each attempt."""
    try:
        with open(log_path()) as fh:
            return sum(1 for _ in fh)
    except OSError:
        return 0


def heard_anything(from_line: int) -> tuple[int, int]:
    """
    Return (frames decoded, connect-acks) from log lines added since `from_line`.

    Bounding by line offset rather than timestamp is deliberate: ardopcf stamps
    its log in UTC while these attempts are timed in local time, so comparing
    the two as strings silently matches the whole file.
    """
    try:
        with open(log_path()) as fh:
            recent = fh.read().splitlines()[from_line:]
    except OSError:
        return 0, 0
    decoded = sum(1 for l in recent if "Decode PASS" in l)
    conack = sum(1 for l in recent if re.search(r"ConAck\d*\s+Decode PASS", l))
    return decoded, conack


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: try_gateways.py CALL:FREQ [CALL:FREQ ...]")
        return 2

    bw = os.environ.get("ARDOP_BW", "2000MAX")
    results = []
    for spec in sys.argv[1:]:
        call, _, freq = spec.partition(":")
        mark = log_lines()
        url = f"ardop:///{call}?bw={bw}&freq={freq}"
        print(f"\n=== {call} on {freq} kHz ({bw}) ===", flush=True)

        proc = subprocess.run(
            ["timeout", str(ATTEMPT_SECONDS), "pat", "connect", url],
            capture_output=True, text=True,
        )
        out = (proc.stdout + proc.stderr).strip()
        for line in out.splitlines():
            print("   ", line, flush=True)

        connected = "Connected" in out or "100%" in out
        rx, conack = heard_anything(mark)
        results.append((call, freq, connected, rx, conack))
        print(f"    -> decoded {rx} frames, {conack} ConAck", flush=True)
        if connected:
            print(f"\n*** CONNECTED to {call} ***")
            break
        time.sleep(3)

    print("\n\n=== summary ===")
    for call, freq, connected, rx, conack in results:
        status = "CONNECTED" if connected else "timeout"
        print(f"  {call:10s} {freq:>8s} kHz  {status:10s}  decoded={rx} conack={conack}")

    if any(r[2] for r in results):
        return 0
    if any(r[4] for r in results):
        print("\nA gateway answered our call but the session did not complete.")
        print("Both directions work; the path is too weak to carry data frames.")
    else:
        print("\nNothing heard from any gateway. Either none are on the air, or")
        print("the receive path into the modem is not delivering usable audio.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

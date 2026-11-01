"""
Poll the IC-7300's transmit meters through rigctld while something else
(ardopcf, WSJT-X) owns the audio device.

The CI-V serial port can only have one owner, and during an ARDOP session that
owner is rigctld. This talks rigctld's TCP protocol instead, so we can watch
ALC, forward power and SWR live without fighting over the port.
"""

from __future__ import annotations

import socket
import sys
import time


class Rigctld:
    def __init__(self, host: str = "localhost", port: int = 4532, timeout: float = 2.0) -> None:
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.fh = self.sock.makefile("rw", encoding="ascii", newline="\n")

    def level(self, name: str) -> float | None:
        try:
            self.fh.write(f"l {name}\n")
            self.fh.flush()
            line = self.fh.readline().strip()
            return float(line)
        except (ValueError, OSError):
            return None

    def set_ptt(self, on: bool) -> None:
        self.fh.write(f"T {1 if on else 0}\n")
        self.fh.flush()
        self.fh.readline()  # consume RPRT

    def get_ptt(self) -> bool:
        self.fh.write("t\n")
        self.fh.flush()
        return self.fh.readline().strip() == "1"

    def close(self) -> None:
        self.fh.close()
        self.sock.close()


def main() -> int:
    duration = float(sys.argv[1]) if len(sys.argv) > 1 else 60.0
    interval = 0.2

    rig = Rigctld()
    peak_pwr = peak_alc = 0.0
    worst_swr = 1.0
    tx_samples = 0
    total = 0
    started = time.monotonic()

    print(f"monitoring for {duration:.0f}s (power / alc / swr)")
    try:
        while time.monotonic() - started < duration:
            pwr = rig.level("RFPOWER_METER")
            alc = rig.level("ALC")
            swr = rig.level("SWR")
            total += 1
            if pwr and pwr > 0.01:
                tx_samples += 1
                peak_pwr = max(peak_pwr, pwr)
                peak_alc = max(peak_alc, alc or 0.0)
                worst_swr = max(worst_swr, swr or 1.0)
                print(
                    f"  t+{time.monotonic()-started:5.1f}s  TX  "
                    f"pwr {pwr:5.2f}  alc {alc or 0:5.2f}  swr {swr or 0:4.2f}"
                )
            time.sleep(interval)
    except KeyboardInterrupt:
        pass
    finally:
        rig.close()

    print()
    print(f"  samples total     : {total}")
    print(f"  samples with RF   : {tx_samples}")
    if tx_samples:
        print(f"  peak fwd power    : {peak_pwr:.2f}")
        print(f"  peak ALC          : {peak_alc:.2f}")
        print(f"  worst SWR         : {worst_swr:.2f}")
    else:
        print("  NO RF DETECTED - the radio never keyed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

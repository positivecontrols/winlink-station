"""
Scan the 0x1A 0x05 menu space and report which item numbers answer.

Icom does not publish the item numbers per firmware, and the numbering shifts
between models and revisions, so the only reliable way to find a setting is to
read the whole space once and then identify an item by changing it and watching
what moves. Items that don't exist return NAK (the library raises), so a clean
read is itself the evidence that an item is real.

RECEIVE ONLY. Nothing here keys the transmitter.
"""

from __future__ import annotations

import sys

from ic7300 import IC7300, from_bcd


def main() -> int:
    start = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    end = int(sys.argv[2]) if len(sys.argv) > 2 else 150

    found: list[tuple[int, bytes, int]] = []
    with IC7300() as rig:
        for item in range(start, end + 1):
            try:
                data = rig.get_menu(item)
            except Exception:
                continue
            if not data:
                continue
            try:
                value = from_bcd(data)
            except Exception:
                value = -1
            found.append((item, data, value))
            print(f"  item {item:3d}  raw {data.hex(' '):<12} int {value}")

    print()
    print(f"{len(found)} items answered in {start}..{end}")
    # USB AF Output Level defaults to 50% -> 128 on the 0..255 scale.
    near = [f for f in found if 100 <= f[2] <= 160]
    if near:
        print("\ncandidates sitting near a 50% default (int 100-160):")
        for item, data, value in near:
            print(f"  item {item:3d}  raw {data.hex(' '):<12} int {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

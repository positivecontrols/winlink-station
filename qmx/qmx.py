"""Minimal CAT control library for the QRP Labs QMX transceiver.

QMX speaks a subset of the Kenwood TS-480/TS-440 CAT protocol over a USB-CDC
virtual serial port (baud rate is irrelevant -- it's USB, not a real UART).
Commands are ASCII, terminated by ';', never by CR/LF (an incoming CR flips
the port to terminal/menu mode instead -- avoid sending one).

Reference: the QMX CAT manual from QRP Labs (firmware 1.04).

Firmware note: this library targets whatever firmware is actually on the
radio. Some commands (UI, OM, PS, AI, MD-set, BD/BN/BU, GP, SR) were added in
firmware 1.03/1.04 and return '?;' (unsupported) on older firmware -- check
.version() and don't assume a command exists just because it's documented.
"""

from __future__ import annotations
import time
from typing import Iterator

import serial


class CATError(Exception):
    pass


class QMX:
    def __init__(self, port: str = "/dev/qmx", baud: int = 38400, timeout: float = 2.0) -> None:
        self.ser = serial.Serial(port, baud, timeout=0.2)
        self.timeout = timeout
        time.sleep(0.2)
        self.ser.reset_input_buffer()

    def close(self) -> None:
        self.ser.close()

    def __enter__(self) -> "QMX":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- transport --

    def send(self, cmd: str) -> None:
        """Fire-and-forget: most two-letter CAT *Set* forms (e.g. FA, MD, TX)
        follow standard Kenwood convention and send NO reply at all -- only
        the bare Get/query form (no parameter) replies. Confirmed empirically
        on this firmware: 'FA00007290000;' gets zero bytes back, 'FA;' gets
        'FA00007290000;'. Waiting for a reply after a Set will time out even
        though the command succeeded -- use this for all Set-type sends."""
        self.ser.reset_input_buffer()
        self.ser.write((cmd + ";").encode("ascii"))
        time.sleep(0.05)  # let the radio actually act on it before returning

    def transact(self, cmd: str) -> str:
        """Send one command (without trailing ';') and return the reply body
        (without the leading echoed command or trailing ';'). Use only for
        Get/query forms and other commands documented to reply -- see send()
        for Set-type commands that don't. Raises CATError on '?;' (QMX's
        generic error response) or a timeout."""
        self.ser.reset_input_buffer()
        self.ser.write((cmd + ";").encode("ascii"))
        deadline = time.monotonic() + self.timeout
        buf = b""
        while time.monotonic() < deadline:
            chunk = self.ser.read(256)
            if chunk:
                buf += chunk
                if b";" in buf:
                    break
        if not buf.endswith(b";"):
            raise CATError(f"timeout waiting for reply to {cmd!r}, got {buf!r}")
        reply = buf.decode("ascii", errors="replace").rstrip(";")
        if reply == "?":
            raise CATError(f"QMX rejected command {cmd!r} (unsupported or bad param)")
        return reply

    # -- frequency / mode --

    def get_freq_a(self) -> int:
        return int(self.transact("FA")[2:])

    def set_freq_a(self, hz: int) -> None:
        self.send(f"FA{hz:011d}")

    def get_freq_b(self) -> int:
        return int(self.transact("FB")[2:])

    def set_freq_b(self, hz: int) -> None:
        self.send(f"FB{hz:011d}")

    MODES = {1: "LSB", 2: "USB", 3: "CW", 5: "AM", 6: "FSK", 7: "CWR", 8: "SWR", 9: "FSK-R"}

    def get_mode(self) -> str:
        return self.MODES.get(int(self.transact("MD")[2:]), "?")

    def set_mode(self, mode_num: int) -> None:
        """1=LSB 2=USB 3=CW 5=AM 6=FSK 7=CWR 8=SWR-tune 9=FSK-reverse.
        Requires firmware >= 1.04_001; older firmware rejects the Set form."""
        self.send(f"MD{mode_num}")

    # -- levels / meters --

    def get_power_out_w(self) -> float:
        """TX output power in watts, from the last transmission (Get only)."""
        return int(self.transact("PC")[2:]) / 10.0

    def get_rf_gain_db(self) -> int:
        return int(self.transact("RG")[2:])

    def set_rf_gain_db(self, db: int) -> None:
        """RF gain / TX drive for the CURRENT band, in dB. Same value shown
        in the Band config. table's 'RF gain (dB)' column -- this is the
        closest QMX equivalent to the IC-7300's RF power level."""
        self.send(f"RG{db:03d}")

    def get_swr(self) -> float:
        """SWR ratio (e.g. 1.21). Returns None while in Receive."""
        r = self.transact("SW")
        digits = r[2:]
        return int(digits) / 100.0 if digits else None

    def get_s_meter_db(self) -> int:
        return int(self.transact("SM")[2:])

    def get_agc_db(self) -> int:
        return int(self.transact("SA")[2:])

    # -- TX/RX --

    def set_tx(self, on: bool) -> None:
        self.send("TX" if on else "RX")

    def get_tx(self) -> bool:
        return self.transact("TQ")[2:] == "1"

    def transmit(self, max_seconds: float = 10.0) -> Iterator["QMX"]:
        """Context manager: key up, yield, always unkey -- mirrors ic7300.py's
        pattern. Caller is responsible for actually feeding audio/CW."""
        import contextlib

        @contextlib.contextmanager
        def _cm():
            self.set_tx(True)
            start = time.monotonic()
            try:
                yield self
            finally:
                self.set_tx(False)
                if time.monotonic() - start > max_seconds:
                    raise CATError(f"transmit held open longer than {max_seconds}s")

        return _cm()

    # -- misc --

    def version(self) -> str:
        return self.transact("VN")[2:]

    SSB_SOURCES = {0: "USB", 1: "internal_two_tone_test", 2: "external_mic"}

    def get_ssb_source(self) -> str:
        return self.SSB_SOURCES.get(int(self.transact("SS")[2:]), "?")

    def set_ssb_source(self, source: int) -> None:
        """0=USB audio from host PC (required for ARDOP/WSJT-X/any digital
        mode driven from this Pi), 1=internal two-tone test, 2=external mic.
        Both this AND mode must be right for TX audio to actually reach the
        transmitter -- confirmed on real hardware: mode=USB with this left on
        2 (external mic) produces a normal-looking keyed TX with no useful
        modulation, same failure signature as the IC-7300's LSB/Data-OFF bug."""
        self.send(f"SS{source}")

    def get_lcd(self) -> str:
        """32 raw characters of the physical LCD (icons render as spaces)."""
        return self.transact("LC")[2:]

    def get_unique_id(self) -> str:
        """96-bit per-unit ID. Requires firmware >= 1.04_003."""
        return self.transact("UI")[2:]

    # -- Menu Manager (MM/ML) -- full config-tree read/write, the QMX
    # equivalent of the IC-7300's CI-V menu system, but self-describing.

    def mm_query(self, path: str) -> str:
        """Discovery form: MM<path>?; -> 'type|len_or_listtype|name' (MM
        echo prefix already stripped)."""
        return self.transact(f"MM{path}?")[2:]

    def mm_get(self, path: str) -> str:
        return self.transact(f"MM{path}")[2:]

    def mm_set(self, path: str, value: str) -> None:
        """Persists to EEPROM immediately (unlike the two-letter CAT commands,
        which are session-only). Untested whether this Set form replies --
        treated as fire-and-forget like every other Set command on this
        firmware; switch to transact() if a real reply is ever observed."""
        self.send(f"MM{path}={value}")

    def ml_list_values(self, list_type: int) -> list[str]:
        """ML<n>; -> pipe-delimited list of valid values for List-type menu #n."""
        return self.transact(f"ML{list_type}").split("|")

    def reload_config(self) -> None:
        """MU; -- force the radio to reload config after MM Set commands,
        if 'MM Effect' is set to 'On demand' rather than 'Immediate'."""
        self.send("MU")

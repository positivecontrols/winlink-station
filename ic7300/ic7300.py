"""
CI-V control library for the Icom IC-7300.

The IC-7300's USB port is a Silicon Labs CP2102 UART bridge. There is no
"IC-7300 driver" to write -- the kernel's cp210x module already gives us a
serial port, and behind that port the radio speaks CI-V, Icom's control
protocol. This module speaks CI-V thoroughly enough to read and set anything
the radio exposes, including most of the front-panel menu system.

Frame format:

    FE FE <to> <from> <cmd> [subcmd] [data...] FD

Two things bite naive implementations, and this module handles both:

1.  ECHO. By default the IC-7300 echoes every frame we send straight back at
    us before replying. A parser that grabs "the first frame that arrives"
    reads its own command back and decodes garbage. We filter on the address
    fields instead of trusting arrival order.

2.  TRANSCEIVE. If CI-V Transceive is enabled, the radio spontaneously emits
    frames addressed to 0x00 (broadcast) whenever the operator touches a
    control. Those can land in the middle of a transaction. We skip anything
    not addressed to us.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Iterator

import serial

# --- protocol constants ------------------------------------------------------

PREAMBLE = 0xFE
END = 0xFD
OK = 0xFB
NG = 0xFA

DEFAULT_RADIO_ADDR = 0x94  # IC-7300 factory default CI-V address
DEFAULT_CTRL_ADDR = 0xE0  # conventional address for the controlling computer

# Commands
CMD_READ_FREQ = 0x03
CMD_READ_MODE = 0x04
CMD_SET_FREQ = 0x05
CMD_SET_MODE = 0x06
CMD_LEVEL = 0x14
CMD_METER = 0x15
CMD_SWITCH = 0x16
CMD_MENU = 0x1A
CMD_PTT = 0x1C

# 0x14 sub-commands: analogue levels, all scaled 0..255
LEVELS = {
    "af": 0x01,
    "rf_gain": 0x02,
    "squelch": 0x03,
    "nr": 0x06,
    "pbt_inner": 0x07,
    "pbt_outer": 0x08,
    "cw_pitch": 0x09,
    "rf_power": 0x0A,
    "mic_gain": 0x0B,
    "key_speed": 0x0C,
    "notch": 0x0D,
    "comp": 0x0E,
    "break_in_delay": 0x0F,
    "nb": 0x12,
    "monitor": 0x15,
    "vox_gain": 0x16,
    "anti_vox": 0x17,
}

# 0x15 sub-commands: meters, all returned as 0..255
METERS = {
    "s": 0x02,
    "power": 0x11,
    "swr": 0x12,
    "alc": 0x13,
    "comp": 0x14,
    "vd": 0x15,
    "id": 0x16,
}

# 0x16 sub-commands: on/off and enumerated switches
SWITCHES = {
    "preamp": 0x02,
    "agc": 0x12,
    "nb": 0x22,
    "nr": 0x40,
    "auto_notch": 0x41,
    "repeater_tone": 0x42,
    "tsql": 0x43,
    "comp": 0x44,
    "monitor": 0x45,
    "vox": 0x46,
    "break_in": 0x47,
    "manual_notch": 0x48,
    "dial_lock": 0x50,
}

MODES = {
    0x00: "LSB",
    0x01: "USB",
    0x02: "AM",
    0x03: "CW",
    0x04: "RTTY",
    0x05: "FM",
    0x07: "CW-R",
    0x08: "RTTY-R",
}
MODES_REV = {v: k for k, v in MODES.items()}

FILTERS = {1: "FIL1", 2: "FIL2", 3: "FIL3"}

# Icom's published calibration points for the meter scales. Values between
# points are linearly interpolated; this is how the front panel reads them.
_SWR_CURVE = [(0, 1.0), (48, 1.5), (80, 2.0), (120, 3.0), (255, 10.0)]
_POWER_CURVE = [(0, 0.0), (143, 50.0), (213, 100.0), (255, 120.0)]
_S_CURVE = [(0, 0.0), (120, 9.0), (241, 15.0)]  # 15 == S9+60dB


class CIVError(Exception):
    """The radio rejected a command, or returned something unparseable."""


# --- BCD helpers -------------------------------------------------------------


def to_bcd(value: int, num_bytes: int, little_endian: bool = False) -> bytes:
    """Encode an integer as packed BCD."""
    digits = str(value).rjust(num_bytes * 2, "0")
    if len(digits) > num_bytes * 2:
        raise ValueError(f"{value} does not fit in {num_bytes} BCD bytes")
    out = bytes(
        (int(digits[i]) << 4) | int(digits[i + 1])
        for i in range(0, len(digits), 2)
    )
    return out[::-1] if little_endian else out


def from_bcd(data: bytes, little_endian: bool = False) -> int:
    """Decode packed BCD into an integer."""
    raw = data[::-1] if little_endian else data
    digits = "".join(f"{(b >> 4) & 0x0F}{b & 0x0F}" for b in raw)
    return int(digits)


def _interp(curve: list[tuple[int, float]], raw: int) -> float:
    """Linear interpolation across a meter calibration curve."""
    if raw <= curve[0][0]:
        return curve[0][1]
    for (x0, y0), (x1, y1) in zip(curve, curve[1:]):
        if raw <= x1:
            span = x1 - x0
            return y0 if span == 0 else y0 + (y1 - y0) * (raw - x0) / span
    return curve[-1][1]


# --- the radio ---------------------------------------------------------------


class IC7300:
    def __init__(
        self,
        port: str = "/dev/ic7300",
        baud: int = 115200,
        radio_addr: int = DEFAULT_RADIO_ADDR,
        ctrl_addr: int = DEFAULT_CTRL_ADDR,
        timeout: float = 1.0,
    ) -> None:
        self.radio_addr = radio_addr
        self.ctrl_addr = ctrl_addr
        self.ser = serial.Serial(port, baud, timeout=0.1)
        self.timeout = timeout
        time.sleep(0.15)
        self.ser.reset_input_buffer()

    def close(self) -> None:
        self.ser.close()

    def __enter__(self) -> "IC7300":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- framing --

    def _frames(self, deadline: float) -> Iterator[bytes]:
        """Yield complete CI-V frames until the deadline passes."""
        buf = bytearray()
        while time.monotonic() < deadline:
            chunk = self.ser.read(64)
            if chunk:
                buf.extend(chunk)
            while END in buf:
                idx = buf.index(END)
                frame, buf = bytes(buf[: idx + 1]), bytearray(buf[idx + 1 :])
                # A valid frame starts with the two-byte preamble.
                start = frame.find(bytes([PREAMBLE, PREAMBLE]))
                if start >= 0 and len(frame) - start >= 5:
                    yield frame[start:]
            if not chunk:
                time.sleep(0.005)

    def transact(self, payload: bytes, expect_reply: bool = True) -> bytes:
        """
        Send a CI-V payload (command + subcommand + data) and return the data
        portion of the radio's reply.

        Echoed copies of our own frame and broadcast Transceive frames are
        discarded; only a frame addressed to us from the radio is accepted.
        """
        frame = bytes([PREAMBLE, PREAMBLE, self.radio_addr, self.ctrl_addr]) + payload + bytes([END])
        self.ser.reset_input_buffer()
        self.ser.write(frame)
        self.ser.flush()

        if not expect_reply:
            return b""

        deadline = time.monotonic() + self.timeout
        for reply in self._frames(deadline):
            to_addr, from_addr = reply[2], reply[3]
            # Our own echo comes back addressed TO the radio; skip it.
            if to_addr != self.ctrl_addr or from_addr != self.radio_addr:
                continue
            body = reply[4:-1]
            if not body:
                continue
            if body[0] == NG:
                raise CIVError(f"radio rejected command {payload.hex(' ')}")
            if body[0] == OK:
                return b""
            # Strip the echoed command/subcommand bytes off the front.
            n = len(payload)
            return body[n:] if body[:n] == payload else body[1:]

        raise CIVError(f"no reply to {payload.hex(' ')} within {self.timeout}s")

    # -- frequency and mode --

    def get_freq(self) -> int:
        """Operating frequency in Hz."""
        return from_bcd(self.transact(bytes([CMD_READ_FREQ])), little_endian=True)

    def set_freq(self, hz: int) -> None:
        self.transact(bytes([CMD_SET_FREQ]) + to_bcd(hz, 5, little_endian=True))

    def get_mode(self) -> tuple[str, str]:
        """Returns (mode, filter), e.g. ("USB", "FIL1")."""
        data = self.transact(bytes([CMD_READ_MODE]))
        mode = MODES.get(data[0], f"0x{data[0]:02X}")
        filt = FILTERS.get(data[1], str(data[1])) if len(data) > 1 else "?"
        return mode, filt

    def set_mode(self, mode: str, filt: int = 1) -> None:
        if mode not in MODES_REV:
            raise ValueError(f"unknown mode {mode!r}; try {sorted(MODES_REV)}")
        self.transact(bytes([CMD_SET_MODE, MODES_REV[mode], filt]))

    def get_data_mode(self) -> tuple[bool, int]:
        """Returns (data_mode_on, filter). PKTUSB is USB with data mode on."""
        data = self.transact(bytes([CMD_MENU, 0x06]))
        return bool(data[0]), (data[1] if len(data) > 1 else 0)

    def set_data_mode(self, on: bool, filt: int = 1) -> None:
        self.transact(bytes([CMD_MENU, 0x06, 1 if on else 0, filt if on else 0]))

    # -- levels --

    def get_level(self, name: str) -> int:
        """Read an analogue level (0..255)."""
        if name not in LEVELS:
            raise ValueError(f"unknown level {name!r}; try {sorted(LEVELS)}")
        return from_bcd(self.transact(bytes([CMD_LEVEL, LEVELS[name]])))

    def set_level(self, name: str, value: int) -> None:
        if name not in LEVELS:
            raise ValueError(f"unknown level {name!r}; try {sorted(LEVELS)}")
        if not 0 <= value <= 255:
            raise ValueError("level must be 0..255")
        self.transact(bytes([CMD_LEVEL, LEVELS[name]]) + to_bcd(value, 2))

    def get_level_pct(self, name: str) -> float:
        return self.get_level(name) * 100.0 / 255.0

    def set_level_pct(self, name: str, pct: float) -> None:
        self.set_level(name, round(max(0.0, min(100.0, pct)) * 255 / 100))

    # -- meters --

    def get_meter(self, name: str) -> int:
        """Raw meter reading (0..255)."""
        if name not in METERS:
            raise ValueError(f"unknown meter {name!r}; try {sorted(METERS)}")
        return from_bcd(self.transact(bytes([CMD_METER, METERS[name]])))

    def swr(self) -> float:
        return _interp(_SWR_CURVE, self.get_meter("swr"))

    def power_pct(self) -> float:
        return _interp(_POWER_CURVE, self.get_meter("power"))

    def alc(self) -> int:
        """ALC as 0..255. Icom considers ~120 the top of the acceptable zone."""
        return self.get_meter("alc")

    def s_meter(self) -> float:
        """S-units; 9.0 means S9, 15.0 means S9+60dB."""
        return _interp(_S_CURVE, self.get_meter("s"))

    # -- switches --

    def get_switch(self, name: str) -> int:
        if name not in SWITCHES:
            raise ValueError(f"unknown switch {name!r}; try {sorted(SWITCHES)}")
        return self.transact(bytes([CMD_SWITCH, SWITCHES[name]]))[0]

    def set_switch(self, name: str, value: int) -> None:
        if name not in SWITCHES:
            raise ValueError(f"unknown switch {name!r}; try {sorted(SWITCHES)}")
        self.transact(bytes([CMD_SWITCH, SWITCHES[name], value]))

    # -- the menu system --

    def get_menu(self, item: int) -> bytes:
        """
        Read a front-panel menu item via 0x1A 0x05.

        `item` is the decimal item number as it appears in Icom's CI-V
        reference (e.g. 71). Returns the raw data bytes, since different items
        carry different widths and encodings.
        """
        return self.transact(bytes([CMD_MENU, 0x05]) + to_bcd(item, 2))

    def set_menu(self, item: int, data: bytes) -> None:
        self.transact(bytes([CMD_MENU, 0x05]) + to_bcd(item, 2) + data)

    def get_menu_int(self, item: int) -> int:
        return from_bcd(self.get_menu(item))

    def set_menu_int(self, item: int, value: int, width: int = 2) -> None:
        self.set_menu(item, to_bcd(value, width))

    # -- transmit --

    def get_ptt(self) -> bool:
        return bool(self.transact(bytes([CMD_PTT, 0x00]))[0])

    def set_ptt(self, on: bool) -> None:
        self.transact(bytes([CMD_PTT, 0x00, 1 if on else 0]))

    @contextmanager
    def transmit(self, max_seconds: float = 10.0) -> Iterator["IC7300"]:
        """
        Key the transmitter, guaranteeing unkey on exit -- including on
        exception or Ctrl-C. `max_seconds` is a sanity bound, not a timer:
        it is checked on exit and reported, so a runaway block is visible.
        """
        started = time.monotonic()
        self.set_ptt(True)
        try:
            yield self
        finally:
            self.set_ptt(False)
            held = time.monotonic() - started
            if held > max_seconds:
                print(f"WARNING: transmitted for {held:.1f}s (limit {max_seconds}s)")

    # -- convenience --

    def status(self) -> dict[str, object]:
        mode, filt = self.get_mode()
        data_on, data_filt = self.get_data_mode()
        return {
            "freq_hz": self.get_freq(),
            "mode": mode,
            "filter": filt,
            "data_mode": data_on,
            "rf_power_pct": round(self.get_level_pct("rf_power"), 1),
            "mic_gain_pct": round(self.get_level_pct("mic_gain"), 1),
            "s_meter": round(self.s_meter(), 1),
        }


if __name__ == "__main__":
    with IC7300() as rig:
        for key, value in rig.status().items():
            print(f"{key:>16}: {value}")

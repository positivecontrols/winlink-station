"""Offline tests for ic7300.py. A fake serial port replays frames, so no radio is needed."""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ic7300"))

import ic7300
from ic7300 import CIVError, IC7300, from_bcd, to_bcd

RADIO = 0x94
HOST = 0xE0


def frame(to: int, sender: int, *body: int) -> bytes:
    return bytes([0xFE, 0xFE, to, sender, *body, 0xFD])


OK_REPLY = frame(HOST, RADIO, 0xFB)


class FakeSerial:
    def __init__(self, *args: object, **kwargs: object) -> None:
        self.rx = bytearray()
        self.written: list[bytes] = []
        self.replies: list[bytes] = []  # one per write, as a real radio answers

    def read(self, n: int) -> bytes:
        chunk = bytes(self.rx[:n])
        del self.rx[:n]
        return chunk

    def write(self, data: bytes) -> None:
        self.written.append(bytes(data))
        if self.replies:
            self.rx += self.replies.pop(0)

    def flush(self) -> None:
        pass

    def reset_input_buffer(self) -> None:
        pass

    def close(self) -> None:
        pass


class BcdTests(unittest.TestCase):
    def test_frequency_is_little_endian(self) -> None:
        self.assertEqual(to_bcd(7_100_200, 5, little_endian=True).hex(), "0002100700")

    def test_round_trip(self) -> None:
        for value in (0, 7, 128, 255, 14_100_000):
            self.assertEqual(from_bcd(to_bcd(value, 5)), value)

    def test_value_too_large_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            to_bcd(1000, 1)


class RadioTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = mock.patch.object(ic7300.serial, "Serial", FakeSerial)
        patcher.start()
        self.addCleanup(patcher.stop)
        # The port name can't reach a radio even if the patch ever failed.
        self.rig = IC7300(port="fake", timeout=0.05)

    def test_skips_its_own_echo(self) -> None:
        self.rig.ser.rx += frame(RADIO, HOST, 0x03)
        self.rig.ser.rx += frame(HOST, RADIO, 0x03, 0x00, 0x02, 0x10, 0x07, 0x00)
        self.assertEqual(self.rig.get_freq(), 7_100_200)

    def test_skips_transceive_broadcasts(self) -> None:
        self.rig.ser.rx += frame(0x00, RADIO, 0x00, 0x00, 0x00, 0x10, 0x14, 0x00)
        self.rig.ser.rx += frame(HOST, RADIO, 0x03, 0x00, 0x02, 0x10, 0x07, 0x00)
        self.assertEqual(self.rig.get_freq(), 7_100_200)

    def test_rejected_command_raises(self) -> None:
        self.rig.ser.rx += frame(HOST, RADIO, 0xFA)
        with self.assertRaises(CIVError):
            self.rig.get_freq()

    def test_silence_raises(self) -> None:
        with self.assertRaises(CIVError):
            self.rig.get_freq()

    def test_set_freq_sends_the_right_frame(self) -> None:
        self.rig.ser.rx += OK_REPLY
        self.rig.set_freq(7_100_200)
        self.assertEqual(
            self.rig.ser.written[-1],
            frame(RADIO, HOST, 0x05, 0x00, 0x02, 0x10, 0x07, 0x00),
        )

    def test_transmit_unkeys_after_an_exception(self) -> None:
        self.rig.ser.replies = [OK_REPLY, OK_REPLY]
        with self.assertRaises(RuntimeError):
            with self.rig.transmit():
                raise RuntimeError("boom")
        self.assertEqual(self.rig.ser.written[0], frame(RADIO, HOST, 0x1C, 0x00, 0x01))
        self.assertEqual(self.rig.ser.written[-1], frame(RADIO, HOST, 0x1C, 0x00, 0x00))

    def test_level_range_is_checked_before_sending(self) -> None:
        with self.assertRaises(ValueError):
            self.rig.set_level("rf_power", 256)
        self.assertEqual(self.rig.ser.written, [])


if __name__ == "__main__":
    unittest.main()

"""Offline tests for qmx.py. A fake serial port replays replies, so no radio is needed."""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "qmx"))

import qmx
from qmx import CATError, QMX


class FakeSerial:
    def __init__(self, *args: object, **kwargs: object) -> None:
        self.rx = bytearray()
        self.written: list[bytes] = []

    def read(self, n: int) -> bytes:
        chunk = bytes(self.rx[:n])
        del self.rx[:n]
        return chunk

    def write(self, data: bytes) -> None:
        self.written.append(bytes(data))

    def reset_input_buffer(self) -> None:
        pass

    def close(self) -> None:
        pass


class QmxTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = mock.patch.object(qmx.serial, "Serial", FakeSerial)
        patcher.start()
        self.addCleanup(patcher.stop)
        # The port name can't reach a radio even if the patch ever failed.
        self.radio = QMX(port="fake", timeout=0.05)

    def test_reads_frequency(self) -> None:
        self.radio.ser.rx += b"FA00007290000;"
        self.assertEqual(self.radio.get_freq_a(), 7_290_000)

    def test_set_frequency_waits_for_no_reply(self) -> None:
        self.radio.set_freq_a(7_290_000)
        self.assertEqual(self.radio.ser.written, [b"FA00007290000;"])

    def test_unsupported_command_raises(self) -> None:
        self.radio.ser.rx += b"?;"
        with self.assertRaises(CATError):
            self.radio.version()

    def test_silence_raises(self) -> None:
        with self.assertRaises(CATError):
            self.radio.version()

    def test_never_sends_a_carriage_return(self) -> None:
        self.radio.set_freq_a(7_290_000)
        self.radio.set_mode(2)
        self.radio.set_tx(True)
        self.radio.set_tx(False)
        self.assertTrue(all(b"\r" not in sent for sent in self.radio.ser.written))

    def test_transmit_unkeys_after_an_exception(self) -> None:
        with self.assertRaises(RuntimeError):
            with self.radio.transmit():
                raise RuntimeError("boom")
        self.assertEqual(self.radio.ser.written, [b"TX;", b"RX;"])


if __name__ == "__main__":
    unittest.main()

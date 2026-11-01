"""Scripts that can transmit or change a radio's settings must stop unless told to go ahead."""

import contextlib
import io
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ic7300"))

import ardop_listen
import calibrate_drive
import find_af_level
import swr_check
from ic7300 import CIVError

MUST_NOT_RUN = AssertionError("reached the radio without being told to")


def quietly(fn):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn()


class TransmitGates(unittest.TestCase):
    def test_calibrate_drive_needs_the_transmit_flag(self) -> None:
        with mock.patch.object(sys, "argv", ["calibrate_drive.py", "90", "78"]):
            with mock.patch.object(calibrate_drive, "Rigctld", side_effect=MUST_NOT_RUN):
                self.assertEqual(quietly(calibrate_drive.main), 2)

    def test_swr_check_needs_a_frequency(self) -> None:
        with mock.patch.object(sys, "argv", ["swr_check.py"]):
            with mock.patch.object(swr_check, "IC7300", side_effect=MUST_NOT_RUN):
                self.assertEqual(quietly(swr_check.main), 2)

    def test_ardop_listen_needs_a_callsign(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "MYCALL"}
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch.object(sys, "argv", ["ardop_listen.py"]):
                with mock.patch.object(
                    ardop_listen.socket, "create_connection", side_effect=MUST_NOT_RUN
                ):
                    self.assertEqual(quietly(ardop_listen.main), 2)


class StubRig:
    values = {21: 128, 43: 128, 60: 255, 63: 12, 64: 128}

    def get_menu_int(self, item: int) -> int:
        if item not in self.values:
            raise CIVError("radio rejected command")
        return self.values[item]

    def get_menu(self, item: int) -> bytes:
        return bytes([item])


class MenuGuard(unittest.TestCase):
    def test_only_items_at_the_default_are_touched(self) -> None:
        self.assertEqual(sorted(find_af_level.at_default(StubRig())), [21, 43, 64])


if __name__ == "__main__":
    unittest.main()

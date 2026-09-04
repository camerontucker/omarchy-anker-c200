import subprocess
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import anker_c200_backend as backend


class BackendTests(unittest.TestCase):
    def test_bundled_controller_is_built_atomically_and_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            stamp = cache / "controller-v2.json"

            with (
                patch.object(backend, "CACHE", cache),
                patch.object(backend, "CACHE_STAMP", stamp),
                patch.object(backend, "CONTROL_FD", None),
                patch.object(backend, "run_bounded", wraps=backend.run_bounded) as run,
            ):
                self.assertTrue(backend.ensure_controller())
                self.assertIsNotNone(backend.CONTROL_FD)
                self.assertTrue(stamp.is_file())
                os.close(backend.CONTROL_FD)
                backend.CONTROL_FD = None
                self.assertTrue(backend.ensure_controller())
                self.assertEqual(run.call_count, 1)
                os.close(backend.CONTROL_FD)

    def test_control_value_parses_controller_output(self):
        self.assertEqual(backend.control_value("fov", "65 (narrow)\n"), "narrow")
        self.assertTrue(backend.control_value("horizontal_flip", "on\n"))
        self.assertFalse(backend.control_value("white_balance_automatic", "off\n"))
        self.assertEqual(backend.control_value("zoom_absolute", "123\n"), 123)

    @patch.object(backend, "read_one", return_value=False)
    def test_verify_one_rejects_a_write_that_did_not_stick(self, _read_one):
        with self.assertRaisesRegex(ValueError, "did not stick"):
            backend.verify_one("horizontal_flip", True, Path("/dev/video0"))

    @patch.object(backend, "verify_one")
    @patch.object(backend, "apply_one")
    def test_disabling_auto_white_balance_restores_manual_temperature(self, apply, verify):
        camera = Path("/dev/video0")
        desired = {"white_balance_temperature": 5200}

        backend.apply_change("white_balance_automatic", False, camera, desired)

        self.assertEqual(
            apply.call_args_list,
            [
                unittest.mock.call("white_balance_automatic", False, camera),
                unittest.mock.call("white_balance_temperature", 5200, camera),
            ],
        )
        self.assertEqual(verify.call_args_list, apply.call_args_list)

    @patch.object(backend, "verify_one")
    @patch.object(backend, "apply_one")
    @patch.object(
        backend,
        "load",
        return_value={
            "white_balance_automatic": True,
            "white_balance_temperature": 5500,
            "brightness": 50,
        },
    )
    def test_profile_skips_inactive_manual_temperature(self, _load, apply, verify):
        camera = Path("/dev/video0")

        self.assertEqual(backend.apply_profile(camera), [])

        self.assertEqual(
            [call.args[0] for call in apply.call_args_list],
            ["white_balance_automatic", "brightness"],
        )
        self.assertEqual(
            [call.args[0] for call in verify.call_args_list],
            ["white_balance_automatic", "brightness"],
        )

    @patch.object(backend, "V4L2_CONTROL", "/usr/bin/v4l2-ctl")
    @patch.object(backend, "run_bounded")
    def test_driver_defaults_come_from_v4l2(self, run):
        run.return_value = subprocess.CompletedProcess(
            [],
            0,
            stdout=(
                "brightness 0x00980900 (int) : min=0 max=100 default=50 value=61\n"
                "white_balance_automatic 0x0098090c (bool) : default=1 value=0\n"
            ),
            stderr="",
        )
        self.assertEqual(
            backend.driver_defaults(Path("/dev/video0")),
            {"brightness": 50, "white_balance_automatic": True},
        )

    @patch.object(backend, "camera_holders", return_value=[{"name": "zoom", "pid": 42}])
    @patch.object(backend, "driver_defaults", return_value={"brightness": 50})
    @patch.object(
        backend,
        "read_actual",
        return_value=({"brightness": 61, "horizontal_flip": True}, {}),
    )
    @patch.object(backend, "controller_available", return_value=True)
    @patch.object(backend, "ensure_controller", return_value=True)
    @patch.object(backend, "process_running", return_value=False)
    @patch.object(backend, "device", return_value=Path("/dev/video0"))
    @patch.object(
        backend,
        "load",
        return_value={"brightness": 50, "horizontal_flip": False},
    )
    def test_status_separates_saved_profile_from_live_hardware(
        self,
        _load,
        _device,
        _process,
        _ensure,
        _controller,
        _actual,
        _defaults,
        _holders,
    ):
        state = backend.status()
        self.assertEqual(
            state["profile"], {"brightness": 50, "horizontal_flip": False}
        )
        self.assertEqual(state["brightness"], 61)
        self.assertEqual(
            state["profile_drift"], ["brightness", "horizontal_flip"]
        )
        self.assertFalse(state["profile_applied"])
        self.assertEqual(state["busy_processes"][0]["name"], "zoom")

    @patch.object(backend, "camera_holders", return_value=[])
    @patch.object(backend, "driver_defaults", return_value={})
    @patch.object(
        backend,
        "read_actual",
        return_value=(
            {
                "white_balance_automatic": True,
                "white_balance_temperature": 3996,
            },
            {},
        ),
    )
    @patch.object(backend, "controller_available", return_value=True)
    @patch.object(backend, "ensure_controller", return_value=True)
    @patch.object(backend, "process_running", return_value=False)
    @patch.object(backend, "device", return_value=Path("/dev/video0"))
    @patch.object(
        backend,
        "load",
        return_value={
            "white_balance_automatic": True,
            "white_balance_temperature": 5500,
        },
    )
    def test_auto_managed_temperature_does_not_create_profile_drift(
        self,
        _load,
        _device,
        _process,
        _ensure,
        _controller,
        _actual,
        _defaults,
        _holders,
    ):
        state = backend.status()

        self.assertEqual(state["white_balance_temperature"], 3996)
        self.assertEqual(state["profile_drift"], [])
        self.assertTrue(state["profile_applied"])

    @patch.object(backend, "read_file", return_value=b'{"hdr": false, "brightness": 61, "future": 9}')
    def test_load_ignores_removed_or_unknown_saved_controls(self, _read):

        values = backend.load()

        self.assertEqual(values["brightness"], 61)
        self.assertNotIn("hdr", values)
        self.assertNotIn("future", values)


if __name__ == "__main__":
    unittest.main()

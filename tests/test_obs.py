import unittest

import obs_control


class FakeObs:
    def request(self, request_type, _request_data=None):
        if request_type == "GetVideoSettings":
            return {
                "baseWidth": 1920,
                "baseHeight": 1080,
                "outputWidth": 1280,
                "outputHeight": 720,
                "fpsNumerator": 30000,
                "fpsDenominator": 1001,
            }
        if request_type == "GetVirtualCamStatus":
            return {"outputActive": True}
        raise AssertionError(request_type)


class FakeWebSocket:
    def close(self):
        pass


class FakeFramingObs(FakeObs):
    def __init__(self):
        self.ws = FakeWebSocket()
        self.transform_reads = 0
        self.crop_writes = []
        self.current_transform = {
            "sourceWidth": 1920,
            "sourceHeight": 1080,
            "cropLeft": 240,
            "cropRight": 240,
            "cropTop": 135,
            "cropBottom": 135,
        }

    def camera_item(self):
        return "Meeting", 7, "Anker PowerConf C200"

    def transform(self, _scene, _item_id):
        self.transform_reads += 1
        return dict(self.current_transform)

    def set_crop(self, _scene, _item_id, crop):
        self.crop_writes.append(dict(crop))
        self.current_transform.update(crop)


class ObsStatusTests(unittest.TestCase):
    def test_persistent_session_keeps_discovery_out_of_drag_updates(self):
        obs = FakeFramingObs()
        session = obs_control.FramingSession(obs)

        first = session.handle("pan", [39, 22, 390, 220])
        second = session.handle("pan", [39, 22, 390, 220])

        self.assertEqual(obs.transform_reads, 1)
        self.assertEqual(len(obs.crop_writes), 2)
        self.assertEqual(first["crop_left"], 192)
        self.assertEqual(second["crop_left"], 144)
        self.assertTrue(second["connected"])

    def test_pan_crop_reaches_every_edge_in_one_full_preview_gesture(self):
        transform = {
            "cropLeft": 240,
            "cropRight": 240,
            "cropTop": 135,
            "cropBottom": 135,
        }

        self.assertEqual(
            obs_control.pan_crop(transform, 390, 220, 390, 220),
            {"cropLeft": 0, "cropRight": 480, "cropTop": 0, "cropBottom": 270},
        )
        self.assertEqual(
            obs_control.pan_crop(transform, -390, -220, 390, 220),
            {"cropLeft": 480, "cropRight": 0, "cropTop": 270, "cropBottom": 0},
        )

    def test_status_reports_format_virtual_camera_and_crop(self):
        state = obs_control.status_payload(
            FakeObs(),
            "Meeting",
            7,
            "Anker PowerConf C200",
            {
                "sourceWidth": 1920,
                "sourceHeight": 1080,
                "cropLeft": 480,
                "cropRight": 0,
                "cropTop": 135,
                "cropBottom": 135,
            },
        )

        self.assertEqual(state["source_width"], 1920)
        self.assertEqual(state["output_width"], 1280)
        self.assertEqual(state["fps"], 29.97)
        self.assertTrue(state["virtual_camera_active"])
        self.assertEqual(
            [state["crop_left"], state["crop_right"], state["crop_top"], state["crop_bottom"]],
            [480, 0, 135, 135],
        )


if __name__ == "__main__":
    unittest.main()

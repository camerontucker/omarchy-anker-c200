import ast
import json
import re
import unittest
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[1]


class ReleaseContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads(
            (REPOSITORY / "manifest.json").read_text(encoding="utf-8")
        )

    def test_marketplace_manifest_contract(self):
        manifest = self.manifest
        self.assertEqual(manifest["schemaVersion"], 1)
        self.assertEqual(manifest["id"], "io.github.camerontucker.anker-c200")
        self.assertEqual(manifest["version"], "1.2.0")
        self.assertEqual(manifest["license"], "MIT")
        self.assertEqual(manifest["kinds"], ["bar-widget"])
        self.assertEqual(manifest["entryPoints"], {"barWidget": "Panel.qml"})
        self.assertEqual(manifest["barWidget"]["defaultSection"], "right")
        self.assertFalse(manifest["barWidget"]["allowMultiple"])
        self.assertEqual(
            list(REPOSITORY.rglob("manifest.json")),
            [REPOSITORY / "manifest.json"],
        )

    def test_required_release_files_exist(self):
        for relative_path in (
            "CHANGELOG.md",
            ".github/workflows/ci.yml",
            "LICENSE",
            "Panel.qml",
            "README.md",
            "SECURITY.md",
            "THIRD_PARTY_NOTICES.md",
            "anker_c200_backend.py",
            "docs/ASSETS.md",
            "docs/STORE_SUBMISSION.md",
            "docs/assets/synthetic-meeting-feed.png",
            "docs/screenshots/framing-detail.png",
            "docs/screenshots/panel-overview.png",
            "manifest.json",
            "obs_control.py",
            "preview.png",
            "tests/run",
            "tests/test_backend.py",
            "tests/test_obs.py",
            "tests/test_release.py",
            "vendor/anker-powerconf-c200-linux-tools/LICENSE",
            "vendor/anker-powerconf-c200-linux-tools/UPSTREAM.md",
            "vendor/anker-powerconf-c200-linux-tools/src/c200_controls.c",
            "vendor/anker-powerconf-c200-linux-tools/src/c200_controls.h",
            "vendor/anker-powerconf-c200-linux-tools/src/c200_fov.c",
            "vendor/anker-powerconf-c200-linux-tools/src/c200_fov.h",
            "vendor/anker-powerconf-c200-linux-tools/src/c200_fov_cli.c",
            "vendor/anker-powerconf-c200-linux-tools/src/c200_vendor.c",
            "vendor/anker-powerconf-c200-linux-tools/src/c200_vendor.h",
        ):
            with self.subTest(path=relative_path):
                self.assertTrue((REPOSITORY / relative_path).is_file())

    def test_payload_excludes_agent_instructions(self):
        # Omarchy installs the entire repository, not just manifest entry points.
        forbidden_names = {"agents.md", "agents.override.md"}
        instruction_paths = sorted(
            str(path.relative_to(REPOSITORY))
            for path in REPOSITORY.rglob("*")
            if ".git" not in path.relative_to(REPOSITORY).parts
            and path.name.casefold() in forbidden_names
        )
        self.assertEqual(instruction_paths, [], "Agent instructions must not ship")

    def test_readme_covers_marketplace_lifecycle_and_dependencies(self):
        readme = (REPOSITORY / "README.md").read_text(encoding="utf-8")
        for text in (
            "**Omarchy Quattro**",
            "anker-powerconf-c200-linux-tools",
            "OBS integration (optional)",
            "omarchy plugin add https://github.com/camerontucker/omarchy-anker-c200.git --enable",
            "omarchy plugin update io.github.camerontucker.anker-c200",
            "omarchy plugin remove io.github.camerontucker.anker-c200",
            "unsandboxed user code",
            "no telemetry",
            "## Acknowledgements",
            "anker-powerconf-c200-linux-tools",
            "Quickshell",
            "OBS Studio",
            "That is the complete required setup",
            "$XDG_CACHE_HOME/anker-c200/bin/anker-c200",
        ):
            with self.subTest(text=text):
                self.assertIn(text, readme)

    def test_third_party_notices_credit_upstreams(self):
        notices = (REPOSITORY / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
        for text in (
            "Copyright (c) David Heinemeier Hansson",
            "Copyright (c) 2026 Eran Sandler",
            "LGPL-3.0-only",
            "GPL-2.0-only",
            "No third-party binaries or libraries are copied into this repository",
            "1912f8690802346557f6bc1d1024e31dec1c7273",
            "No prebuilt controller binary is distributed",
        ):
            with self.subTest(text=text):
                self.assertIn(text, notices)

    def test_readme_local_links_resolve(self):
        readme = (REPOSITORY / "README.md").read_text(encoding="utf-8")
        targets = re.findall(r"!?\[[^]]*\]\(([^)]+)\)", readme)
        for target in targets:
            if "://" in target or target.startswith("#"):
                continue
            path = target.split("#", 1)[0]
            with self.subTest(target=target):
                self.assertTrue((REPOSITORY / path).exists())

    def test_preview_selection_avoids_camera_contention(self):
        qml = (REPOSITORY / "Panel.qml").read_text(encoding="utf-8")
        self.assertIn("readonly property bool useObsPreview: statusReady && obsRunning", qml)
        self.assertIn("readonly property bool useDirectPreview: statusReady && !obsRunning", qml)
        self.assertIn("property bool statusReady: false", qml)
        self.assertIn("id: previewCaptureLoader", qml)
        self.assertIn("active: root.previewActive && root.previewAvailable", qml)
        self.assertIn("function closePanel()", qml)
        self.assertIn("previewActive = false", qml)
        self.assertIn("preventStealing: true", qml)
        self.assertIn("onCanceled: root.flushPan()", qml)
        self.assertIn('["python3", root.obsBackend, "serve"]', qml)
        self.assertIn("stdinEnabled: true", qml)
        self.assertIn("stdout: SplitParser", qml)
        self.assertIn("interval: 24", qml)
        self.assertIn("property bool framingBusy: false", qml)
        self.assertIn("DIRECT PREVIEW · START OBS TO REFRAME", qml)
        self.assertIn("PROFILE DRIFT", qml)
        self.assertIn("Apply saved profile", qml)
        self.assertIn("const obsJustStarted = !obsRunning && nextObsRunning", qml)
        self.assertIn("PHYSICAL CAMERA HELD BY", qml)
        self.assertIn("CROP · L ", qml)
        self.assertIn("buttonCode === Qt.MiddleButton", qml)
        self.assertIn("buttonCode === Qt.RightButton", qml)
        self.assertIn("implicitWidth: button.implicitWidth", qml)
        self.assertIn("component WheelSafeSlider", qml)
        self.assertIn("wheel.accepted = false", qml)
        self.assertIn(
            'onToggled: root.setControl("white_balance_automatic", checked ? "off" : "on")',
            qml,
        )
        self.assertIn(
            'onToggled: root.setControl("focus_automatic_continuous", checked ? "off" : "on")',
            qml,
        )
        self.assertGreaterEqual(qml.count("busy: actionProc.running"), 2)
        self.assertIn('label: root.autoWhiteBalance ? "TEMPERATURE · AUTO" : "TEMPERATURE"', qml)
        self.assertIn('["python3", root.backend, "read", "white_balance_temperature"]', qml)
        self.assertIn("running: root.opened && root.connected && root.autoWhiteBalance", qml)
        self.assertIn("if (stateProc.running) stateProc.running = false", qml)
        self.assertLess(qml.index('label: "ZOOM"'), qml.index('text: "FIELD OF VIEW"'))

    def test_controller_is_optional_and_inputs_are_validated(self):
        backend = (REPOSITORY / "anker_c200_backend.py").read_text(encoding="utf-8")
        self.assertIn('"controller_available": controller_available()', backend)
        self.assertIn("ensure_controller()", backend)
        self.assertIn("controller_fingerprint()", backend)
        self.assertIn('shutil.which("cc")', backend)
        self.assertIn("temporary.replace(CACHE_CONTROL)", backend)
        self.assertIn('"obs_running": process_running("obs")', backend)
        self.assertIn('"profile_drift": drift', backend)
        self.assertIn('"busy_processes": holders', backend)
        self.assertIn("verify_one(name, value, camera)", backend)
        self.assertIn("if value < low or value > high", backend)
        self.assertNotIn("shell=True", backend)

    def test_bundled_controller_is_pinned_and_has_no_build_download(self):
        upstream = (REPOSITORY / "vendor/anker-powerconf-c200-linux-tools/UPSTREAM.md").read_text(
            encoding="utf-8"
        )
        backend = (REPOSITORY / "anker_c200_backend.py").read_text(encoding="utf-8")
        self.assertIn("1912f8690802346557f6bc1d1024e31dec1c7273", upstream)
        self.assertNotIn("http://", backend)
        self.assertNotIn("https://", backend)
        self.assertNotIn("pacman", backend)
        self.assertNotIn("pkexec", backend)

    def test_unreliable_hdr_control_is_not_shipped(self):
        backend = (REPOSITORY / "anker_c200_backend.py").read_text(encoding="utf-8")
        qml = (REPOSITORY / "Panel.qml").read_text(encoding="utf-8")
        self.assertNotIn('"hdr"', backend)
        self.assertNotIn('"hdr"', qml)
        self.assertNotIn('text: "HDR"', qml)

    def test_obs_client_is_loopback_only_and_does_not_log_password(self):
        obs = (REPOSITORY / "obs_control.py").read_text(encoding="utf-8")
        self.assertIn('HOST = "127.0.0.1"', obs)
        self.assertIn('config["server_password"]', obs)
        self.assertIn("WEBSOCKET_GUID", obs)
        self.assertIn("MAX_MESSAGE_BYTES", obs)
        self.assertIn('obs.request("GetVideoSettings")', obs)
        self.assertIn('obs.request("GetVirtualCamStatus")', obs)
        self.assertIn('"virtual_camera_active"', obs)
        self.assertIn("class FramingSession:", obs)
        self.assertIn("def serve() -> int:", obs)
        self.assertNotIn('print(password', obs)
        self.assertNotIn("shell=True", obs)

    def test_python_uses_only_the_standard_library(self):
        allowed = {
            "__future__",
            "base64",
            "hashlib",
            "json",
            "os",
            "pathlib",
            "re",
            "shutil",
            "socket",
            "struct",
            "subprocess",
            "sys",
            "uuid",
        }
        for filename in ("anker_c200_backend.py", "obs_control.py"):
            tree = ast.parse((REPOSITORY / filename).read_text(encoding="utf-8"))
            imported = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(alias.name.split(".", 1)[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module.split(".", 1)[0])
            self.assertEqual(imported - allowed, set(), filename)

    def test_submission_draft_shape_and_metadata(self):
        draft = (REPOSITORY / "docs/STORE_SUBMISSION.md").read_text(encoding="utf-8")
        headings = (
            "### Repository URL",
            "### Category",
            "### Tags",
            "### Suggest a missing tag",
            "### Maintainer notes",
            "### Submission checklist",
        )
        positions = [draft.index(heading) for heading in headings]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("[Plugin]: Anker C200 Controls", draft)
        self.assertIn("https://github.com/camerontucker/omarchy-anker-c200", draft)
        self.assertIn("Hardware", draft)
        self.assertIn("bar, quickshell, system", draft)


if __name__ == "__main__":
    unittest.main()

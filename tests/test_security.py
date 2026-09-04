import fcntl
import base64
import hashlib
import json
import os
import shutil
import signal
import socket
import subprocess
import struct
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import anker_c200_backend as backend
import obs_control as obs
import runtime_guard as guard
import secure_io as files

ROOT = Path(__file__).resolve().parents[1]


class FileBoundaryTests(unittest.TestCase):
    def test_fifo_symlink_hardlink_and_unsafe_parent_rejected_without_blocking(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "settings.json"
            real = root / "real"
            real.write_bytes(b"secret")
            real.chmod(0o600)
            start = time.monotonic()
            os.mkfifo(target)
            with self.assertRaises(files.UnsafeInput):
                files.read_file(target)
            with self.assertRaises(files.UnsafeInput):
                files.write_file(target, b"{}")
            target.unlink()
            target.symlink_to(real)
            with self.assertRaises(OSError):
                files.read_file(target)
            with self.assertRaises(OSError):
                files.write_file(target, b"{}")
            self.assertEqual(real.read_bytes(), b"secret")
            target.unlink()
            os.link(real, target)
            with self.assertRaises(files.UnsafeInput):
                files.read_file(target)
            target.unlink()
            root.chmod(0o777)
            with self.assertRaises(files.UnsafeInput):
                files.read_file(real)
            root.chmod(0o700)
            self.assertLess(time.monotonic() - start, 1)

    def test_private_atomic_publication_and_parent_descriptor_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / "private" / "settings.json"
            files.write_file(data, b'{"brightness":61}')
            self.assertEqual(data.stat().st_mode & 0o777, 0o600)
            self.assertEqual(data.parent.stat().st_mode & 0o777, 0o700)
            with files.locked_directory(data.parent) as parent:
                original = data.parent.with_name("original")
                data.parent.rename(original)
                data.parent.symlink_to(root)
                files.publish(parent, data.name, b'{"brightness":62}')
                self.assertFalse((root / data.name).exists())
                self.assertEqual((original / data.name).read_bytes(), b'{"brightness":62}')

    def test_size_schema_and_credentials_fail_closed(self):
        malformed = [b'[]', b'{"x":NaN}', b'{"x":1e309}', b'{"x":1,"x":2}', b'{"x":' + b'[' * 40 + b'0' + b']' * 40 + b'}',
                     json.dumps({"x": "a" * 1025}).encode()]
        for raw in malformed:
            with self.subTest(raw=raw[:32]), self.assertRaises(files.UnsafeInput):
                files.json_object(raw)
        for raw in (b'{"brightness":999}', b'{"white_balance_automatic":"off"}', b'[]'):
            with patch.object(backend, "read_file", return_value=raw), self.assertRaises((files.UnsafeInput, ValueError)):
                backend.load()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_bytes(b"x" * 8193)
            path.chmod(0o600)
            with patch.object(obs, "OBS_CONFIG", path), self.assertRaises(files.UnsafeInput):
                obs.Obs()
            path.write_text('{"server_password":"private","server_port":"4455"}')
            with patch.object(obs, "OBS_CONFIG", path), self.assertRaises(obs.ObsError):
                obs.Obs()
            path.chmod(0o644)
            with self.assertRaises(files.UnsafeInput):
                files.read_file(path, secret=True)

    def test_no_replace_publication_preserves_existing_object(self):
        with tempfile.TemporaryDirectory() as tmp, files.locked_directory(tmp) as parent:
            files.publish(parent, "artifact", b"original", replace=False)
            with self.assertRaises(FileExistsError):
                files.publish(parent, "artifact", b"replacement", replace=False)
            self.assertEqual((Path(tmp) / "artifact").read_bytes(), b"original")


class ProcessBoundaryTests(unittest.TestCase):
    def test_real_qml_consumer_success_and_unterminated_flood(self):
        quickshell = shutil.which("quickshell")
        if not quickshell:
            self.skipTest("Quickshell runtime is only present on Omarchy")
        with tempfile.TemporaryDirectory() as tmp:
            harness = Path(tmp) / "shell.qml"
            harness.write_text((ROOT / "tests/ProcessHarness.qml").read_text().replace('"../"', '"./"'))
            shutil.copyfile(ROOT / "BoundedProcess.qml", Path(tmp) / "BoundedProcess.qml")
            result = subprocess.run([quickshell, "--no-color", "-p", str(harness)],
                                    env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
                                    capture_output=True, text=True, timeout=8)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("HARNESS_PASS", result.stdout + result.stderr)
        self.assertNotIn("HARNESS_FAIL", result.stdout + result.stderr)

    def test_flood_unterminated_output_and_absolute_deadline(self):
        programs = ["import os\nwhile True: os.write(1,b'x'*4096)",
                    "import time,os\nwhile True: os.write(1,b'x'); time.sleep(.02)"]
        for program in programs:
            start = time.monotonic()
            with self.assertRaises(files.UnsafeInput):
                guard.run_bounded([guard.PYTHON, "-I", "-S", "-c", program], cap=8192, timeout=.2)
            self.assertLess(time.monotonic() - start, 2)

    def test_descendant_held_pipes_ignore_term_are_killed_and_reaped(self):
        with tempfile.TemporaryDirectory() as tmp:
            pidfile = Path(tmp) / "child.pid"
            code = ("import os,signal,time\n"
                    "pid=os.fork()\n"
                    "if pid: os._exit(0)\n"
                    "signal.signal(signal.SIGTERM,signal.SIG_IGN)\n"
                    f"open({str(pidfile)!r},'w').write(str(os.getpid()))\n"
                    "time.sleep(30)\n")
            with self.assertRaises(files.UnsafeInput):
                guard.run_bounded([guard.PYTHON, "-I", "-S", "-c", code], timeout=.3)
            self.assertFalse(Path("/proc", pidfile.read_text()).exists())

    def test_system_executable_binding_and_environment(self):
        with patch.dict(os.environ, {"PATH": "/tmp/hostile", "PYTHONPATH": "/tmp/hostile", "LD_PRELOAD": "/tmp/hostile", "GCC_EXEC_PREFIX": "/tmp/hostile"}):
            result = guard.run_bounded([guard.PYTHON, "-I", "-S", "-c", "import os;print(os.environ['PATH']);print('LD_PRELOAD' in os.environ)"])
            self.assertEqual(result.stdout, "/usr/bin\nFalse\n")
        with self.assertRaises(files.UnsafeInput):
            guard.trusted_executable("python3")

    def test_sealed_artifact_cannot_change(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(backend, "CACHE", Path(tmp)), \
             patch.object(backend, "CACHE_STAMP", Path(tmp) / "controller-v2.json"), \
             patch.object(backend, "CONTROL_FD", None):
            self.assertTrue(backend.ensure_controller())
            fd = backend.CONTROL_FD
            try:
                with self.assertRaises(OSError):
                    os.write(fd, b"bad")
                artifact = next(Path(tmp).glob("controller-" + "?" * 64))
                artifact.write_bytes(b"tampered")
                result = guard.run_bounded(["controller", "list-controls"], executable_fd=fd)
                self.assertIn("brightness", result.stdout)
                backend.CONTROL_FD = None
                with self.assertRaises(files.UnsafeInput):
                    backend.ensure_controller()
            finally:
                os.close(fd)

    def test_supervisor_term_cleanup_and_stalled_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("runtime_guard.py", "secure_io.py"):
                shutil.copyfile(ROOT / name, root / name)
            guard_path = root / "runtime_guard.py"
            guard_path.write_text(guard_path.read_text().replace("REQUEST_SECONDS = 8", "REQUEST_SECONDS = 0.3"))
            pidfile = root / "pid"
            (root / "obs_control.py").write_text(
                "import os,signal,time\ndef main():\n"
                " pid=os.fork()\n"
                " if not pid:\n"
                "  signal.signal(signal.SIGTERM,signal.SIG_IGN)\n"
                f"  open({str(pidfile)!r},'w').write(str(os.getpid()))\n"
                "  time.sleep(30)\n"
                " print('{}',flush=True)\n"
                " time.sleep(30)\n")
            for cancel in ("deadline", "term", "kill"):
                process = subprocess.Popen([guard.PYTHON, "-I", "-S", str(guard_path), "obs", "serve"],
                                           stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                try:
                    self.assertEqual(process.stdout.readline(), b"{}\n")
                    if cancel == "term":
                        process.terminate()
                    elif cancel == "kill":
                        process.kill()
                    else:
                        process.stdin.write(b'{}\n'); process.stdin.flush()
                    process.wait(timeout=3)
                    end = time.monotonic() + 2
                    while Path("/proc", pidfile.read_text()).exists() and time.monotonic() < end:
                        time.sleep(.02)
                    self.assertFalse(Path("/proc", pidfile.read_text()).exists())
                finally:
                    if process.poll() is None:
                        process.kill(); process.wait()
                    for pipe in (process.stdin, process.stdout, process.stderr):
                        pipe.close()


class ObsBoundaryTests(unittest.TestCase):
    def test_authenticated_loopback_framing_with_private_credentials(self):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0)); listener.listen(1); listener.settimeout(3)
        port = listener.getsockname()[1]
        errors = []
        def server():
            try:
                with listener.accept()[0] as sock:
                    sock.settimeout(3)
                    header = b""
                    while not header.endswith(b"\r\n\r\n"):
                        header += sock.recv(1)
                    key = next(line.split(b":",1)[1].strip() for line in header.split(b"\r\n") if line.lower().startswith(b"sec-websocket-key:"))
                    accept = base64.b64encode(hashlib.sha1(key + obs.WEBSOCKET_GUID.encode()).digest())
                    sock.sendall(b"HTTP/1.1 101 Switching Protocols\r\nSec-WebSocket-Accept: " + accept + b"\r\n\r\n")
                    def send(value):
                        data = json.dumps(value).encode()
                        prefix = bytes((0x81,len(data))) if len(data) < 126 else b'\x81\x7e' + struct.pack('!H',len(data))
                        sock.sendall(prefix + data)
                    def read(count):
                        data = b""
                        while len(data) < count:
                            chunk = sock.recv(count-len(data))
                            if not chunk: raise EOFError()
                            data += chunk
                        return data
                    def receive():
                        first, second = read(2)
                        length = second & 127
                        if length == 126: length = struct.unpack('!H',read(2))[0]
                        mask = read(4)
                        return json.loads(bytes(value ^ mask[index%4] for index,value in enumerate(read(length))))
                    send({"op":0,"d":{"authentication":{"salt":"salt","challenge":"challenge"}}})
                    identification = receive()
                    secret = base64.b64encode(hashlib.sha256(b"private-testsalt").digest())
                    expected = base64.b64encode(hashlib.sha256(secret + b"challenge").digest()).decode()
                    self.assertEqual(identification['d']['authentication'], expected)
                    self.assertNotIn('private-test',json.dumps(identification))
                    send({"op":2,"d":{}})
                    responses = {
                        "GetCurrentProgramScene":{"currentProgramSceneName":"Meeting"},
                        "GetSceneItemList":{"sceneItems":[{"sourceName":"Anker C200","sceneItemId":7}]},
                        "GetSceneItemTransform":{"sceneItemTransform":{"sourceWidth":1920,"sourceHeight":1080,"cropLeft":240,"cropRight":240,"cropTop":135,"cropBottom":135}},
                        "GetVideoSettings":{"outputWidth":1280,"outputHeight":720,"baseWidth":1920,"baseHeight":1080,"fpsNumerator":30,"fpsDenominator":1},
                        "GetVirtualCamStatus":{"outputActive":True},
                        "SetSceneItemTransform":{},
                    }
                    for _ in range(6):
                        request = receive()['d']
                        send({"op":7,"d":{"requestId":request['requestId'],"requestStatus":{"result":True},"responseData":responses[request['requestType']]}})
            except BaseException as exc:
                errors.append(exc)
        thread = threading.Thread(target=server)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                config = Path(tmp) / "config.json"
                config.write_text(json.dumps({"server_port":port,"server_password":"private-test"}))
                config.chmod(0o600)
                with patch.object(obs, "OBS_CONFIG", config):
                    session = obs.FramingSession()
                    try:
                        self.assertEqual(session.handle("pan", [390,220,390,220])["crop_left"],0)
                    finally:
                        session.close()
        finally:
            thread.join(timeout=4); listener.close()
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])

    def test_proc_cap_applies_before_directory_materialization(self):
        from unittest.mock import MagicMock
        count = [0]
        def entries():
            for index in range(20000):
                count[0] += 1
                yield type("Entry", (), {"path": f"/proc/{index}"})()
        scanner = MagicMock()
        scanner.__enter__.return_value = entries()
        with patch.object(backend.os, "scandir", return_value=scanner), self.assertRaises(files.UnsafeInput):
            list(backend.scan_entries("/proc", 8))
        self.assertEqual(count[0], 9)
        scanner.__exit__.assert_called_once()

    def test_handshake_eof_closes_socket(self):
        from unittest.mock import MagicMock
        sock = MagicMock()
        sock.recv.return_value = b""
        with patch.object(socket, "create_connection", return_value=sock), self.assertRaises(obs.ObsError):
            obs.WebSocket(4455)
        sock.close.assert_called_once()

    def test_drip_and_ping_stream_have_absolute_and_frame_limits(self):
        client, server = socket.socketpair()
        ws = obs.WebSocket.__new__(obs.WebSocket)
        ws.sock, ws.buffer, ws.frames = client, b"", 0
        ws.deadline = time.monotonic() + .15
        stopped = threading.Event()
        def drip():
            while not stopped.wait(.02):
                try:
                    server.send(b'x')
                except OSError:
                    break
        thread = threading.Thread(target=drip)
        thread.start()
        try:
            with self.assertRaises((obs.ObsError, OSError)):
                ws._read(100)
        finally:
            stopped.set(); thread.join(); client.close(); server.close()
        ws = obs.WebSocket.__new__(obs.WebSocket)
        ws.frames = 0
        with patch.object(ws, "_read", side_effect=lambda count: b'\x89\x00' if count == 2 else b''), \
             patch.object(ws, "_send_control"), self.assertRaises(obs.ObsError):
            ws.receive()

    def test_invalid_transform_and_pan_arguments(self):
        for value in (float('nan'), float('inf'), True, "10", -1, 999999):
            with self.assertRaises(obs.ObsError):
                obs.transform_value({"cropLeft": value})
        with self.assertRaises(obs.ObsError):
            obs.pan_crop({}, float('nan'), 0, 300, 200)
        with self.assertRaises(ValueError):
            backend.control_value("brightness", "999")
        with self.assertRaises(files.UnsafeInput):
            list(backend.bounded_entries(range(100), 8))

    def test_ui_schema_rejects_untrusted_fields_and_neutralizes_markup(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node required for the pure-JS consumer schema check")
        source = (ROOT / "Schema.js").read_text().replace('.pragma library', '')
        program = source + """
const assert = require('assert');
assert.throws(() => obs({connected:'yes'}));
assert.throws(() => temperature({white_balance_temperature:NaN}));
assert.throws(() => controlMap({brightness:999}));
assert.throws(() => state({busy_processes:Array(1000).fill({name:'x',pid:1})}));
assert(!label('<img src="file:///private">').includes('<'));
assert.strictEqual(temperature({white_balance_temperature:4500}),4500);
"""
        subprocess.run([node, "-e", program], check=True, timeout=3, capture_output=True)


if __name__ == "__main__":
    unittest.main()

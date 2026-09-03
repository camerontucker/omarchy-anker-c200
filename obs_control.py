#!/usr/bin/env python3
"""Small stdlib-only OBS WebSocket bridge for camera framing."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import struct
import sys
import uuid
from pathlib import Path


CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
OBS_CONFIG = CONFIG_HOME / "obs-studio/plugin_config/obs-websocket/config.json"
HOST = "127.0.0.1"
DEFAULT_PORT = 4455
WEBSOCKET_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
MAX_MESSAGE_BYTES = 1024 * 1024


class ObsError(RuntimeError):
    pass


class WebSocket:
    def __init__(self, port: int) -> None:
        self.sock = socket.create_connection((HOST, port), timeout=1.5)
        self.sock.settimeout(1.5)
        self.buffer = b""
        key = base64.b64encode(os.urandom(16)).decode()
        request = (
            "GET / HTTP/1.1\r\n"
            f"Host: {HOST}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        ).encode()
        self.sock.sendall(request)
        response = b""
        while b"\r\n\r\n" not in response:
            response += self.sock.recv(4096)
            if len(response) > 32768:
                raise ObsError("invalid OBS WebSocket handshake")
        headers, self.buffer = response.split(b"\r\n\r\n", 1)
        if not headers.startswith(b"HTTP/1.1 101"):
            raise ObsError("OBS WebSocket handshake was rejected")
        header_values = {}
        for line in headers.split(b"\r\n")[1:]:
            if b":" not in line:
                continue
            name, value = line.split(b":", 1)
            header_values[name.strip().lower()] = value.strip()
        expected_accept = base64.b64encode(
            hashlib.sha1((key + WEBSOCKET_GUID).encode()).digest()
        )
        if header_values.get(b"sec-websocket-accept") != expected_accept:
            raise ObsError("invalid OBS WebSocket handshake signature")

    def _read(self, count: int) -> bytes:
        while len(self.buffer) < count:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ObsError("OBS closed the connection")
            self.buffer += chunk
        result, self.buffer = self.buffer[:count], self.buffer[count:]
        return result

    def send(self, payload: dict) -> None:
        data = json.dumps(payload, separators=(",", ":")).encode()
        mask = os.urandom(4)
        length = len(data)
        if length < 126:
            header = bytes((0x81, 0x80 | length))
        elif length < 65536:
            header = bytes((0x81, 0xFE)) + struct.pack("!H", length)
        else:
            header = bytes((0x81, 0xFF)) + struct.pack("!Q", length)
        masked = bytes(value ^ mask[index % 4] for index, value in enumerate(data))
        self.sock.sendall(header + mask + masked)

    def receive(self) -> dict:
        while True:
            first, second = self._read(2)
            opcode = first & 0x0F
            length = second & 0x7F
            if length == 126:
                length = struct.unpack("!H", self._read(2))[0]
            elif length == 127:
                length = struct.unpack("!Q", self._read(8))[0]
            if length > MAX_MESSAGE_BYTES:
                raise ObsError("OBS WebSocket message is too large")
            mask = self._read(4) if second & 0x80 else b""
            payload = self._read(length)
            if mask:
                payload = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
            if opcode == 0x8:
                raise ObsError("OBS closed the connection")
            if opcode == 0x9:
                self._send_control(0xA, payload)
                continue
            if opcode == 0x1:
                return json.loads(payload)

    def _send_control(self, opcode: int, data: bytes) -> None:
        mask = os.urandom(4)
        masked = bytes(value ^ mask[index % 4] for index, value in enumerate(data))
        self.sock.sendall(bytes((0x80 | opcode, 0x80 | len(data))) + mask + masked)

    def close(self) -> None:
        self.sock.close()


class Obs:
    def __init__(self) -> None:
        try:
            config = json.loads(OBS_CONFIG.read_text())
        except (OSError, json.JSONDecodeError):
            config = {}
        port = int(config.get("server_port", DEFAULT_PORT))
        if port < 1 or port > 65535:
            raise ObsError("invalid OBS WebSocket port")
        self.ws = WebSocket(port)
        hello = self.ws.receive()
        if hello.get("op") != 0:
            raise ObsError("unexpected response from OBS")
        identification: dict = {"rpcVersion": 1}
        authentication = hello.get("d", {}).get("authentication")
        if authentication:
            try:
                password = str(config["server_password"])
            except KeyError as exc:
                raise ObsError("could not read the OBS WebSocket password") from exc
            secret = base64.b64encode(
                hashlib.sha256((password + authentication["salt"]).encode()).digest()
            ).decode()
            identification["authentication"] = base64.b64encode(
                hashlib.sha256((secret + authentication["challenge"]).encode()).digest()
            ).decode()
        self.ws.send({"op": 1, "d": identification})
        identified = self.ws.receive()
        if identified.get("op") != 2:
            raise ObsError("OBS WebSocket authentication failed")

    def request(self, request_type: str, request_data: dict | None = None) -> dict:
        request_id = str(uuid.uuid4())
        self.ws.send(
            {
                "op": 6,
                "d": {
                    "requestType": request_type,
                    "requestId": request_id,
                    "requestData": request_data or {},
                },
            }
        )
        while True:
            response = self.ws.receive()
            data = response.get("d", {})
            if response.get("op") != 7 or data.get("requestId") != request_id:
                continue
            status = data.get("requestStatus", {})
            if not status.get("result"):
                raise ObsError(status.get("comment") or f"OBS request {request_type} failed")
            return data.get("responseData", {})

    def camera_item(self) -> tuple[str, int, str]:
        scene = self.request("GetCurrentProgramScene")["currentProgramSceneName"]
        items = self.request("GetSceneItemList", {"sceneName": scene}).get("sceneItems", [])
        candidates = [
            item
            for item in items
            if "anker" in item.get("sourceName", "").lower()
            or "powerconf" in item.get("sourceName", "").lower()
        ]
        if not candidates:
            raise ObsError("Anker camera source is not in the current OBS scene")
        item = candidates[0]
        return scene, int(item["sceneItemId"]), str(item["sourceName"])

    def transform(self, scene: str, item_id: int) -> dict:
        return self.request(
            "GetSceneItemTransform", {"sceneName": scene, "sceneItemId": item_id}
        )["sceneItemTransform"]

    def set_crop(self, scene: str, item_id: int, crop: dict) -> None:
        self.request(
            "SetSceneItemTransform",
            {
                "sceneName": scene,
                "sceneItemId": item_id,
                "sceneItemTransform": crop,
            },
        )


def rounded_pair(total: int) -> tuple[int, int]:
    first = total // 2
    return first, total - first


def pan_crop(transform: dict, dx: float, dy: float, width: float, height: float) -> dict:
    """Map one preview-sized gesture to the complete movable crop range."""
    if width <= 0 or height <= 0:
        raise ObsError("invalid preview size")
    left = int(round(transform.get("cropLeft", 0)))
    right = int(round(transform.get("cropRight", 0)))
    top = int(round(transform.get("cropTop", 0)))
    bottom = int(round(transform.get("cropBottom", 0)))
    total_x = left + right
    total_y = top + bottom
    left = max(0, min(total_x, round(left - dx * total_x / width)))
    top = max(0, min(total_y, round(top - dy * total_y / height)))
    return {
        "cropLeft": left,
        "cropRight": total_x - left,
        "cropTop": top,
        "cropBottom": total_y - top,
    }


def status_payload(
    obs: Obs,
    scene: str,
    item_id: int,
    source_name: str,
    transform: dict,
) -> dict:
    video = obs.request("GetVideoSettings")
    virtual_camera = obs.request("GetVirtualCamStatus")
    numerator = int(video.get("fpsNumerator", 0))
    denominator = int(video.get("fpsDenominator", 1)) or 1
    return {
        "connected": True,
        "scene": scene,
        "source_name": source_name,
        "item_id": item_id,
        "source_width": int(round(transform.get("sourceWidth", 0))),
        "source_height": int(round(transform.get("sourceHeight", 0))),
        "output_width": int(video.get("outputWidth", 0)),
        "output_height": int(video.get("outputHeight", 0)),
        "base_width": int(video.get("baseWidth", 0)),
        "base_height": int(video.get("baseHeight", 0)),
        "fps": round(numerator / denominator, 2),
        "virtual_camera_active": bool(virtual_camera.get("outputActive")),
        "crop_left": int(round(transform.get("cropLeft", 0))),
        "crop_right": int(round(transform.get("cropRight", 0))),
        "crop_top": int(round(transform.get("cropTop", 0))),
        "crop_bottom": int(round(transform.get("cropBottom", 0))),
    }


class FramingSession:
    """Keep OBS discovery and authentication out of the pointer-move path."""

    def __init__(self, obs: Obs | None = None) -> None:
        self.obs = obs or Obs()
        self.scene, self.item_id, self.source_name = self.obs.camera_item()
        self.transform = self.obs.transform(self.scene, self.item_id)
        self.payload = status_payload(
            self.obs,
            self.scene,
            self.item_id,
            self.source_name,
            self.transform,
        )

    def _update_crop_payload(self) -> None:
        self.payload.update(
            {
                "crop_left": int(round(self.transform.get("cropLeft", 0))),
                "crop_right": int(round(self.transform.get("cropRight", 0))),
                "crop_top": int(round(self.transform.get("cropTop", 0))),
                "crop_bottom": int(round(self.transform.get("cropBottom", 0))),
            }
        )

    def handle(self, command: str, arguments: list) -> dict:
        if command == "state":
            self.transform = self.obs.transform(self.scene, self.item_id)
            self._update_crop_payload()
            return dict(self.payload)

        if command == "pan":
            if len(arguments) != 4:
                raise ObsError("pan requires DX DY WIDTH HEIGHT")
            dx, dy, width, height = map(float, arguments)
            crop = pan_crop(self.transform, dx, dy, width, height)
        elif command == "center":
            left = int(round(self.transform.get("cropLeft", 0)))
            right = int(round(self.transform.get("cropRight", 0)))
            top = int(round(self.transform.get("cropTop", 0)))
            bottom = int(round(self.transform.get("cropBottom", 0)))
            left, right = rounded_pair(left + right)
            top, bottom = rounded_pair(top + bottom)
            crop = {
                "cropLeft": left,
                "cropRight": right,
                "cropTop": top,
                "cropBottom": bottom,
            }
        else:
            raise ObsError(f"unsupported command: {command}")

        self.obs.set_crop(self.scene, self.item_id, crop)
        self.transform.update(crop)
        self._update_crop_payload()
        return dict(self.payload)

    def close(self) -> None:
        self.obs.ws.close()


def framing(command: str, arguments: list[str]) -> dict:
    obs = Obs()
    try:
        scene, item_id, source_name = obs.camera_item()
        transform = obs.transform(scene, item_id)
        left = int(round(transform.get("cropLeft", 0)))
        right = int(round(transform.get("cropRight", 0)))
        top = int(round(transform.get("cropTop", 0)))
        bottom = int(round(transform.get("cropBottom", 0)))
        total_x = left + right
        total_y = top + bottom

        if command == "pan":
            if len(arguments) != 4:
                raise ObsError("pan requires DX DY WIDTH HEIGHT")
            dx, dy, width, height = map(float, arguments)
            obs.set_crop(scene, item_id, pan_crop(transform, dx, dy, width, height))
        elif command == "center":
            left, right = rounded_pair(total_x)
            top, bottom = rounded_pair(total_y)
            obs.set_crop(
                scene,
                item_id,
                {"cropLeft": left, "cropRight": right, "cropTop": top, "cropBottom": bottom},
            )
        elif command != "state":
            raise ObsError(f"unsupported command: {command}")

        if command in {"pan", "center"}:
            transform = obs.transform(scene, item_id)
        return status_payload(obs, scene, item_id, source_name, transform)
    finally:
        obs.ws.close()


def serve() -> int:
    """Serve newline-delimited framing requests over one OBS connection."""
    session = None
    try:
        try:
            session = FramingSession()
            print(json.dumps(session.payload, separators=(",", ":")), flush=True)
        except (ObsError, OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
            print(json.dumps({"connected": False, "error": str(exc)}, separators=(",", ":")), flush=True)

        for line in sys.stdin:
            sequence = None
            try:
                request = json.loads(line)
                if not isinstance(request, dict):
                    raise ValueError("framing request must be an object")
                sequence = request.get("sequence")
                if session is None:
                    session = FramingSession()
                response = session.handle(
                    str(request.get("command", "state")),
                    request.get("arguments", []),
                )
                if sequence is not None:
                    response["sequence"] = sequence
            except (ObsError, OSError, KeyError, ValueError, TypeError, json.JSONDecodeError) as exc:
                if session is not None:
                    try:
                        session.close()
                    except OSError:
                        pass
                    session = None
                response = {"connected": False, "error": str(exc)}
                if sequence is not None:
                    response["sequence"] = sequence
            print(json.dumps(response, separators=(",", ":")), flush=True)
    finally:
        if session is not None:
            session.close()
    return 0


def main() -> int:
    command = sys.argv[1] if len(sys.argv) > 1 else "state"
    if command == "serve":
        return serve()
    try:
        print(json.dumps(framing(command, sys.argv[2:]), separators=(",", ":")))
        return 0
    except (ObsError, OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"connected": False, "error": str(exc)}, separators=(",", ":")))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

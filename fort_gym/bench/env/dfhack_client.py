"""Lightweight DFHack Remote client for the alpha integration."""

from __future__ import annotations

import json
import os
import socket
import struct
import time
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ..dfhack_backend import advance_ticks_exact
from ..dfhack_exec import read_game_state as cli_read_game_state

try:  # pragma: no cover - optional dependency
    from google.protobuf.message import Message  # type: ignore
except ModuleNotFoundError:  # noqa: pragma: no cover
    Message = Any  # type: ignore

try:  # pragma: no cover - optional dependency
    from .remote_proto import ProtoLoadError, ensure_proto_modules
except Exception:  # noqa: pragma: no cover
    class ProtoLoadError(RuntimeError):
        pass

    def ensure_proto_modules():  # type: ignore
        raise ProtoLoadError(
            "Missing DFHack protobuf bindings. Run `make proto` before using the DFHack backend."
        )


class DFHackError(RuntimeError):
    """Generic DFHack client failure."""


class DFHackUnavailableError(DFHackError):
    """Raised when the remote DFHack interface is not reachable."""


def screen_to_text(screen: Dict[str, Any]) -> str:
    """Convert CopyScreen response to plain text string.

    The tiles array from CopyScreen is in column-major order (column 0 row 0-24,
    then column 1 row 0-24, etc.). Each tile is [character, foreground, background].

    Args:
        screen: Dict with 'width', 'height', 'tiles' from get_screen()

    Returns:
        Multi-line string representation of the screen
    """
    width = screen.get("width", 80)
    height = screen.get("height", 25)
    tiles = screen.get("tiles", [])

    if not tiles:
        return "(empty screen)"

    lines = []
    for row in range(height):
        line_chars = []
        for col in range(width):
            # Column-major: index = col * height + row
            idx = col * height + row
            if idx < len(tiles):
                char_code = tiles[idx][0]
                # Convert to printable ASCII, use space for non-printables
                if 32 <= char_code < 127:
                    line_chars.append(chr(char_code))
                elif char_code == 0:
                    line_chars.append(' ')
                else:
                    # CP437 extended chars - map common ones, otherwise use placeholder
                    # Common DF characters: walls, floors, etc.
                    cp437_map = {
                        176: '#',  # Light shade (wall)
                        177: '#',  # Medium shade
                        178: '#',  # Dark shade
                        219: '#',  # Full block
                        220: '_',  # Lower half block
                        223: '-',  # Upper half block
                        249: '.',  # Bullet (floor)
                        250: '.',  # Interpunct
                        254: '*',  # Square
                        # Box drawing
                        179: '|', 180: '+', 191: '+', 192: '+',
                        193: '+', 194: '+', 195: '+', 196: '-',
                        197: '+', 217: '+', 218: '+',
                        # Arrows
                        24: '^', 25: 'v', 26: '>', 27: '<',
                        # Other common
                        1: '@',    # Smiley (dwarf)
                        2: '@',    # Inverse smiley
                        3: '<3',   # Heart
                        4: '<>',   # Diamond
                        5: '*',    # Club
                        6: '*',    # Spade
                        7: 'o',    # Bullet
                        15: '*',   # Sun
                        30: '^',   # Up triangle
                        31: 'v',   # Down triangle
                    }
                    line_chars.append(cp437_map.get(char_code, '?'))
            else:
                line_chars.append(' ')
        lines.append(''.join(line_chars).rstrip())

    # Remove trailing empty lines
    while lines and not lines[-1]:
        lines.pop()

    return '\n'.join(lines)


@dataclass
class CallDescriptor:
    method: str
    input_cls: type[Message]
    output_cls: type[Message]
    plugin: str = ""


class DFHackClient:
    """Blocking TCP client for DFHack remote RPC with lua bridges."""

    MAGIC_REQUEST = b"DFHack?\n"
    MAGIC_REPLY = b"DFHack!\n"
    HEADER_STRUCT = struct.Struct("<hHI")  # id, padding, size

    RPC_BIND_METHOD = 0
    RPC_RUN_COMMAND = 1

    RPC_REPLY_RESULT = -1
    RPC_REPLY_FAIL = -2
    RPC_REPLY_TEXT = -3
    RPC_REQUEST_QUIT = -4

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        *,
        timeout: float = 5.0,
        retries: int = 3,
    ) -> None:
        self.host = host or os.environ.get("DFHACK_HOST", "127.0.0.1")
        self.port = port or int(os.environ.get("DFHACK_PORT", "5000"))
        self.timeout = timeout
        self.retries = retries
        self._sock: Optional[socket.socket] = None
        self._core = None
        self._fortress = None
        self._method_cache: dict[Tuple[str, str, str, str], int] = {}
        self._capture_text: Optional[List[str]] = None
        self._last_tick_info: Dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Connection orchestration
    # ------------------------------------------------------------------
    def connect(self, host: Optional[str] = None, port: Optional[int] = None) -> None:
        if self._sock is not None:
            return

        self.host = host or self.host
        self.port = port or self.port

        try:
            modules = ensure_proto_modules()
        except ProtoLoadError as exc:
            raise DFHackUnavailableError(str(exc)) from exc

        # Check if protos are actually loaded (empty dict if DF_PROTO_ENABLED=0)
        if not modules:
            raise DFHackUnavailableError(
                "DFHack protobuf bindings disabled (DF_PROTO_ENABLED=0). "
                "Set DF_PROTO_ENABLED=1 to enable DFHack backend, or use backend='mock' for local development."
            )

        self._core = modules["core"]
        self._fortress = modules["fortress"]

        last_error: Optional[Exception] = None
        for attempt in range(self.retries):
            try:
                sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
                sock.settimeout(self.timeout)
                self._sock = sock
                self._handshake()
                return
            except OSError as exc:
                last_error = exc
                time.sleep(0.25 * (attempt + 1))

        raise DFHackUnavailableError(
            f"Unable to connect to DFHack remote interface at {self.host}:{self.port}: {last_error}"
        )

    def close(self) -> None:
        if not self._sock:
            return

        with suppress(Exception):
            header = self.HEADER_STRUCT.pack(self.RPC_REQUEST_QUIT, 0, 0)
            self._sock.sendall(header)
        with suppress(Exception):
            self._sock.close()
        self._sock = None

    # ------------------------------------------------------------------
    # High-level helpers
    # ------------------------------------------------------------------
    def pause(self) -> None:
        self._ensure_connection()
        self._call(
            CallDescriptor(
                "SetPauseState",
                self._fortress.SingleBool,
                self._core.EmptyMessage,
                "RemoteFortressReader",
            ),
            {"Value": True},
        )

    def resume(self) -> None:
        self._ensure_connection()
        self._call(
            CallDescriptor(
                "SetPauseState",
                self._fortress.SingleBool,
                self._core.EmptyMessage,
                "RemoteFortressReader",
            ),
            {"Value": False},
        )

    def advance(self, ticks: int) -> Dict[str, Any]:
        self._ensure_connection()
        if ticks <= 0:
            self._last_tick_info = {"ok": False, "error": "invalid_ticks"}
            return self.get_state()

        tick_info = advance_ticks_exact(int(ticks), repause=True)
        self._last_tick_info = dict(tick_info) if isinstance(tick_info, dict) else tick_info

        return self.get_state()

    @property
    def last_tick_info(self) -> Dict[str, Any]:
        return self._last_tick_info

    def get_state(self) -> Dict[str, Any]:
        self._ensure_connection()

        # Use CLI-based state reading since RPC doesn't capture dfhack.print output
        data = cli_read_game_state()
        if not data:
            data = {
                "time": 0,
                "population": 0,
                "stocks": {"food": 0, "drink": 0, "wood": 0, "stone": 0},
                "recent_events": [],
            }

        data.setdefault("risks", [])
        data.setdefault("reminders", [])
        data.setdefault("map_bounds", (0, 0, 0))
        return data

    def get_screen(self) -> Dict[str, Any]:
        """Capture the current DF screen via RemoteFortressReader CopyScreen RPC.

        Returns a dict with width, height, and tiles array where each tile is
        [character, foreground_color, background_color].
        """
        self._ensure_connection()
        response = self._call(
            CallDescriptor(
                "CopyScreen",
                self._core.EmptyMessage,
                self._fortress.ScreenCapture,
                "RemoteFortressReader",
            )
        )
        tiles = []
        for tile in response.tiles:
            tiles.append([tile.character, tile.foreground, tile.background])
        return {
            "width": response.width,
            "height": response.height,
            "tiles": tiles,
        }

    def get_screen_text(self) -> str:
        """Capture current DF screen and return as plain text string.

        Returns an 80x25 (or actual dimensions) text representation of the screen,
        suitable for passing to an LLM agent.
        """
        screen = self.get_screen()
        return screen_to_text(screen)

    def designate_rect(self, x1: int, y1: int, z1: int, x2: int, y2: int, z2: int) -> Tuple[bool, Optional[str]]:
        self._ensure_connection()
        script = """
local args = {...}
local x1 = tonumber(args[1])
local y1 = tonumber(args[2])
local z1 = tonumber(args[3])
local x2 = tonumber(args[4])
local y2 = tonumber(args[5])
local z2 = tonumber(args[6])
if not (x1 and y1 and z1 and x2 and y2 and z2) then
  qerror('invalid rectangle for dig')
end
local map = require('dfhack.maps')
local df = df
for z = math.min(z1, z2), math.max(z1, z2) do
  for x = math.min(x1, x2), math.max(x1, x2) do
    for y = math.min(y1, y2), math.max(y1, y2) do
      local block = map.getTileBlock(x, y, z)
      if block then
        local des = block.designation[x % 16][y % 16]
        des.dig = df.tile_dig_designation.Default
      end
    end
  end
end
"""
        try:
            self._run_command(
                "lua",
                [script, str(x1), str(y1), str(z1), str(x2), str(y2), str(z2)],
            )
            self._run_command("dig-now")
            return True, None
        except DFHackError as exc:
            return False, str(exc)

    def queue_manager_order(self, job: str, quantity: int) -> Tuple[bool, Optional[str]]:
        self._ensure_connection()
        if not job:
            return False, "Missing job name"
        try:
            self._run_command("orders", ["add", job, str(quantity)])
            return True, None
        except DFHackError as exc:
            return False, str(exc)

    def place_building(
        self,
        kind: str,
        x: int,
        y: int,
        z: int,
        materials: Optional[List[str]] = None,
    ) -> Tuple[bool, Optional[str]]:
        self._ensure_connection()
        try:
            args = [kind, str(x), str(y), str(z)]
            if materials:
                args.extend(materials)
            self._run_command("build-now", args)
            return True, None
        except DFHackError as exc:
            return False, str(exc)

    # ------------------------------------------------------------------
    # Internal RPC helpers
    # ------------------------------------------------------------------
    def _ensure_connection(self) -> None:
        if self._sock is None:
            raise DFHackUnavailableError("DFHack client not connected")
        if self._core is None or self._fortress is None:
            raise DFHackUnavailableError("DFHack protobuf modules not loaded")

    def _handshake(self) -> None:
        assert self._sock is not None
        self._sock.sendall(self.MAGIC_REQUEST + struct.pack("<i", 1))
        reply = self._read_exact(12)
        if reply[:8] != self.MAGIC_REPLY:
            raise DFHackError("Unexpected DFHack handshake response")

    def _read_exact(self, size: int) -> bytes:
        assert self._sock is not None
        data = b""
        remaining = size
        while remaining:
            chunk = self._sock.recv(remaining)
            if not chunk:
                raise DFHackError("Connection closed by DFHack")
            data += chunk
            remaining -= len(chunk)
        return data

    def _send_request(self, method_id: int, payload: Optional[Message]) -> None:
        assert self._sock is not None
        body = payload.SerializeToString() if payload is not None else b""
        header = self.HEADER_STRUCT.pack(method_id, 0, len(body))
        self._sock.sendall(header + body)

    def _bind_method(self, descriptor: CallDescriptor) -> int:
        key = (
            descriptor.method,
            descriptor.input_cls.DESCRIPTOR.full_name,
            descriptor.output_cls.DESCRIPTOR.full_name,
            descriptor.plugin,
        )
        if key in self._method_cache:
            return self._method_cache[key]

        request = self._core.CoreBindRequest(
            method=descriptor.method,
            input_msg=descriptor.input_cls.DESCRIPTOR.full_name,
            output_msg=descriptor.output_cls.DESCRIPTOR.full_name,
        )
        if descriptor.plugin:
            request.plugin = descriptor.plugin

        self._send_request(self.RPC_BIND_METHOD, request)
        response = self._read_reply(self._core.CoreBindReply)
        method_id = int(response.assigned_id)
        self._method_cache[key] = method_id
        return method_id

    def _read_reply(self, output_cls: type[Message]) -> Message:
        assert self._sock is not None
        while True:
            header = self._read_exact(self.HEADER_STRUCT.size)
            rpc_id, _, size = self.HEADER_STRUCT.unpack(header)
            payload = self._read_exact(size)

            if rpc_id == self.RPC_REPLY_TEXT:
                text = self._core.CoreTextNotification()
                text.ParseFromString(payload)
                if self._capture_text is not None and getattr(text, "text", ""):
                    self._capture_text.append(text.text)
                continue
            if rpc_id == self.RPC_REPLY_FAIL:
                code = struct.unpack("<i", payload)[0]
                raise DFHackError(f"DFHack RPC failure (code={code})")
            if rpc_id == self.RPC_REPLY_RESULT:
                message = output_cls()
                message.ParseFromString(payload)
                return message

            raise DFHackError(f"Unexpected RPC id {rpc_id}")

    def _call(
        self,
        descriptor: CallDescriptor,
        field_values: Optional[Dict[str, Any]] = None,
        message: Optional[Message] = None,
    ) -> Message:
        method_id = self._bind_method(descriptor)
        payload = message or descriptor.input_cls()
        if field_values:
            for name, value in field_values.items():
                setattr(payload, name, value)
        self._send_request(method_id, payload)
        return self._read_reply(descriptor.output_cls)

    def _run_command(
        self,
        command: str,
        arguments: Optional[Iterable[str]] = None,
        *,
        capture_output: bool = False,
    ) -> Optional[List[str]]:
        request = self._core.CoreRunCommandRequest(command=command)
        if arguments:
            request.arguments.extend(arguments)
        self._capture_text = [] if capture_output else None
        self._send_request(self.RPC_RUN_COMMAND, request)
        self._read_reply(self._core.EmptyMessage)
        output = self._capture_text
        self._capture_text = None
        return output if capture_output else None


__all__ = [
    "DFHackClient",
    "DFHackError",
    "DFHackUnavailableError",
    "screen_to_text",
]

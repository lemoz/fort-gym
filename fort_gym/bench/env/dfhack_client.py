"""Lightweight DFHack Remote client for the alpha integration."""

from __future__ import annotations

import os
import re
import socket
import struct
import time
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ..dfhack_backend import advance_ticks_exact, read_work_metrics
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


_RUNTIME_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_RUNTIME_NONCE_RE = re.compile(r"^[a-f0-9]{32,64}$")
_RUNTIME_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_RUNTIME_IDENTITY_PREFIX = "FORTGYM_RUNTIME_IDENTITY\t"
_RUNTIME_IDENTITY_LUA = r"""
local f = io.open('/run/fortgym/run-identity.tsv', 'r')
if not f then
  qerror('fortgym runtime identity unavailable')
end
local identity = f:read('*l') or ''
f:close()
dfhack.print('FORTGYM_RUNTIME_IDENTITY\t' .. identity)
""".strip()


def _validated_runtime_identity(
    *,
    run_id: str | None,
    nonce: str | None,
    contract_sha256: str | None,
    seed_tree_sha256: str | None,
    seed_world_sha256: str | None,
    image_manifest_sha256: str | None,
    image_config_sha256: str | None,
    image_archive_sha256: str | None,
) -> tuple[str, str, str, str, str, str, str, str] | None:
    """Validate an all-or-none expected runtime identity.

    A supervised worker receives this identity through its sanitized process
    environment. Legacy callers have no identity fields and retain the old
    connection behavior.
    """

    values = (
        run_id,
        nonce,
        contract_sha256,
        seed_tree_sha256,
        seed_world_sha256,
        image_manifest_sha256,
        image_config_sha256,
        image_archive_sha256,
    )
    if not any(value is not None for value in values):
        return None
    if not all(isinstance(value, str) and value for value in values):
        raise ValueError(
            "expected DFHack runtime identity requires run ID, nonce, contract, "
            "seed-tree, seed-world, image-manifest, image-config, and image-archive digests"
        )
    assert run_id is not None
    assert nonce is not None
    assert contract_sha256 is not None
    assert seed_tree_sha256 is not None
    assert seed_world_sha256 is not None
    assert image_manifest_sha256 is not None
    assert image_config_sha256 is not None
    assert image_archive_sha256 is not None
    if not _RUNTIME_RUN_ID_RE.fullmatch(run_id):
        raise ValueError("expected DFHack runtime run ID is invalid")
    if not _RUNTIME_NONCE_RE.fullmatch(nonce):
        raise ValueError("expected DFHack runtime nonce is invalid")
    digests = {
        "contract": contract_sha256,
        "seed-tree": seed_tree_sha256,
        "seed-world": seed_world_sha256,
        "image-manifest": image_manifest_sha256,
        "image-config": image_config_sha256,
        "image-archive": image_archive_sha256,
    }
    for label, digest in digests.items():
        if not _RUNTIME_SHA256_RE.fullmatch(digest):
            raise ValueError(f"expected DFHack runtime {label} digest is invalid")
    return (
        run_id,
        nonce,
        contract_sha256,
        seed_tree_sha256,
        seed_world_sha256,
        image_manifest_sha256,
        image_config_sha256,
        image_archive_sha256,
    )


def _runtime_identity_from_environment() -> (
    tuple[str, str, str, str, str, str, str, str] | None
):
    """Load the complete supervisor identity, or preserve a true legacy launch."""

    prepared = os.environ.get("FORT_GYM_RUNTIME_PREPARED")
    values = {
        "run_id": os.environ.get("FORT_GYM_RUN_ID"),
        "nonce": os.environ.get("FORT_GYM_RUN_NONCE"),
        "contract_sha256": os.environ.get("FORT_GYM_RUN_CONTRACT_SHA256"),
        "seed_tree_sha256": os.environ.get("FORT_GYM_EXPECTED_SEED_TREE_SHA256"),
        "seed_world_sha256": os.environ.get("FORT_GYM_EXPECTED_SEED_WORLD_SHA256"),
        "image_manifest_sha256": os.environ.get(
            "FORT_GYM_EXPECTED_IMAGE_MANIFEST_SHA256"
        ),
        "image_config_sha256": os.environ.get("FORT_GYM_EXPECTED_IMAGE_CONFIG_SHA256"),
        "image_archive_sha256": os.environ.get(
            "FORT_GYM_EXPECTED_IMAGE_ARCHIVE_SHA256"
        ),
    }
    if prepared is None and not any(value is not None for value in values.values()):
        return None
    if prepared != "1":
        raise ValueError(
            "expected DFHack runtime identity requires FORT_GYM_RUNTIME_PREPARED=1"
        )
    return _validated_runtime_identity(**values)


def _tile_to_char(tile: List[int]) -> str:
    char_code = tile[0]
    # Convert to printable ASCII, use space for non-printables
    if 32 <= char_code < 127:
        return chr(char_code)
    if char_code == 0:
        return " "

    # CP437 extended chars - map common ones, otherwise use placeholder.
    # Common DF characters: walls, floors, dwarves, cursor markers, etc.
    cp437_map = {
        176: "#",  # Light shade (wall)
        177: "#",  # Medium shade
        178: "#",  # Dark shade
        219: "#",  # Full block
        220: "_",  # Lower half block
        223: "-",  # Upper half block
        249: ".",  # Bullet (floor)
        250: ".",  # Interpunct
        254: "*",  # Square
        # Box drawing
        179: "|",
        180: "+",
        191: "+",
        192: "+",
        193: "+",
        194: "+",
        195: "+",
        196: "-",
        197: "+",
        217: "+",
        218: "+",
        # Arrows
        24: "^",
        25: "v",
        26: ">",
        27: "<",
        # Other common
        1: "@",  # Smiley (dwarf)
        2: "@",  # Inverse smiley
        3: "<3",  # Heart
        4: "<>",  # Diamond
        5: "*",  # Club
        6: "*",  # Spade
        7: "o",  # Bullet
        15: "*",  # Sun
        30: "^",  # Up triangle
        31: "v",  # Down triangle
    }
    return cp437_map.get(char_code, "?")


def _tile_attr(tile: List[int]) -> Tuple[Optional[int], Optional[int]]:
    fg = tile[1] if len(tile) > 1 else None
    bg = tile[2] if len(tile) > 2 else None
    return fg, bg


def _screen_rows(
    screen: Dict[str, Any],
) -> List[Tuple[str, List[Tuple[Optional[int], Optional[int]]]]]:
    width = screen.get("width", 80)
    height = screen.get("height", 25)
    tiles = screen.get("tiles", [])

    rows: List[Tuple[str, List[Tuple[Optional[int], Optional[int]]]]] = []
    for row in range(height):
        line_chars = []
        attrs: List[Tuple[Optional[int], Optional[int]]] = []
        for col in range(width):
            # Column-major: index = col * height + row
            idx = col * height + row
            if idx < len(tiles):
                tile = tiles[idx]
                line_chars.append(_tile_to_char(tile))
                attrs.append(_tile_attr(tile))
            else:
                line_chars.append(" ")
                attrs.append((None, None))
        rows.append(("".join(line_chars), attrs))
    return rows


def screen_selection_hints(
    screen: Dict[str, Any],
    *,
    max_rows: int = 8,
) -> List[Dict[str, Any]]:
    """Return rows with visible CopyScreen background highlighting.

    CopyScreen exposes each tile as [character, foreground, background], but the
    plain text view necessarily discards color. DF uses background color for
    menu highlights and cursors, so these rows preserve raw visible information
    that would otherwise be lost before the agent sees the screen.
    """
    rows = _screen_rows(screen)
    hints: List[Dict[str, Any]] = []
    for row_index, (raw_line, attrs) in enumerate(rows):
        if not raw_line.strip():
            continue
        line_text = raw_line.rstrip()
        if row_index == 0 and ("PAUSED" in line_text or "Dwarf Fortress" in line_text):
            continue

        run_start: Optional[int] = None
        run_attr: Tuple[Optional[int], Optional[int]] | None = None
        runs: List[Tuple[int, int, Tuple[Optional[int], Optional[int]]]] = []
        for col, (_ch, attr) in enumerate(zip(raw_line, attrs)):
            bg = attr[1]
            is_highlighted = bg not in (None, 0)
            if is_highlighted and run_start is None:
                run_start = col
                run_attr = attr
            elif (not is_highlighted or attr != run_attr) and run_start is not None:
                runs.append((run_start, col - 1, run_attr or (None, None)))
                run_start = col if is_highlighted else None
                run_attr = attr if is_highlighted else None
        if run_start is not None:
            runs.append((run_start, len(raw_line) - 1, run_attr or (None, None)))

        for start, end, (fg, bg) in runs:
            if end - start + 1 < 2:
                continue
            highlighted_text = raw_line[start : end + 1].strip()
            hint_text = highlighted_text or line_text.strip()
            if sum(1 for ch in hint_text if ch.isalpha()) < 2:
                continue
            hints.append(
                {
                    "row": row_index,
                    "cols": [start, end],
                    "text": hint_text,
                    "line": line_text.strip(),
                    "fg": fg,
                    "bg": bg,
                }
            )
            if len(hints) >= max_rows:
                break
        if len(hints) >= max_rows:
            break
    return hints


def screen_visual_hints_text(screen: Dict[str, Any]) -> str:
    hints = screen_selection_hints(screen)
    if not hints:
        return ""
    lines = [
        "== SCREEN VISUAL HINTS ==",
        (
            "Rows below have non-default CopyScreen background colors. "
            "Treat them as visible highlight/cursor/menu-selection clues, "
            "not as recommended actions."
        ),
    ]
    for hint in hints:
        start, end = hint["cols"]
        lines.append(
            f"- row {hint['row']} cols {start}-{end} "
            f"fg={hint['fg']} bg={hint['bg']}: {hint['text']}"
        )
    return "\n".join(lines)


def screen_to_text(screen: Dict[str, Any]) -> str:
    """Convert CopyScreen response to plain text string.

    The tiles array from CopyScreen is in column-major order (column 0 row 0-24,
    then column 1 row 0-24, etc.). Each tile is [character, foreground, background].

    Args:
        screen: Dict with 'width', 'height', 'tiles' from get_screen()

    Returns:
        Multi-line string representation of the screen
    """
    height = screen.get("height", 25)
    if not screen.get("tiles"):
        return "(empty screen)"

    lines = [line.rstrip() for line, _attrs in _screen_rows(screen)[:height]]

    # Remove trailing empty lines
    while lines and not lines[-1]:
        lines.pop()

    return "\n".join(lines)


def screen_to_text_with_visual_hints(screen: Dict[str, Any]) -> str:
    """Convert CopyScreen response to text plus raw visual highlight metadata."""
    text = screen_to_text(screen)
    visual_hints = screen_visual_hints_text(screen)
    if not visual_hints:
        return text
    return f"{text}\n\n{visual_hints}"


@dataclass
class CallDescriptor:
    method: str
    input_cls: type[Message]
    output_cls: type[Message]
    plugin: str = ""


_MISSING_NOTIFICATION_FIELD = object()


def _text_notification_content(notification: Any) -> str:
    """Return text from a validated DFHack RPC text notification.

    DFHack 0.47.05-r8 encodes output as ``CoreTextNotification.fragments``
    where every fragment has a required ``text`` field. A direct ``text``
    attribute is retained only for compatibility with legacy client shims.
    """

    try:
        fragments = getattr(
            notification,
            "fragments",
            _MISSING_NOTIFICATION_FIELD,
        )
    except Exception as exc:
        raise DFHackError("Malformed DFHack RPC text notification") from exc

    if fragments is not _MISSING_NOTIFICATION_FIELD:
        if fragments is None or isinstance(fragments, (str, bytes, bytearray)):
            raise DFHackError("Malformed DFHack RPC text notification fragments")
        try:
            iterator = iter(fragments)
        except TypeError as exc:
            raise DFHackError("Malformed DFHack RPC text notification fragments") from exc

        chunks: list[str] = []
        try:
            for fragment in iterator:
                has_field = getattr(fragment, "HasField", None)
                if callable(has_field):
                    try:
                        has_text = bool(has_field("text"))
                    except (TypeError, ValueError) as exc:
                        raise DFHackError(
                            "Malformed DFHack RPC text notification fragment"
                        ) from exc
                    if not has_text:
                        raise DFHackError("Malformed DFHack RPC text notification fragment")
                value = getattr(fragment, "text", _MISSING_NOTIFICATION_FIELD)
                if not isinstance(value, str):
                    raise DFHackError("Malformed DFHack RPC text notification fragment")
                chunks.append(value)
        except DFHackError:
            raise
        except Exception as exc:
            raise DFHackError("Malformed DFHack RPC text notification fragments") from exc
        return "".join(chunks)

    try:
        direct_text = getattr(notification, "text", _MISSING_NOTIFICATION_FIELD)
    except Exception as exc:
        raise DFHackError("Malformed DFHack RPC text notification") from exc
    if isinstance(direct_text, str):
        return direct_text
    raise DFHackError("Malformed DFHack RPC text notification payload")


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
        expected_run_id: str | None = None,
        expected_nonce: str | None = None,
        expected_contract_sha256: str | None = None,
        expected_seed_tree_sha256: str | None = None,
        expected_seed_world_sha256: str | None = None,
        expected_image_manifest_sha256: str | None = None,
        expected_image_config_sha256: str | None = None,
        expected_image_archive_sha256: str | None = None,
    ) -> None:
        self.host = host or os.environ.get("DFHACK_HOST", "127.0.0.1")
        self.port = port or int(os.environ.get("DFHACK_PORT", "5000"))
        self.timeout = timeout
        self.retries = retries
        explicit_identity = (
            expected_run_id,
            expected_nonce,
            expected_contract_sha256,
            expected_seed_tree_sha256,
            expected_seed_world_sha256,
            expected_image_manifest_sha256,
            expected_image_config_sha256,
            expected_image_archive_sha256,
        )
        if any(value is not None for value in explicit_identity):
            self._expected_runtime_identity = _validated_runtime_identity(
                run_id=expected_run_id,
                nonce=expected_nonce,
                contract_sha256=expected_contract_sha256,
                seed_tree_sha256=expected_seed_tree_sha256,
                seed_world_sha256=expected_seed_world_sha256,
                image_manifest_sha256=expected_image_manifest_sha256,
                image_config_sha256=expected_image_config_sha256,
                image_archive_sha256=expected_image_archive_sha256,
            )
        else:
            self._expected_runtime_identity = _runtime_identity_from_environment()
        self._runtime_identity_verified = False
        self._sock: Optional[socket.socket] = None
        self._core = None
        self._fortress = None
        self._method_cache: dict[Tuple[str, str, str, str], int] = {}
        self._capture_text: Optional[List[str]] = None
        self._last_tick_info: Dict[str, Any] = {}
        self._work_rect: tuple[int, int, int, int, int, int] | None = None
        self._work_metrics_global_only = False

    def set_work_rect(self, rect: tuple[int, int, int, int, int, int] | None) -> None:
        """Set the bounded work rectangle used for live work metrics."""

        self._work_rect = rect

    def set_work_metrics_global_only(self, enabled: bool) -> None:
        """Suppress legacy target/plan geometry while keeping global work facts."""

        self._work_metrics_global_only = bool(enabled)

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
                sock = socket.create_connection(
                    (self.host, self.port), timeout=self.timeout
                )
                self._sock = sock
                sock.settimeout(self.timeout)
                self._handshake()
                self._attest_runtime_identity()
                return
            except (DFHackError, OSError) as exc:
                last_error = exc
                self.close()
                if attempt + 1 < self.retries:
                    time.sleep(0.25 * (attempt + 1))

        raise DFHackUnavailableError(
            f"Unable to connect to DFHack remote interface at {self.host}:{self.port}: {last_error}"
        )

    def close(self) -> None:
        sock = self._sock
        self._sock = None
        self._runtime_identity_verified = False
        self._capture_text = None
        self._method_cache.clear()
        if not sock:
            return

        with suppress(Exception):
            header = self.HEADER_STRUCT.pack(self.RPC_REQUEST_QUIT, 0, 0)
            sock.sendall(header)
        with suppress(Exception):
            sock.close()

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

    def advance(
        self,
        ticks: int,
        *,
        interrupt_on_viewscreen_transition: bool = False,
        viewscreen_before: str | None = None,
        max_advance_ticks: int | None = None,
    ) -> Dict[str, Any]:
        self._ensure_connection()
        if ticks <= 0:
            self._last_tick_info = {"ok": False, "error": "invalid_ticks"}
            return self.get_state()

        limit_options = (
            {"max_advance_ticks": max_advance_ticks}
            if max_advance_ticks is not None
            else {}
        )
        if interrupt_on_viewscreen_transition:
            tick_info = advance_ticks_exact(
                int(ticks),
                repause=True,
                interrupt_on_viewscreen_transition=True,
                viewscreen_before=viewscreen_before,
                **limit_options,
            )
        else:
            tick_info = advance_ticks_exact(int(ticks), repause=True, **limit_options)
        self._last_tick_info = (
            dict(tick_info) if isinstance(tick_info, dict) else tick_info
        )

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
                "year": 0,
                "year_tick": 0,
                "population": 0,
                "stocks": {"food": 0, "drink": 0, "wood": 0, "stone": 0},
                "recent_events": [],
            }

        data.setdefault("year", 0)
        data.setdefault("year_tick", data.get("time", 0))
        data.setdefault("risks", [])
        data.setdefault("reminders", [])
        data.setdefault("map_bounds", (0, 0, 0))
        data["work"] = read_work_metrics(
            self._work_rect,
            global_only=self._work_metrics_global_only,
        )
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

    def get_screen_text(self, *, include_visual_hints: bool = False) -> str:
        """Capture current DF screen and return as plain text string.

        Returns an 80x25 (or actual dimensions) text representation of the screen,
        suitable for passing to an LLM agent.
        """
        screen = self.get_screen()
        if include_visual_hints:
            return screen_to_text_with_visual_hints(screen)
        return screen_to_text(screen)

    def run_command(
        self,
        command: str,
        arguments: Iterable[str] | None = None,
        *,
        capture_output: bool = False,
    ) -> list[str] | None:
        """Run one DFHack command over the connected native RPC transport.

        A command is never replayed automatically: doing so could duplicate a
        mutating action. Transport and DFHack RPC failures close the connection
        and clear connection-scoped state so the supervisor can explicitly
        reconnect or terminate the run.
        """

        try:
            self._ensure_connection()
            return self._run_command(
                command,
                arguments,
                capture_output=capture_output,
            )
        except (DFHackError, OSError):
            self.close()
            raise

    def designate_rect(
        self, x1: int, y1: int, z1: int, x2: int, y2: int, z2: int
    ) -> Tuple[bool, Optional[str]]:
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

    def queue_manager_order(
        self, job: str, quantity: int
    ) -> Tuple[bool, Optional[str]]:
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
        except (DFHackError, OSError, TimeoutError) as exc:
            return False, str(exc)

    # ------------------------------------------------------------------
    # Internal RPC helpers
    # ------------------------------------------------------------------
    def _ensure_connection(self) -> None:
        if self._sock is None:
            raise DFHackUnavailableError("DFHack client not connected")
        if self._core is None or self._fortress is None:
            raise DFHackUnavailableError("DFHack protobuf modules not loaded")
        if self._expected_runtime_identity and not self._runtime_identity_verified:
            raise DFHackUnavailableError("DFHack runtime identity was not verified")

    def _attest_runtime_identity(self) -> None:
        """Fail closed if the connected DF process is not this worker's runtime.

        This read-only command runs immediately after the native RPC handshake,
        before the client can issue gameplay commands. It is intentionally not
        retried as a command; a failed connection attempt is discarded in full.
        """

        expected = self._expected_runtime_identity
        if expected is None:
            self._runtime_identity_verified = True
            return
        output = self._run_command(
            "lua",
            [_RUNTIME_IDENTITY_LUA],
            capture_output=True,
        )
        joined = "".join(output or [])
        candidates = [
            line[len(_RUNTIME_IDENTITY_PREFIX) :]
            for line in joined.splitlines()
            if line.startswith(_RUNTIME_IDENTITY_PREFIX)
        ]
        if len(candidates) != 1:
            raise DFHackError(
                "DFHack runtime identity attestation was missing or ambiguous"
            )
        observed = tuple(candidates[0].split("\t"))
        if len(observed) != 8 or observed != expected:
            raise DFHackError("DFHack runtime identity mismatch")
        self._runtime_identity_verified = True

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
                notification = self._core.CoreTextNotification()
                try:
                    notification.ParseFromString(payload)
                except Exception as exc:
                    raise DFHackError("Malformed DFHack RPC text notification") from exc
                content = _text_notification_content(notification)
                if self._capture_text is not None and content:
                    self._capture_text.append(content)
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
        try:
            self._send_request(self.RPC_RUN_COMMAND, request)
            self._read_reply(self._core.EmptyMessage)
            output = list(self._capture_text or [])
            return output if capture_output else None
        finally:
            self._capture_text = None


__all__ = [
    "DFHackClient",
    "DFHackError",
    "DFHackUnavailableError",
    "screen_selection_hints",
    "screen_to_text",
    "screen_to_text_with_visual_hints",
    "screen_visual_hints_text",
]

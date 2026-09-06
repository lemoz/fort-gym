from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from fort_gym.bench import dfhack_exec
from fort_gym.bench.env import dfhack_client as client_module
from fort_gym.bench.env.dfhack_client import DFHackClient

RUNTIME_IDENTITY_KWARGS = {
    "expected_run_id": "m1b-run-01",
    "expected_nonce": "a" * 32,
    "expected_contract_sha256": "b" * 64,
    "expected_seed_tree_sha256": "c" * 64,
    "expected_seed_world_sha256": "d" * 64,
    "expected_image_manifest_sha256": "e" * 64,
    "expected_image_config_sha256": "f" * 64,
    "expected_image_archive_sha256": "1" * 64,
}
RUNTIME_IDENTITY_FIELDS = (
    "m1b-run-01",
    "a" * 32,
    "b" * 64,
    "c" * 64,
    "d" * 64,
    "e" * 64,
    "f" * 64,
    "1" * 64,
)
RUNTIME_IDENTITY_TSV = "\t".join(RUNTIME_IDENTITY_FIELDS)
RUNTIME_IDENTITY_ENVIRONMENT = {
    "FORT_GYM_RUNTIME_PREPARED": "1",
    "FORT_GYM_RUN_ID": RUNTIME_IDENTITY_FIELDS[0],
    "FORT_GYM_RUN_NONCE": RUNTIME_IDENTITY_FIELDS[1],
    "FORT_GYM_RUN_CONTRACT_SHA256": RUNTIME_IDENTITY_FIELDS[2],
    "FORT_GYM_EXPECTED_SEED_TREE_SHA256": RUNTIME_IDENTITY_FIELDS[3],
    "FORT_GYM_EXPECTED_SEED_WORLD_SHA256": RUNTIME_IDENTITY_FIELDS[4],
    "FORT_GYM_EXPECTED_IMAGE_MANIFEST_SHA256": RUNTIME_IDENTITY_FIELDS[5],
    "FORT_GYM_EXPECTED_IMAGE_CONFIG_SHA256": RUNTIME_IDENTITY_FIELDS[6],
    "FORT_GYM_EXPECTED_IMAGE_ARCHIVE_SHA256": RUNTIME_IDENTITY_FIELDS[7],
}


class _FakeSocket:
    def __init__(self) -> None:
        self.closed = False
        self.timeout: float | None = None
        self.sent: list[bytes] = []

    def close(self) -> None:
        self.closed = True

    def sendall(self, payload: bytes) -> None:
        self.sent.append(payload)

    def settimeout(self, timeout: float) -> None:
        self.timeout = timeout


class _ReplySocket(_FakeSocket):
    def __init__(self, inbound: bytes) -> None:
        super().__init__()
        self.inbound = bytearray(inbound)

    def recv(self, size: int) -> bytes:
        if not self.inbound:
            return b""
        chunk = bytes(self.inbound[:size])
        del self.inbound[:size]
        return chunk


def _rpc_frame(rpc_id: int, payload: bytes) -> bytes:
    return DFHackClient.HEADER_STRUCT.pack(rpc_id, 0, len(payload)) + payload


def _core_protocol_047() -> SimpleNamespace:
    """Build the exact 0.47 text-notification shape as dynamic messages."""

    descriptor_pb2 = pytest.importorskip("google.protobuf.descriptor_pb2")
    descriptor_pool = pytest.importorskip("google.protobuf.descriptor_pool")
    message_factory = pytest.importorskip("google.protobuf.message_factory")

    file_descriptor = descriptor_pb2.FileDescriptorProto(
        name="CoreProtocol.proto",
        package="dfproto",
        syntax="proto2",
    )
    file_descriptor.options.optimize_for = descriptor_pb2.FileOptions.LITE_RUNTIME

    fragment = file_descriptor.message_type.add(name="CoreTextFragment")
    text_field = fragment.field.add(
        name="text",
        number=1,
        label=descriptor_pb2.FieldDescriptorProto.LABEL_REQUIRED,
        type=descriptor_pb2.FieldDescriptorProto.TYPE_STRING,
    )
    assert text_field.name == "text"
    color_enum = fragment.enum_type.add(name="Color")
    for number, name in enumerate(
        (
            "COLOR_BLACK",
            "COLOR_BLUE",
            "COLOR_GREEN",
            "COLOR_CYAN",
            "COLOR_RED",
            "COLOR_MAGENTA",
            "COLOR_BROWN",
            "COLOR_GREY",
            "COLOR_DARKGREY",
            "COLOR_LIGHTBLUE",
            "COLOR_LIGHTGREEN",
            "COLOR_LIGHTCYAN",
            "COLOR_LIGHTRED",
            "COLOR_LIGHTMAGENTA",
            "COLOR_YELLOW",
            "COLOR_WHITE",
        )
    ):
        color_enum.value.add(name=name, number=number)
    fragment.field.add(
        name="color",
        number=2,
        label=descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL,
        type=descriptor_pb2.FieldDescriptorProto.TYPE_ENUM,
        type_name=".dfproto.CoreTextFragment.Color",
    )

    notification = file_descriptor.message_type.add(name="CoreTextNotification")
    notification.field.add(
        name="fragments",
        number=1,
        label=descriptor_pb2.FieldDescriptorProto.LABEL_REPEATED,
        type=descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE,
        type_name=".dfproto.CoreTextFragment",
    )
    file_descriptor.message_type.add(name="EmptyMessage")
    command = file_descriptor.message_type.add(name="CoreRunCommandRequest")
    command.field.add(
        name="command",
        number=1,
        label=descriptor_pb2.FieldDescriptorProto.LABEL_REQUIRED,
        type=descriptor_pb2.FieldDescriptorProto.TYPE_STRING,
    )
    command.field.add(
        name="arguments",
        number=2,
        label=descriptor_pb2.FieldDescriptorProto.LABEL_REPEATED,
        type=descriptor_pb2.FieldDescriptorProto.TYPE_STRING,
    )

    pool = descriptor_pool.DescriptorPool()
    pool.Add(file_descriptor)

    def message(name: str):
        return message_factory.GetMessageClass(pool.FindMessageTypeByName(f"dfproto.{name}"))

    return SimpleNamespace(
        CoreTextNotification=message("CoreTextNotification"),
        EmptyMessage=message("EmptyMessage"),
        CoreRunCommandRequest=message("CoreRunCommandRequest"),
    )


class _CommandRequest:
    def __init__(self, *, command: str) -> None:
        self.command = command
        self.arguments: list[str] = []


class _Core:
    CoreRunCommandRequest = _CommandRequest
    EmptyMessage = object


class _RecordingNativeClient:
    def __init__(
        self,
        *,
        output: list[str] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.output = output
        self.error = error
        self.calls: list[tuple[Any, ...]] = []

    def connect(self) -> None:
        self.calls.append(("connect",))

    def close(self) -> None:
        self.calls.append(("close",))

    def run_command(
        self,
        command: str,
        arguments: list[str],
        *,
        capture_output: bool,
    ) -> list[str] | None:
        self.calls.append(("run_command", command, arguments, capture_output))
        if self.error is not None:
            raise self.error
        return self.output


def _connected_client(sock: _FakeSocket | None = None) -> DFHackClient:
    client = DFHackClient(retries=1)
    client._sock = sock or _FakeSocket()
    client._core = _Core
    client._fortress = object()
    return client


def test_public_run_command_captures_rpc_text(monkeypatch) -> None:
    client = _connected_client()
    sent: list[tuple[int, _CommandRequest]] = []

    def fake_send_request(method_id: int, request: _CommandRequest) -> None:
        sent.append((method_id, request))

    def fake_read_reply(_output_cls) -> object:
        assert client._capture_text == []
        client._capture_text.extend(["notice\n", "result\n"])
        return object()

    monkeypatch.setattr(client, "_send_request", fake_send_request)
    monkeypatch.setattr(client, "_read_reply", fake_read_reply)

    output = client.run_command(
        "lua",
        ["print('result')"],
        capture_output=True,
    )

    assert output == ["notice\n", "result\n"]
    assert len(sent) == 1
    assert sent[0][0] == client.RPC_RUN_COMMAND
    assert sent[0][1].command == "lua"
    assert sent[0][1].arguments == ["print('result')"]
    assert client._capture_text is None


def test_supervised_identity_is_captured_from_047_text_fragments(monkeypatch) -> None:
    core = _core_protocol_047()
    notification = core.CoreTextNotification()
    notification.fragments.add(text="DFHack diagnostic\n")
    notification.fragments.add(text=f"FORTGYM_RUNTIME_IDENTITY\t{RUNTIME_IDENTITY_TSV}\n")
    sock = _ReplySocket(
        _rpc_frame(DFHackClient.RPC_REPLY_TEXT, notification.SerializeToString())
        + _rpc_frame(
            DFHackClient.RPC_REPLY_RESULT,
            core.EmptyMessage().SerializeToString(),
        )
    )
    client = DFHackClient(retries=1, **RUNTIME_IDENTITY_KWARGS)
    monkeypatch.setattr(
        client_module,
        "ensure_proto_modules",
        lambda: {"core": core, "fortress": object()},
    )
    monkeypatch.setattr(
        client_module.socket,
        "create_connection",
        lambda *_args, **_kwargs: sock,
    )
    monkeypatch.setattr(client, "_handshake", lambda: None)

    client.connect()

    assert client._runtime_identity_verified is True
    assert sock.inbound == b""
    client.close()


def test_047_fragment_output_reaches_native_lua_json_parser(monkeypatch) -> None:
    core = _core_protocol_047()
    notification = core.CoreTextNotification()
    notification.fragments.add(text="diagnostic\n")
    notification.fragments.add(text='{"ok": true, "value": 4}\n')
    client = DFHackClient(retries=1)
    client._sock = _ReplySocket(
        _rpc_frame(DFHackClient.RPC_REPLY_TEXT, notification.SerializeToString())
        + _rpc_frame(
            DFHackClient.RPC_REPLY_RESULT,
            core.EmptyMessage().SerializeToString(),
        )
    )
    client._core = core
    client._fortress = object()

    monkeypatch.setenv("FORT_GYM_DFHACK_TRANSPORT", "native-rpc")
    monkeypatch.setattr(
        dfhack_exec,
        "get_settings",
        lambda: SimpleNamespace(DFHACK_HOST="127.0.0.1", DFHACK_PORT=5444),
    )
    monkeypatch.setattr(
        dfhack_exec,
        "_new_native_rpc_client",
        lambda **_kwargs: client,
    )

    assert dfhack_exec.run_lua_file("/runtime/hook.lua", "arg1") == {
        "ok": True,
        "value": 4,
    }
    assert client._sock is None


def test_047_text_notification_missing_required_fragment_text_fails_closed() -> None:
    core = _core_protocol_047()
    notification = core.CoreTextNotification()
    notification.fragments.add()
    client = DFHackClient(retries=1)
    client._sock = _ReplySocket(
        _rpc_frame(
            DFHackClient.RPC_REPLY_TEXT,
            notification.SerializePartialToString(),
        )
    )
    client._core = core
    client._fortress = object()
    client._capture_text = []

    with pytest.raises(client_module.DFHackError, match="notification fragment"):
        client._read_reply(core.EmptyMessage)


def test_malformed_text_notification_wire_payload_fails_closed() -> None:
    core = _core_protocol_047()
    client = DFHackClient(retries=1)
    client._sock = _ReplySocket(_rpc_frame(DFHackClient.RPC_REPLY_TEXT, b"\xff"))
    client._core = core
    client._fortress = object()

    with pytest.raises(client_module.DFHackError, match="text notification"):
        client._read_reply(core.EmptyMessage)


def test_legacy_direct_text_notification_remains_supported() -> None:
    class LegacyTextNotification:
        def ParseFromString(self, payload: bytes) -> None:
            self.text = payload.decode("utf-8")

    class EmptyMessage:
        def ParseFromString(self, _payload: bytes) -> None:
            return None

    core = SimpleNamespace(
        CoreTextNotification=LegacyTextNotification,
        EmptyMessage=EmptyMessage,
    )
    client = DFHackClient(retries=1)
    client._sock = _ReplySocket(
        _rpc_frame(DFHackClient.RPC_REPLY_TEXT, b"legacy output\n")
        + _rpc_frame(DFHackClient.RPC_REPLY_RESULT, b"")
    )
    client._core = core
    client._fortress = object()
    client._capture_text = []

    client._read_reply(core.EmptyMessage)

    assert client._capture_text == ["legacy output\n"]


@pytest.mark.parametrize(
    "failure",
    [TimeoutError("timed out"), client_module.DFHackError("rpc failed")],
)
def test_public_run_command_closes_and_requires_explicit_reconnect(
    monkeypatch,
    failure: Exception,
) -> None:
    first_socket = _FakeSocket()
    second_socket = _FakeSocket()
    client = _connected_client(first_socket)
    client._method_cache[("old", "input", "output", "plugin")] = 9
    outcomes: list[Exception | list[str]] = [failure, ["reconnected"]]
    command_calls = 0

    def fake_run_command(*_args, **_kwargs):
        nonlocal command_calls
        command_calls += 1
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(client, "_run_command", fake_run_command)

    with pytest.raises(type(failure), match=str(failure)):
        client.run_command("lua", ["print('once')"], capture_output=True)

    assert command_calls == 1
    assert first_socket.closed is True
    assert client._sock is None
    assert client._method_cache == {}
    assert client._capture_text is None

    monkeypatch.setattr(
        client_module,
        "ensure_proto_modules",
        lambda: {"core": _Core, "fortress": object()},
    )
    monkeypatch.setattr(
        client_module.socket,
        "create_connection",
        lambda *_args, **_kwargs: second_socket,
    )
    monkeypatch.setattr(client, "_handshake", lambda: None)

    client.connect()
    assert client._sock is second_socket
    assert client.run_command("lua", ["print('again')"], capture_output=True) == [
        "reconnected"
    ]
    assert command_calls == 2


def test_connect_discards_failed_handshake_socket_before_retry(monkeypatch) -> None:
    first_socket = _FakeSocket()
    second_socket = _FakeSocket()
    sockets = iter([first_socket, second_socket])
    handshakes = iter([client_module.DFHackError("bad handshake"), None])
    client = DFHackClient(timeout=1.25, retries=2)

    monkeypatch.setattr(
        client_module,
        "ensure_proto_modules",
        lambda: {"core": _Core, "fortress": object()},
    )
    monkeypatch.setattr(
        client_module.socket,
        "create_connection",
        lambda *_args, **_kwargs: next(sockets),
    )
    monkeypatch.setattr(client_module.time, "sleep", lambda _seconds: None)

    def fake_handshake() -> None:
        outcome = next(handshakes)
        if outcome is not None:
            raise outcome

    monkeypatch.setattr(client, "_handshake", fake_handshake)

    client.connect()

    assert first_socket.closed is True
    assert first_socket.timeout == 1.25
    assert client._sock is second_socket
    assert second_socket.timeout == 1.25

    client.close()
    assert second_socket.closed is True


def test_supervised_connection_attests_exact_runtime_before_use(monkeypatch) -> None:
    sock = _FakeSocket()
    client = DFHackClient(
        timeout=1.25,
        retries=1,
        **RUNTIME_IDENTITY_KWARGS,
    )
    commands: list[tuple[str, list[str] | None, bool]] = []

    monkeypatch.setattr(
        client_module,
        "ensure_proto_modules",
        lambda: {"core": _Core, "fortress": object()},
    )
    monkeypatch.setattr(
        client_module.socket,
        "create_connection",
        lambda *_args, **_kwargs: sock,
    )
    monkeypatch.setattr(client, "_handshake", lambda: None)

    def fake_run_command(command, arguments=None, *, capture_output=False):
        commands.append((command, list(arguments or []), capture_output))
        return [f"FORTGYM_RUNTIME_IDENTITY\t{RUNTIME_IDENTITY_TSV}\n"]

    monkeypatch.setattr(client, "_run_command", fake_run_command)

    client.connect()

    assert client._runtime_identity_verified is True
    assert commands == [("lua", [client_module._RUNTIME_IDENTITY_LUA], True)]
    client._ensure_connection()


def test_supervised_connection_rejects_cross_wired_runtime_and_closes(
    monkeypatch,
) -> None:
    sock = _FakeSocket()
    client = DFHackClient(
        retries=1,
        **RUNTIME_IDENTITY_KWARGS,
    )
    monkeypatch.setattr(
        client_module,
        "ensure_proto_modules",
        lambda: {"core": _Core, "fortress": object()},
    )
    monkeypatch.setattr(
        client_module.socket,
        "create_connection",
        lambda *_args, **_kwargs: sock,
    )
    monkeypatch.setattr(client, "_handshake", lambda: None)
    monkeypatch.setattr(
        client,
        "_run_command",
        lambda *_args, **_kwargs: [
            "FORTGYM_RUNTIME_IDENTITY\t"
            + RUNTIME_IDENTITY_TSV.replace("m1b-run-01", "foreign-run")
            + "\n"
        ],
    )

    with pytest.raises(client_module.DFHackUnavailableError, match="Unable to connect"):
        client.connect()

    assert sock.closed is True
    assert client._sock is None
    assert client._runtime_identity_verified is False


@pytest.mark.parametrize(
    "observed_tsv",
    [
        "\t".join(RUNTIME_IDENTITY_FIELDS[:-1]),
        "\t".join(
            (
                *RUNTIME_IDENTITY_FIELDS[:3],
                RUNTIME_IDENTITY_FIELDS[4],
                RUNTIME_IDENTITY_FIELDS[3],
                *RUNTIME_IDENTITY_FIELDS[5:],
            )
        ),
        "\t".join((*RUNTIME_IDENTITY_FIELDS, "unexpected-extra-field")),
    ],
    ids=("partial", "reordered", "extra"),
)
def test_supervised_connection_rejects_nonexact_eight_field_identity(
    monkeypatch,
    observed_tsv: str,
) -> None:
    sock = _FakeSocket()
    client = DFHackClient(retries=1, **RUNTIME_IDENTITY_KWARGS)
    monkeypatch.setattr(
        client_module,
        "ensure_proto_modules",
        lambda: {"core": _Core, "fortress": object()},
    )
    monkeypatch.setattr(
        client_module.socket,
        "create_connection",
        lambda *_args, **_kwargs: sock,
    )
    monkeypatch.setattr(client, "_handshake", lambda: None)
    monkeypatch.setattr(
        client,
        "_run_command",
        lambda *_args, **_kwargs: [f"FORTGYM_RUNTIME_IDENTITY\t{observed_tsv}\n"],
    )

    with pytest.raises(client_module.DFHackUnavailableError, match="Unable to connect"):
        client.connect()

    assert sock.closed is True
    assert client._sock is None
    assert client._runtime_identity_verified is False


def test_runtime_identity_environment_is_all_or_none_and_legacy_is_unchanged(
    monkeypatch,
) -> None:
    for name in RUNTIME_IDENTITY_ENVIRONMENT:
        monkeypatch.delenv(name, raising=False)
    assert DFHackClient(retries=1)._expected_runtime_identity is None

    for name, value in RUNTIME_IDENTITY_ENVIRONMENT.items():
        if name != "FORT_GYM_RUNTIME_PREPARED":
            monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match="requires FORT_GYM_RUNTIME_PREPARED=1"):
        DFHackClient(retries=1)

    monkeypatch.setenv("FORT_GYM_RUNTIME_PREPARED", "true")
    with pytest.raises(ValueError, match="requires FORT_GYM_RUNTIME_PREPARED=1"):
        DFHackClient(retries=1)

    monkeypatch.setenv("FORT_GYM_RUNTIME_PREPARED", "1")
    assert DFHackClient(retries=1)._expected_runtime_identity == RUNTIME_IDENTITY_FIELDS


@pytest.mark.parametrize(
    "missing_name",
    [
        name
        for name in RUNTIME_IDENTITY_ENVIRONMENT
        if name != "FORT_GYM_RUNTIME_PREPARED"
    ],
)
def test_prepared_runtime_environment_rejects_each_partial_identity(
    monkeypatch,
    missing_name: str,
) -> None:
    for name in RUNTIME_IDENTITY_ENVIRONMENT:
        monkeypatch.delenv(name, raising=False)
    for name, value in RUNTIME_IDENTITY_ENVIRONMENT.items():
        if name != missing_name:
            monkeypatch.setenv(name, value)

    with pytest.raises(ValueError, match="requires run ID, nonce, contract"):
        DFHackClient(retries=1)


def test_native_rpc_expr_uses_settings_and_cleans_up(monkeypatch) -> None:
    client = _RecordingNativeClient(output=["notice\n", "\x1b[0mvalue\x1b[0m\n"])
    factory_calls: list[dict[str, Any]] = []

    monkeypatch.setenv("FORT_GYM_DFHACK_TRANSPORT", "native-rpc")
    monkeypatch.setattr(
        dfhack_exec,
        "get_settings",
        lambda: SimpleNamespace(DFHACK_HOST="127.0.0.9", DFHACK_PORT=5123),
    )
    monkeypatch.setattr(
        dfhack_exec,
        "_new_native_rpc_client",
        lambda **kwargs: factory_calls.append(kwargs) or client,
    )
    monkeypatch.setattr(
        dfhack_exec,
        "run_dfhack",
        lambda *_args, **_kwargs: pytest.fail("native-rpc must not fall back to CLI"),
    )

    assert dfhack_exec.run_lua_expr("print('value')", timeout=3.5) == "notice\nvalue"
    assert factory_calls == [{"host": "127.0.0.9", "port": 5123, "timeout": 3.5}]
    assert client.calls == [
        ("connect",),
        ("run_command", "lua", ["print('value')"], True),
        ("close",),
    ]


def test_generic_command_uses_native_rpc_without_host_binary(monkeypatch) -> None:
    client = _RecordingNativeClient(output=["nopause disabled\n"])
    monkeypatch.setenv("FORT_GYM_DFHACK_TRANSPORT", "native-rpc")
    monkeypatch.setattr(
        dfhack_exec,
        "get_settings",
        lambda: SimpleNamespace(DFHACK_HOST="127.0.0.1", DFHACK_PORT=5888),
    )
    monkeypatch.setattr(
        dfhack_exec,
        "_new_native_rpc_client",
        lambda **_kwargs: client,
    )
    monkeypatch.setattr(
        dfhack_exec,
        "run_dfhack",
        lambda *_args, **_kwargs: pytest.fail("native-rpc must not use host CLI"),
    )

    assert dfhack_exec.run_command("nopause", ["0"], timeout=1.5) == (
        "nopause disabled\n"
    )
    assert client.calls == [
        ("connect",),
        ("run_command", "nopause", ["0"], True),
        ("close",),
    ]


def test_native_rpc_file_parses_last_json_line(monkeypatch) -> None:
    client = _RecordingNativeClient(
        output=["diagnostic\n", '\x1b[0m{"ok": true, "value": 4}\x1b[0m\n']
    )
    monkeypatch.setenv("FORT_GYM_DFHACK_TRANSPORT", "native-rpc")
    monkeypatch.setattr(
        dfhack_exec,
        "get_settings",
        lambda: SimpleNamespace(DFHACK_HOST="127.0.0.1", DFHACK_PORT=5444),
    )
    monkeypatch.setattr(
        dfhack_exec,
        "_new_native_rpc_client",
        lambda **_kwargs: client,
    )

    assert dfhack_exec.run_lua_file("/runtime/hook.lua", "arg1") == {
        "ok": True,
        "value": 4,
    }
    assert client.calls[1] == (
        "run_command",
        "lua",
        ["-f", "/runtime/hook.lua", "arg1"],
        True,
    )
    assert client.calls[-1] == ("close",)


@pytest.mark.parametrize(
    "failure",
    [TimeoutError("timed out"), client_module.DFHackError("rpc failed")],
)
def test_native_rpc_error_closes_without_cli_fallback(
    monkeypatch,
    failure: Exception,
) -> None:
    client = _RecordingNativeClient(error=failure)
    monkeypatch.setenv("FORT_GYM_DFHACK_TRANSPORT", "native-rpc")
    monkeypatch.setattr(
        dfhack_exec,
        "get_settings",
        lambda: SimpleNamespace(DFHACK_HOST="127.0.0.1", DFHACK_PORT=5666),
    )
    monkeypatch.setattr(
        dfhack_exec,
        "_new_native_rpc_client",
        lambda **_kwargs: client,
    )
    monkeypatch.setattr(
        dfhack_exec,
        "run_dfhack",
        lambda *_args, **_kwargs: pytest.fail("native-rpc must not fall back to CLI"),
    )

    with pytest.raises(
        dfhack_exec.DFHackError,
        match=rf"native-rpc command failed at 127\.0\.0\.1:5666: {failure}",
    ):
        dfhack_exec.run_lua_expr("error('stop')")

    assert client.calls[-1] == ("close",)


def test_unset_transport_preserves_cli_behavior(monkeypatch) -> None:
    calls: list[tuple[list[str], dict[str, Any]]] = []
    monkeypatch.delenv("FORT_GYM_DFHACK_TRANSPORT", raising=False)
    monkeypatch.setattr(
        dfhack_exec,
        "run_dfhack",
        lambda args, **kwargs: calls.append((args, kwargs)) or "legacy",
    )
    monkeypatch.setattr(
        dfhack_exec,
        "_new_native_rpc_client",
        lambda **_kwargs: pytest.fail("legacy default must not create an RPC client"),
    )

    assert dfhack_exec.run_lua_expr("print('legacy')", timeout=2.0) == "legacy"
    assert calls == [
        (
            [str(dfhack_exec.DFHACK_RUN), "lua", "print('legacy')"],
            {"timeout": 2.0, "cwd": str(dfhack_exec.DFROOT)},
        )
    ]


def test_unknown_transport_fails_closed(monkeypatch) -> None:
    monkeypatch.setenv("FORT_GYM_DFHACK_TRANSPORT", "native_rpc")
    monkeypatch.setattr(
        dfhack_exec,
        "run_dfhack",
        lambda *_args, **_kwargs: pytest.fail("unknown transport must not use CLI"),
    )
    monkeypatch.setattr(
        dfhack_exec,
        "_new_native_rpc_client",
        lambda **_kwargs: pytest.fail("unknown transport must not use native RPC"),
    )

    with pytest.raises(dfhack_exec.DFHackError, match="unsupported"):
        dfhack_exec.run_lua_expr("print('never')")

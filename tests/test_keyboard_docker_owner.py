"""Portable owner wiring uses synthetic saves, Docker and model doubles only."""

import json
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

from fort_gym.bench.agent.keyboard_exchange import publish, read
from fort_gym.bench.run.campaign_checkpoint import verify_checkpoint
from fort_gym.bench.run import keyboard_docker_owner as owner
from fort_gym.bench.run import keyboard_docker_plan as plan
from fort_gym.bench.run import keyboard_window_courier as courier
from tests.test_campaign_load_smoke import sources as sources
from tests.test_keyboard_trial_launcher import prepared as prepared
from tests.test_keyboard_runtime import CONDITION, saved as saved
from tests.test_keyboard_window_courier import FakeExchange
from tests.test_keyboard_seccomp import profile, retained

RUNTIME = {
    "schema_version": plan.SCHEMA,
    "image": "sha256:" + "a" * 64,
    "source_revision": "b" * 40,
    "project_directory": "/workspace/fort-gym",
    "python_executable": "/venv/bin/python",
    "runtime_directory": "/opt/df",
    "cpus": 2,
    "memory_mib": 4096,
    "pids_limit": 512,
    "minimum_host_free_bytes": 1073741824,
}


@pytest.fixture
def arguments(prepared, tmp_path):
    path = tmp_path / "runtime.json"
    publish(path, RUNTIME)
    return SimpleNamespace(
        runtime=path,
        condition=prepared.condition,
        declaration=prepared.trial,
        origin=prepared.snapshot,
        output=tmp_path / "portable-run",
        campaign_id=prepared.campaign_id,
        mode="fresh",
        port=5540,
        context="fixture",
        docker=Path(sys.executable),
        model_executable=Path(sys.executable),
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("image", "game:latest"),
        ("source_revision", "main"),
        ("cpus", True),
        ("memory_mib", 1),
        ("pids_limit", 0),
        ("minimum_host_free_bytes", 1024),
        ("project_directory", "relative"),
        ("runtime_directory", "/opt/../df"),
        ("python_executable", "/"),
        ("runtime_directory", "/fortgym-origin/game"),
        ("extra", "unknown"),
    ],
)
def test_runtime_rejects_ambiguous_or_undeclared_inputs(field, value):
    with pytest.raises(ValueError):
        plan.validate_runtime({**RUNTIME, field: value})


def test_fresh_plan_selects_real_condition_and_only_narrow_mounts(arguments):
    data = owner.source_inputs(arguments)
    command = plan.create_arguments(
        RUNTIME, data, arguments.output, arguments.origin, "fortgym-" + "1" * 32, "2" * 32, 5540
    )
    assert data["initial_memory"] == "" and data["limit"] == 3
    assert command[:3] == ["create", "--pull", "never"]
    assert command[command.index("--network") + 1] == "none"
    assert "--read-only" in command and "--privileged" not in command
    mounts = [command[i + 1] for i, item in enumerate(command) if item == "--mount"]
    assert len(mounts) == 3
    assert sum("readonly" in item for item in mounts) == 2
    assert all(".codex" not in item and "model" not in item for item in mounts)
    assert "scripts.campaign_keyboard_trial" in command
    assert command[command.index("--source") + 1] == "/opt/df"
    assert command[command.index("--output") + 1] == plan.NATIVE_OUTPUT
    assert "fixture-new-fort" in command
    assert "--init" in command
    assert command[command.index("--memory") + 1] == command[command.index("--memory-swap") + 1]


def selected_profile(arguments):
    path, sha, raw = retained(arguments.runtime.parent, profile())
    runtime = {
        **RUNTIME,
        "schema_version": plan.SECCOMP_SCHEMA,
        "seccomp_profile": str(path),
        "seccomp_sha256": sha,
    }
    # publish() is intentionally write-once; this is a distinct input condition.
    arguments.runtime = arguments.runtime.parent / "runtime-v2.json"
    publish(arguments.runtime, runtime)
    return runtime, raw


def test_v2_keeps_profile_on_host_and_retains_exact_client_input(arguments):
    runtime, raw = selected_profile(arguments)
    result, client = execute(arguments)
    assert result["status"] == "execution_finished"
    assert result["seccomp_sha256"] == runtime["seccomp_sha256"]
    assert (arguments.output / "seccomp.json").read_bytes() == raw
    create = next(call for call in client.calls if call[0] == "create")
    security = [create[i + 1] for i, item in enumerate(create) if item == "--security-opt"]
    assert security == ["no-new-privileges", "seccomp=" + str(arguments.output / "seccomp.json")]
    mounts = [create[i + 1] for i, item in enumerate(create) if item == "--mount"]
    assert len(mounts) == 3 and all("seccomp" not in mount for mount in mounts)
    assert read(arguments.output / "owner-plan.json")["seccomp_sha256"] == runtime["seccomp_sha256"]


def test_changed_profile_stops_before_output_creation_and_docker(arguments):
    runtime, _ = selected_profile(arguments)
    Path(runtime["seccomp_profile"]).write_text("{}")
    with pytest.raises(ValueError, match="SHA256"):
        execute(arguments)
    assert not arguments.output.exists()


def test_changed_retained_profile_during_admission_prevents_container_creation(arguments):
    selected_profile(arguments)
    clients = []

    def factory(*args):
        client = FakeDocker(*args)
        clients.append(client)
        return client

    def allowance(*args, **kwargs):
        (arguments.output / "seccomp.json").write_text("{}")
        return {"allowed": True}

    result = owner.run_owner(arguments, client_factory=factory, allowance_check=allowance)
    assert result["status"] == "failed" and not result["container_create_attempted"]
    assert not clients[0].calls and not result["model_responses"]


def test_frozen_declared_profile_cannot_silently_use_default_policy(arguments):
    data = owner.source_inputs(arguments)
    data["declaration"]["seccomp_sha256"] = "c" * 64
    with pytest.raises(ValueError, match="original runtime owner"):
        plan.create_arguments(
            RUNTIME, data, arguments.output, arguments.origin, "fortgym-" + "1" * 32, "2" * 32, 5540
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_native_revision", "e" * 40),
        ("source_image_id", "sha256:" + "d" * 64),
    ],
)
def test_declared_source_and_image_cannot_silently_switch_owners(arguments, field, value):
    data = owner.source_inputs(arguments)
    data["declaration"][field] = value
    with pytest.raises(ValueError, match="original runtime owner"):
        plan.create_arguments(
            RUNTIME, data, arguments.output, arguments.origin, "fortgym-" + "1" * 32, "2" * 32, 5540
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("expected_campaign_id", "another-fort"),
        ("source_condition_sha256", "d" * 64),
    ],
)
def test_continuation_declaration_bindings_are_checked_before_execution(
    tmp_path, saved, field, value
):
    checkpoint, _, _ = saved
    condition, declaration = tmp_path / "condition.json", tmp_path / "window.json"
    publish(condition, CONDITION)
    publish(
        declaration,
        {
            "schema_version": "fortgym.codex-keyboard-window/v1",
            "condition_id": "fixture",
            "original_condition": condition.name,
            "continuation_from_next_step": 1,
            "steps_per_segment": 2,
            "max_segments": 1,
            "reset_memory": False,
            "reset_usage": False,
            "strategy_intervention": False,
            field: value,
        },
    )
    with pytest.raises(ValueError, match="binding differs"):
        plan.prepare_inputs(condition, declaration, checkpoint, "runtime-test", mode="continue")


@pytest.mark.parametrize("path", ["/tmp/bad,name", "/tmp/../other", "/tmp/bad\nname"])
def test_ambiguous_host_mount_paths_are_rejected(path):
    with pytest.raises(ValueError):
        plan.absolute_path(Path(path))


def test_continuation_preparation_restores_actual_memory_and_usage(tmp_path, saved):
    checkpoint, _, _ = saved
    condition, declaration = tmp_path / "condition.json", tmp_path / "window.json"
    publish(condition, CONDITION)
    manifest = verify_checkpoint(checkpoint)
    publish(
        declaration,
        {
            "schema_version": "fortgym.codex-keyboard-window/v1",
            "condition_id": "fixture",
            "original_condition": condition.name,
            "continuation_from_next_step": 1,
            "continuation_checkpoint_sha256": manifest["sha256"],
            "steps_per_segment": 2,
            "max_segments": 1,
            "reset_memory": False,
            "reset_usage": False,
            "strategy_intervention": False,
        },
    )
    data = plan.prepare_inputs(condition, declaration, checkpoint, "runtime-test", mode="continue")
    assert data["initial_memory"] == read(checkpoint / "agent.json")["memory"]
    assert data["original"] == manifest and data["limit"] == 2
    command = plan.create_arguments(
        RUNTIME, data, tmp_path / "new-run", checkpoint, "fortgym-" + "1" * 32, "2" * 32, 5540
    )
    assert "scripts.campaign_keyboard_native" in command
    assert command[command.index("--latest-usage") + 1] == "/fortgym-origin/usage.jsonl"
    with pytest.raises(ValueError, match="own declared"):
        plan.prepare_inputs(condition, declaration, checkpoint, "wrong-fort", mode="continue")


class FakeDocker:
    fail_create = False
    fail_preflight = False
    foreign_owner = False
    stop_fails = False

    def __init__(self, executable, context, output):
        self.command = [str(executable), "--context", context]
        self.output = output
        self.calls = []
        self.identity = "c" * 64
        self.state = {"Running": False, "ExitCode": 0}
        self.nonce = None

    def preflight(self, runtime):
        if self.fail_preflight:
            raise ValueError("Synthetic missing image")

    def inspect(self, identity):
        self.calls.append(["inspect", identity])
        return {
            "Id": self.identity,
            "Image": RUNTIME["image"],
            "State": dict(self.state),
            "Config": {"Labels": {plan.LABEL: "foreign" if self.foreign_owner else self.nonce}},
        }

    def call(self, *arguments):
        self.calls.append(list(arguments))
        if arguments[0] == "create":
            self.nonce = arguments[arguments.index("--label") + 1].split("=")[1]
            if self.fail_create:
                raise TimeoutError("Create outcome unknown to caller, container exists")
            return self.identity
        if arguments[0] == "start":
            self.state["Running"] = True
        if arguments[0] == "stop" and not self.stop_fails:
            self.state["Running"] = False
        return ""

    def output_command(self, command):
        raise AssertionError("Fixture server replaces Docker observation")

    def run(self, *args):
        raise AssertionError("Fixture server replaces Docker copying")


def execute(arguments, *, failure=None, admission=True):
    clients = []

    def factory(*args):
        client = FakeDocker(*args)
        client.fail_create = failure == "create"
        client.fail_preflight = failure == "preflight"
        client.foreign_owner = failure == "foreign"
        client.stop_fails = failure == "stop"
        clients.append(client)
        return client

    def server(exchange, condition, declaration, **kwargs):
        if failure in ("courier", "stop"):
            raise RuntimeError("Synthetic interrupted courier")
        fake = FakeExchange(exchange.out, total=declaration["steps_per_segment"])
        fake.memory = ""
        courier.serve_fresh(
            fake, condition, declaration, answer=fake.answer, wait=lambda _: None, **kwargs
        )
        native = exchange.out / "game/native"
        native.mkdir()
        publish(
            native / "result.json",
            {
                "campaign_id": arguments.campaign_id,
                "source_revision": RUNTIME["source_revision"],
                "status": "completed",
                "runtime_cleanup_verified": failure != "native",
            },
        )
        clients[0].state["Running"] = False

    result = owner.run_owner(
        arguments,
        client_factory=factory,
        fresh_server=server,
        allowance_check=lambda *a, **kw: {"allowed": admission, "basis": "synthetic_fixture"},
    )
    return result, clients[0]


def test_public_owner_composes_real_fresh_memory_exchange_and_retains_usage(arguments):
    result, client = execute(arguments)
    assert result["status"] == "execution_finished"
    assert result["container_stopped_verified"] and result["original_inputs_unchanged"]
    assert result["known_returned_tokens"] == 30
    assert result["responses_with_unknown_tokens"] == 0 and result["reported_charge_usd"] is None
    assert len(result["model_responses"]) == 3
    assert (
        result["native_acceptance_audited"] is result["vm_created"] is result["vm_stopped"] is False
    )
    assert result == read(arguments.output / "owner-result.json")
    assert not any(call[0] in {"rm", "pull", "volume", "system"} for call in client.calls)
    assert len(list((arguments.output / "model").glob("*/claim.json"))) == 3
    assert (
        arguments.output / "inputs" / arguments.condition.name
    ).read_bytes() == arguments.condition.read_bytes()
    assert (
        arguments.output / "inputs" / arguments.declaration.name
    ).read_bytes() == arguments.declaration.read_bytes()
    with pytest.raises(ValueError, match="new output"):
        execute(arguments)


@pytest.mark.parametrize("failure", ["create", "courier", "native", "preflight", "foreign", "stop"])
def test_failure_retains_attempt_and_never_retries_or_stops_foreign_container(arguments, failure):
    result, client = execute(arguments, failure=failure)
    assert result["status"] == "failed" and result["original_inputs_unchanged"]
    assert result == read(arguments.output / "owner-result.json")
    assert sum(call[0] == "create" for call in client.calls) <= 1
    assert sum(call[0] == "start" for call in client.calls) <= 1
    if failure == "foreign":
        assert not any(call[0] in ("start", "stop") for call in client.calls)
    if failure == "stop":
        assert result["container_stopped_verified"] is False
    if failure == "create":
        assert result["container_id"] == "c" * 64 and result["container_stopped_verified"]


def test_unknown_create_result_reconciles_the_actual_predeclared_container_name(arguments):
    class ExactNameDocker(FakeDocker):
        def call(self, *parts):
            if parts[0] == "create":
                self.created_name = parts[parts.index("--name") + 1]
                self.fail_create = True
            return super().call(*parts)

        def inspect(self, identity):
            if identity not in (self.identity, self.created_name):
                raise ValueError("No such container: " + identity)
            return super().inspect(identity)

    result = owner.run_owner(
        arguments,
        client_factory=ExactNameDocker,
        allowance_check=lambda *args, **kwargs: {"allowed": True},
    )
    assert result["status"] == "failed"  # Uncertain create is never retried.
    assert result["container_stopped_verified"] is True
    assert result["container_id"] == "c" * 64


def test_admission_pause_does_not_create_a_container_or_make_model_calls(arguments):
    result, client = execute(arguments, admission=False)
    assert result["status"] == "budget_limited_pause"
    assert not result["container_create_attempted"] and not result["model_responses"]
    assert not client.calls


def test_output_capacity_failure_happens_before_any_docker_or_model_call(arguments, monkeypatch):
    monkeypatch.setattr(owner.shutil, "disk_usage", lambda _: SimpleNamespace(free=100))
    with pytest.raises(ValueError, match="capacity floor"):
        execute(arguments)
    assert not arguments.output.exists()


def test_configured_transport_paths_are_quoted_and_python_is_explicit(tmp_path, monkeypatch):
    commands = []

    def observe(command, **kwargs):
        commands.append(command)
        return ""

    monkeypatch.setattr(courier, "observe_container_output", observe)
    exchange = courier.DockerExchange(
        "owned",
        tmp_path,
        ["docker"],
        {},
        lambda _: "",
        lambda *a: None,
        native_output="/evidence/native run",
        python_executable="/venv/bin/python",
        project_directory="/workspace/project",
    )
    assert exchange.pending() == []
    assert "'/evidence/native run/exchange'" in commands[0][-1]

    def process(command, **kwargs):
        commands.append(command)
        kwargs["stdout"].write(b'{"published_and_read_verified":true}')
        return SimpleNamespace(returncode=0)

    exchange.process = process
    exchange.deliver(["probe", "--output", "/fixture/probe.json"], {}, "probe")
    assert commands[-1][:7] == [
        "docker",
        "exec",
        "-i",
        "--workdir",
        "/workspace/project",
        "owned",
        "/venv/bin/python",
    ]


@pytest.mark.parametrize("native_output", [
    "/fortgym-evidence/native", "/evidence/astra", "/evidence/native run",
])
def test_actual_observation_guard_accepts_declared_courier_layout(tmp_path, native_output):
    calls = []
    identifier = "a" * 32

    def output(command):
        calls.append(command)
        return "" if "test -d" in command[-1] else "ready"

    exchange = courier.DockerExchange(
        "owned", tmp_path, ["docker"], {}, output, lambda *args: None,
        native_output=native_output,
    )
    assert exchange.pending() == []
    assert exchange.copy_request(identifier, tmp_path / identifier) is True
    assert len(calls) == 2


def test_runtime_preflight_requires_local_engine_exact_image_and_no_implicit_volumes(tmp_path):
    client = owner.DockerClient(Path(sys.executable), "fixture", tmp_path)
    values = [
        [{"Name": "fixture", "Endpoints": {"docker": {"Host": "unix:///fixture.sock"}}}],
        [{"Id": RUNTIME["image"], "Os": "linux", "Config": {}}],
    ]
    client.call = lambda *a: json.dumps(values[0] if a[0] == "context" else values[1])
    client.preflight(RUNTIME)
    values[0][0]["Endpoints"]["docker"]["Host"] = "ssh://remote"
    with pytest.raises(ValueError, match="local Unix"):
        client.preflight(RUNTIME)
    values[0][0]["Endpoints"]["docker"]["Host"] = "unix:///fixture.sock"
    values[1][0]["Config"]["Volumes"] = {"/unexpected": {}}
    with pytest.raises(ValueError, match="implicit"):
        client.preflight(RUNTIME)
    values[1][0]["Config"] = {}
    values[1][0]["Id"] = "sha256:" + "f" * 64
    with pytest.raises(ValueError, match="exact existing"):
        client.preflight(RUNTIME)


def test_docker_machine_output_keeps_stderr_warning_separate(tmp_path):
    client = owner.DockerClient(Path(sys.executable), "fixture", tmp_path)
    identity = "a" * 64
    command = [sys.executable, "-c",
               "import sys; print('WARNING: image platform differs', file=sys.stderr); "
               + f"print({identity!r})"]
    assert client.run(command, "create") == identity
    assert (tmp_path / "docker-0001-create.log").read_text() == identity + "\n"
    assert (tmp_path / "docker-0001-create.stderr.log").read_text() == (
        "WARNING: image platform differs\n"
    )


def test_docker_failed_command_retains_both_streams_without_retry(tmp_path):
    client = owner.DockerClient(Path(sys.executable), "fixture", tmp_path)
    command = [sys.executable, "-c", "import sys; print('partial'); "
               "print('daemon error', file=sys.stderr); sys.exit(7)"]
    with pytest.raises(owner.subprocess.CalledProcessError) as error:
        client.run(command, "failure")
    assert error.value.returncode == 7 and client.sequence == 1
    assert (tmp_path / "docker-0001-failure.log").read_text() == "partial\n"
    assert (tmp_path / "docker-0001-failure.stderr.log").read_text() == "daemon error\n"


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_docker_bounds_each_retained_stream(tmp_path, monkeypatch, stream):
    client = owner.DockerClient(Path(sys.executable), "fixture", tmp_path)
    monkeypatch.setattr(owner, "MAX_BYTES", 20)
    command = [sys.executable, "-c", f"import sys; sys.{stream}.write('x' * 21)"]
    with pytest.raises(ValueError, match="bounded reader"):
        client.run(command, "oversized")
    assert client.sequence == 1


def test_owner_routes_unchanged_continuation_with_its_original_memory(arguments, saved):
    checkpoint, _, _ = saved
    arguments.mode, arguments.origin, arguments.campaign_id = "continue", checkpoint, "runtime-test"
    arguments.condition.write_text(json.dumps(CONDITION))
    manifest = verify_checkpoint(checkpoint)
    declaration = {
        "schema_version": "fortgym.codex-keyboard-window/v1",
        "condition_id": "fixture",
        "original_condition": arguments.condition.name,
        "continuation_from_next_step": 1,
        "continuation_checkpoint_sha256": manifest["sha256"],
        "steps_per_segment": 2,
        "max_segments": 1,
        "reset_memory": False,
        "reset_usage": False,
        "strategy_intervention": False,
    }
    arguments.declaration.write_text(json.dumps(declaration))
    clients = []

    def factory(*args):
        client = FakeDocker(*args)
        clients.append(client)
        return client

    def window(exchange, condition, value, **kwargs):
        assert value == declaration and condition == CONDITION
        assert kwargs["initial_memory"] == read(checkpoint / "agent.json")["memory"]
        kwargs["decisions"].append({"total_tokens": None, "model_dispatched": None})
        native = exchange.out / "game/native"
        native.mkdir()
        publish(
            native / "result.json",
            {
                "campaign_id": "runtime-test",
                "source_revision": RUNTIME["source_revision"],
                "status": "paused",
                "runtime_cleanup_verified": True,
            },
        )
        clients[0].state["Running"] = False

    result = owner.run_owner(
        arguments,
        client_factory=factory,
        window_server=window,
        fresh_server=lambda *a, **kw: pytest.fail("Continuation cannot reset as a fresh trial"),
        allowance_check=lambda *a, **kw: {"allowed": True, "basis": "synthetic_fixture"},
    )
    assert result["status"] == "execution_finished" and result["original_inputs_unchanged"]
    assert result["known_returned_tokens"] == 0 and result["responses_with_unknown_tokens"] == 1
    assert result["reported_charge_usd"] is None and verify_checkpoint(checkpoint) == manifest


def test_cli_check_is_read_only_and_does_not_contact_docker_or_model(
    arguments, monkeypatch, capsys
):
    from scripts import campaign_keyboard_docker as cli

    checked = []
    monkeypatch.setattr(cli, "verify_source", checked.append)
    monkeypatch.setattr(cli, "run_owner", lambda *a: pytest.fail("Check must not execute"))
    command = ["campaign_keyboard_docker", "check", "--mode", "fresh"]
    for key in (
        "runtime",
        "condition",
        "declaration",
        "origin",
        "output",
        "campaign_id",
        "context",
        "docker",
        "model_executable",
        "port",
    ):
        command += ["--" + key.replace("_", "-"), str(getattr(arguments, key))]
    monkeypatch.setattr(sys, "argv", command)
    cli.main()
    result = json.loads(capsys.readouterr().out)
    assert result["passed"] is True and result["local_files_only"] is True
    assert result["docker_contacted"] is result["game_or_model_started"] is False
    assert checked == [RUNTIME["source_revision"]] and not arguments.output.exists()

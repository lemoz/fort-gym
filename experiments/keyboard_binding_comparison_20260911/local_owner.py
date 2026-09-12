"""Run one declared comparison attempt on the existing local VM, with mandatory teardown."""

# ruff: noqa: E402 -- Select the frozen checkout before importing its campaign code.

import argparse
import hashlib
import io
import os
import tarfile
import importlib.util
import json
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

PLAN = Path(__file__).resolve().parent
ROOT = PLAN.parents[1]
RUNTIME = ROOT / "fort_gym/artifacts/native-local-20260906/runtime-v2"
BASE = RUNTIME / "keyboard-matched-pilot-v1/keyboard-bindings-comparison-v1"
WORKTREE = ROOT / "fort_gym/artifacts/worktrees/campaign-dismissed-screen-restart"
REVISION = "d22f28d99f4fd103188979e964e148139d3f3efd"
IMAGE = "sha256:32bd022138a4772ed0c0d3a14f94feab8ad4a4cd183a20a8cd098745aedbd10d"
TRIAL_ID = None
SESSION = None
DECLARATION_REVISION = None
PREFLIGHT_ONLY = False
SEED_VOLUME = "fort-gym-v2-seed-20260906"
SEED_SHA = "eaf5fa5a40014719e6c313f33497740e536a8faa1c90a84c4e09dcc380ac0595"
COURIER_SECONDS = 23340  # 64 * (exchange timeout + native work) + save.
MAX_RESPONSES = 64
CONFIG_SHA = "ee0e3b0ced1cb0642f691959783e48c4ed45ecb182474974ae1afee84f0def93"
SECCOMP_SHA = "5ae96ce3d0a9c746765df7d4c5948312f3847b08e917174368797d788461657a"


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def initialize():
    """Load the pinned native harness and existing local transport only on execution."""
    global transport, run, output, COLIMA, DOCKER, read_allowance, answer_request
    global \
        publish, \
        read, \
        validate_request, \
        observe_container_output, \
        load_trial, \
        verify_snapshot
    HELPERS = RUNTIME / "map-inspection-v3/operator.py"
    assert (
        sha(HELPERS)
        == "4dd26e958085e2122a2ff466af36f6ff521ee6a9e61da06e74e499866532abcf"
    )
    spec = importlib.util.spec_from_file_location("matched_transport", HELPERS)
    transport = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(transport)
    run, output = transport.run, transport.output
    COLIMA, DOCKER = transport.COLIMA, transport.DOCKER
    sys.path.insert(0, str(WORKTREE))
    from fort_gym.bench.agent.codex_allowance import read_allowance
    from fort_gym.bench.agent.keyboard_courier import answer_request
    from fort_gym.bench.agent.keyboard_exchange import publish, read, validate_request
    from fort_gym.bench.agent.keyboard_observation import observe_container_output
    from fort_gym.bench.run.keyboard_trial_config import load_trial
    from scripts.campaign_load_smoke import verify_snapshot


def selection():
    cohort = json.loads((PLAN / "cohort.json").read_text())
    candidates = [item for item in cohort["sequence"] if item["id"] == TRIAL_ID]
    if len(candidates) != 1:
        raise ValueError("Select exactly one predeclared campaign")
    item = candidates[0]
    row = {
        "campaign_id": item["id"],
        "model": cohort["models"][item["model"]],
        "condition": item["condition"],
        "trial": item["trial"],
        "replicate": item["replicate"],
    }
    condition, trial = load_trial(PLAN / row["condition"], PLAN / row["trial"])
    assert (
        cohort["native_source_revision"] == REVISION and cohort["native_image"] == IMAGE
    )
    assert (
        condition["model"] == row["model"] and condition["reasoning_effort"] == "medium"
    )
    assert condition["control_profile"] == "native_keyboard_bindings/v1"
    assert condition["prompt_profile"] == "native_keyboard_binding_instructions/v1"
    assert (
        condition["bindings_sha256"]
        == "8176d2bd7a8d96f6bb12feb654519a8361a6f262363b84ec48963be832cb7efd"
    )
    assert condition["maximum_included_usage_percent"] == 98
    assert (
        condition["max_dispatches"] == 1280
        and condition["max_total_tokens"] == 40000000
    )
    assert (
        condition["max_segments"] == 1
        and condition["steps_per_segment"] == MAX_RESPONSES
    )
    assert trial["steps_per_segment"] == MAX_RESPONSES
    assert trial["source_snapshot_receipt_sha256"] == SEED_SHA
    assert (
        trial["initial_memory"] == "empty" and trial["strategy_intervention"] is False
    )
    return row, condition


def launch_archive(row):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        directory = tarfile.TarInfo("launch")
        directory.type, directory.mode = tarfile.DIRTYPE, 0o755
        archive.addfile(directory)
        for filename in (row["condition"], row["trial"]):
            data = (PLAN / filename).read_bytes()
            entry = tarfile.TarInfo("launch/" + filename)
            entry.mode, entry.size = 0o444, len(data)
            archive.addfile(entry, io.BytesIO(data))
    return stream.getvalue()


def native_arguments(row):
    root = "/launch/"
    return [
        "-m",
        "scripts.campaign_keyboard_trial",
        "run",
        "--condition",
        root + row["condition"],
        "--trial",
        root + row["trial"],
        "--campaign-id",
        row["campaign_id"],
        "--source",
        "/opt/dwarf-fortress",
        "--snapshot",
        "/seed-evidence/seed-smoke",
        "--output",
        "/evidence/astra",
        "--port",
        "5617",
        "--revision",
        REVISION,
    ]


def binding():
    return {
        "schema_version": "fortgym.private-binding-trial-execution/v1",
        "source_revision": REVISION,
        "image_id": IMAGE,
        "declaration_revision": DECLARATION_REVISION,
        "config_sha256": {path.name: sha(path) for path in sorted(PLAN.glob("*.json"))},
        "seed_receipt_sha256": SEED_SHA,
        "operator_sha256": sha(Path(__file__)),
        "audit_source_sha256": {
            path.name: sha(path) for path in sorted(PLAN.glob("*_review.py"))
        },
        "vm_config_sha256": CONFIG_SHA,
        "seccomp_sha256": SECCOMP_SHA,
        "maximum_responses_per_start": MAX_RESPONSES,
        "maximum_live_games": 1,
    }


def stopped():
    rows = [
        json.loads(line) for line in output(COLIMA + ["list", "--json"]).splitlines()
    ]
    return bool(rows) and all(row["status"] == "Stopped" for row in rows)


def serve_model(name, out, condition, decisions):
    model_root = out / "model"
    model_root.mkdir(mode=0o700)
    failures = 0
    handled = set()
    handoff_verified = False
    memory = ""
    terminal_response = False

    def retain_failure(value):
        nonlocal failures
        failures += 1
        publish(out / f"read-failure-{failures:04d}.json", value)

    def game_output(command):
        return observe_container_output(
            command,
            output=output,
            inspect_command=DOCKER + ["inspect", name, "--format", "{{json .State}}"],
            retain_warning=lambda warning: publish(
                out / "terminal-observation-warning.json", warning
            ),
            max_live_read_attempts=3,
            retain_failure=retain_failure,
        )

    def deliver(arguments, value, label):
        with (out / (label + ".log")).open("xb") as log:
            completed = subprocess.run(
                DOCKER
                + [
                    "exec",
                    "-i",
                    name,
                    "/opt/python/bin/python3.11",
                    "-m",
                    "scripts.campaign_keyboard_native",
                    *arguments,
                ],
                input=json.dumps(value, allow_nan=False).encode(),
                stdout=log,
                stderr=subprocess.STDOUT,
                env=transport.VM_ENV,
                timeout=20,
            )
        assert completed.returncode == 0, "Game-user response delivery failed"
        assert read(out / (label + ".log")) == {"published_and_read_verified": True}

    deadline = time.monotonic() + COURIER_SECONDS
    while time.monotonic() < deadline:
        state = json.loads(
            output(DOCKER + ["inspect", name, "--format", "{{json .State}}"])
        )
        if not state["Running"]:
            return
        listing = game_output(
            DOCKER
            + [
                "exec",
                name,
                "/bin/sh",
                "-c",
                "if test -d /evidence/astra/exchange; then ls -1 /evidence/astra/exchange; fi",
            ]
        )
        if listing is None:
            return
        for identifier in listing.splitlines():
            assert re.fullmatch("[a-f0-9]{32}", identifier)
            if identifier in handled:
                continue
            assert len(handled) < MAX_RESPONSES and not terminal_response, (
                "Fresh-start response bound exceeded"
            )
            remote = "/evidence/astra/exchange/" + identifier
            ready = game_output(
                DOCKER
                + [
                    "exec",
                    name,
                    "/bin/sh",
                    "-c",
                    "if test -f " + remote + "/request.json; then echo ready; fi",
                ]
            )
            if ready != "ready":
                continue
            directory = model_root / identifier
            directory.mkdir(mode=0o700)
            run(
                DOCKER
                + [
                    "cp",
                    name + ":" + remote + "/request.json",
                    str(directory / "request.json"),
                ],
                "request-copy-" + identifier,
                20,
            )
            request = read(directory / "request.json")
            validate_request(request)
            assert request["request_id"] == identifier
            assert request["memory"] == memory, "Model memory chain differs"
            assert [
                request["screen"]["width"],
                request["screen"]["height"],
            ] == condition["screen_size"]
            if not handled:
                assert request["feedback"] is None, (
                    "Fresh trial cannot borrow prior feedback"
                )
            if not handoff_verified:
                deliver(
                    ["probe", "--output", "/evidence/astra/transport-probe.json"],
                    {"probe": "bounded-json-delivery/v1"},
                    "model-handoff-preflight",
                )
                handoff_verified = True
            handled.add(identifier)
            response, summary = answer_request(
                request,
                directory=directory,
                condition=condition,
                executable=Path("/opt/homebrew/bin/codex"),
            )
            summary = {"decision_index": len(decisions), **summary}
            decisions.append(summary)
            publish(directory / "summary.json", summary)
            result = response["result"]
            if result.get("action_grammar_valid") is True:
                memory = result["action"]["memory_update"]
                assert isinstance(memory, str)
            terminal_response = summary.get("model_dispatched") is not True
            deliver(
                [
                    "publish-response",
                    "--exchange",
                    "/evidence/astra/exchange",
                    "--request-id",
                    identifier,
                ],
                response,
                "response-publish-" + identifier,
            )
            print(json.dumps(summary), flush=True)
        time.sleep(0.5)
    raise TimeoutError("Displayed-key fresh-start owner deadline reached")


def main():
    row, condition = selection()
    identity = row["campaign_id"]
    out = SESSION / "attempt"
    name = "fort-gym-" + identity
    volume = name + "-evidence"
    assert not out.exists(), "Never relaunch or overwrite an existing attempt"
    assert not (SESSION / "execution.json").exists()
    assert (
        subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=WORKTREE, text=True
        ).strip()
        == REVISION
    )
    assert not subprocess.check_output(["git", "status", "--porcelain"], cwd=WORKTREE)
    assert (
        subprocess.check_output(
            [
                "git",
                "ls-remote",
                "github",
                "refs/heads/codex/campaign-dismissed-screen-restart",
            ],
            cwd=WORKTREE,
            text=True,
        ).split()[0]
        == REVISION
    )
    ci = json.loads(
        subprocess.check_output(
            [
                "gh",
                "run",
                "view",
                "34619202196",
                "--repo",
                "lemoz/fort-gym",
                "--json",
                "headSha,status,conclusion",
            ],
            text=True,
        )
    )
    assert ci == {"headSha": REVISION, "status": "completed", "conclusion": "success"}
    check = (
        BASE.parent
        / "keyboard-binding-integrated-native-review-v1/terminal-review.json"
    )
    assert (
        sha(check) == "1ce949d0d7324dd66f65b250e37a090c59cabf078de5c58af60c697bea7eb680"
    )
    assert read(check)["passed"] is True
    verify_snapshot(RUNTIME / "corrected-context/seed-smoke", SEED_SHA)
    config = transport.APP / "fg-v2/colima.yaml"
    seccomp = RUNTIME.parent / "seccomp-moby27-dfhack.json"
    assert sha(config) == CONFIG_SHA and sha(seccomp) == SECCOMP_SHA
    assert stopped()
    assert all(
        json.loads(line)["status"] == "Stopped"
        for line in output(
            ["/opt/homebrew/bin/colima", "list", "--json"], transport.ENV
        ).splitlines()
    )
    for path in sorted(PLAN.glob("*")):
        if path.is_file() and path.suffix in (".py", ".json", ".md"):
            committed = subprocess.check_output(
                [
                    "git",
                    "show",
                    DECLARATION_REVISION + ":" + str(path.relative_to(ROOT)),
                ],
                cwd=ROOT,
            )
            assert path.read_bytes() == committed, "Declaration source differs"
    remote = subprocess.check_output(
        ["git", "ls-remote", "github", "refs/heads/codex/year-two-campaigns"],
        cwd=ROOT,
        text=True,
    ).split()[0]
    subprocess.run(
        ["git", "merge-base", "--is-ancestor", DECLARATION_REVISION, remote],
        cwd=ROOT,
        check=True,
    )
    if PREFLIGHT_ONLY:
        allowance = read_allowance(
            Path("/opt/homebrew/bin/codex"), maximum_used_percent=98
        )
        print(
            json.dumps(
                {
                    "preflight_passed": True,
                    "campaign_id": identity,
                    "binding": binding(),
                    "subscription_admission": allowance,
                    "vm_observed_stopped": True,
                    "guest_capacity": "checked_after_start_before_container_creation",
                    "model_calls": 0,
                    "vm_started": False,
                }
            ),
            flush=True,
        )
        return
    SESSION.mkdir(mode=0o700, parents=True, exist_ok=False)
    out.mkdir(mode=0o700)
    os.chdir(SESSION)
    transport.OUT = out
    transport.DEADLINE = time.monotonic() + COURIER_SECONDS + 900
    result = {
        "schema_version": "fortgym.private-binding-trial-owner/v1",
        "campaign_id": identity,
        "source_revision": REVISION,
        "image_id": IMAGE,
        "model": row["model"],
        "reasoning_effort": "medium",
        "binding": binding(),
        "model_decisions": [],
        "cloud_vms_created": 0,
        "reported_model_charge_usd": None,
        "hardware_energy_and_app_cost_usd": None,
        "vm_started": False,
        "status": "failed",
        "provider_calls": None,
        "native_result_audited": False,
    }
    publish(out / "launch.json", result)
    allowance = read_allowance(Path("/opt/homebrew/bin/codex"), maximum_used_percent=98)
    publish(out / "subscription-admission.json", allowance)
    if not allowance["allowed"]:
        result.update(status="budget_limited_pause", provider_calls=0)
        publish(out / "result.json", result)
        print(
            json.dumps(
                {
                    "campaign_id": identity,
                    "status": result["status"],
                    "vm_started": False,
                }
            ),
            flush=True,
        )
        return
    created = started = False
    signal.signal(signal.SIGTERM, transport.interrupted)
    signal.signal(signal.SIGINT, transport.interrupted)
    try:
        started = True
        result["vm_started"] = True
        run(
            COLIMA
            + [
                "start",
                "--arch=aarch64",
                "--vm-type=vz",
                "--vz-rosetta",
                "--cpus=2",
                "--memory=3",
                "--root-disk=8",
                "--disk=32",
                "--runtime=docker",
                "--activate=false",
                "--ssh-config=false",
                "--ssh-agent=false",
                "--network-address=false",
                "--mount=none",
            ],
            "vm-start",
            480,
        )
        assert output(DOCKER + ["ps", "-q"]) == ""
        assert (
            name
            not in output(DOCKER + ["ps", "-a", "--format", "{{.Names}}"]).splitlines()
        )
        volumes = output(
            DOCKER + ["volume", "ls", "--format", "{{.Name}}"]
        ).splitlines()
        assert volume not in volumes and SEED_VOLUME in volumes
        disk = output(COLIMA + ["ssh", "--", "df", "-Pk", "/var/lib/docker"])
        publish(out / "data-disk-before.json", {"df_pk": disk})
        assert int(disk.splitlines()[-1].split()[3]) >= 1536 * 1024, (
            "Retained evidence leaves insufficient disk"
        )
        image = json.loads(output(DOCKER + ["image", "inspect", IMAGE]))[0]
        assert (
            image["Id"] == IMAGE
            and image["Architecture"] == "amd64"
            and image["Config"]["User"] == "dfh"
        )
        publish(SESSION / "execution.json", binding())
        created = True
        run(
            DOCKER
            + [
                "create",
                "--name",
                name,
                "--init",
                "--platform=linux/amd64",
                "--network=none",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                "--security-opt=seccomp=" + str(seccomp),
                "--memory=1536m",
                "--memory-swap=1536m",
                "--cpus=2",
                "--pids-limit=256",
                "--label=fortgym.owner=" + name,
                "--mount=type=volume,src="
                + SEED_VOLUME
                + ",dst=/seed-evidence,readonly",
                "--mount=type=volume,src=" + volume + ",dst=/evidence",
                "--entrypoint=/opt/python/bin/python3.11",
                IMAGE,
                *native_arguments(row),
            ],
            "container-create",
        )
        observed = json.loads(output(DOCKER + ["inspect", name]))[0]
        publish(out / "container-config.json", observed)
        host = observed["HostConfig"]
        assert (
            host["Init"] is True
            and host["PidsLimit"] == 256
            and host["NetworkMode"] == "none"
        )
        assert (
            host["Memory"] == host["MemorySwap"] == 1610612736
            and host["NanoCpus"] == 2000000000
        )
        assert host["PortBindings"] == {}
        assert any(
            m["Destination"] == "/seed-evidence" and m["RW"] is False
            for m in observed["Mounts"]
        )
        with (out / "launch-archive.log").open("xb") as log:
            copied = subprocess.run(
                DOCKER + ["cp", "-", name + ":/"],
                input=launch_archive(row),
                stdout=log,
                stderr=subprocess.STDOUT,
                env=transport.VM_ENV,
                timeout=30,
            )
        assert copied.returncode == 0
        run(DOCKER + ["start", name], "native-start", 30)
        serve_model(name, out, condition, result["model_decisions"])
        state = json.loads(
            output(DOCKER + ["inspect", name, "--format", "{{json .State}}"])
        )
        assert not state["Running"] and state["ExitCode"] == 0, state
    except BaseException as error:
        result.update(error_type=type(error).__name__, error=str(error))
        raise
    finally:
        if created:
            try:
                assert (
                    output(
                        DOCKER
                        + [
                            "inspect",
                            name,
                            "--format",
                            '{{index .Config.Labels "fortgym.owner"}}',
                        ]
                    )
                    == name
                )
                for command, label, bound in (
                    (DOCKER + ["stop", "--time=30", name], "container-stop", 45),
                    (DOCKER + ["logs", name], "container-log", 30),
                    (
                        DOCKER + ["inspect", name, "--format", "{{json .State}}"],
                        "container-final-state",
                        20,
                    ),
                    (
                        DOCKER + ["cp", name + ":/evidence", str(out / "evidence")],
                        "evidence-copy",
                        120,
                    ),
                ):
                    try:
                        result[label + "_returncode"] = run(
                            command, label, bound, check=False, cleanup=True
                        )
                    except Exception as error:
                        result[label + "_error_type"] = type(error).__name__
            except Exception as error:
                result["container_cleanup_error_type"] = type(error).__name__
        if started:
            try:
                result["guest_poweroff_returncode"] = run(
                    COLIMA + ["ssh", "--", "sudo", "systemctl", "poweroff"],
                    "guest-poweroff",
                    20,
                    check=False,
                    cleanup=True,
                )
                for _ in range(30):
                    if stopped():
                        break
                    time.sleep(1)
            except Exception as error:
                result["guest_poweroff_error_type"] = type(error).__name__
            finally:
                try:
                    result["vm_stop_returncode"] = run(
                        COLIMA + ["stop"], "vm-stop", 90, check=False, cleanup=True
                    )
                    result["vm_observed_stopped"] = stopped()
                except Exception as error:
                    result["vm_cleanup_error_type"] = type(error).__name__
        result["vm_config_unchanged"] = sha(config) == CONFIG_SHA
        native = out / "evidence/astra/result.json"
        if native.is_file():
            result["native"] = read(native)
        result["confirmed_model_calls"] = sum(
            d.get("model_dispatched") is True for d in result["model_decisions"]
        )
        claims = list((out / "model").glob("*/claim.json"))
        result["provider_calls_complete"] = len(claims) == len(
            result["model_decisions"]
        ) and all(
            d.get("model_dispatched") in (True, False)
            for d in result["model_decisions"]
        )
        if result["provider_calls_complete"]:
            result["provider_calls"] = result["confirmed_model_calls"]
        if "error_type" not in result:
            result["status"] = "terminal_pending_audit"
        publish(out / "result.json", result)
        print(
            json.dumps(
                {
                    k: v
                    for k, v in result.items()
                    if k not in {"native", "model_decisions", "binding"}
                }
            ),
            flush=True,
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--declaration-revision", required=True)
    parser.add_argument("--preflight", action="store_true")
    arguments = parser.parse_args()
    if re.fullmatch(r"[a-f0-9]{40}", arguments.declaration_revision) is None:
        parser.error("Supply the exact pushed declaration revision")
    TRIAL_ID = arguments.campaign_id
    DECLARATION_REVISION = arguments.declaration_revision
    PREFLIGHT_ONLY = arguments.preflight
    initialize()
    selection()  # Validate the ID before using it in a filesystem path.
    SESSION = BASE / TRIAL_ID
    main()

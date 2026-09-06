from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = REPO_ROOT / "infra/m1b/bootstrap_live_host.sh"
GUARD = REPO_ROOT / "infra/m1b/activate_outer_egress_guard.sh"
EXPIRY = REPO_ROOT / "infra/m1b/expire_live_host.sh"
SCRIPTS = (BOOTSTRAP, GUARD, EXPIRY)
PYTHON_HEREDOC = re.compile(r"<<'PY'\n(?P<body>.*?)\nPY", re.DOTALL)
NFT_HEREDOC = re.compile(r"<<'NFT'\n(?P<body>.*?)\nNFT", re.DOTALL)


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _python_heredoc_containing(script: Path, marker: str) -> str:
    return next(
        match.group("body")
        for match in PYTHON_HEREDOC.finditer(_text(script))
        if marker in match.group("body")
    )


def _write_docker_lifecycle_inputs(
    root: Path,
    *,
    listing_returncodes: dict[str, int] | None = None,
    removal_returncodes: dict[str, int] | None = None,
    listing_stdout: dict[str, bytes] | None = None,
) -> None:
    listing_returncodes = listing_returncodes or {}
    removal_returncodes = removal_returncodes or {}
    listing_stdout = listing_stdout or {}
    for prefix in (
        "loopback-before",
        "loopback-after",
        "forward-before",
        "forward-after",
    ):
        root.joinpath(f"{prefix}.rc").write_text(
            f"{listing_returncodes.get(prefix, 0)}\n", encoding="ascii"
        )
        root.joinpath(f"{prefix}.stdout").write_bytes(listing_stdout.get(prefix, b""))
        root.joinpath(f"{prefix}.stderr").write_bytes(b"")
    for prefix in ("loopback-removal", "forward-removal"):
        root.joinpath(f"{prefix}.rc").write_text(
            f"{removal_returncodes.get(prefix, 0)}\n", encoding="ascii"
        )
        root.joinpath(f"{prefix}.stdout").write_bytes(b"")
        root.joinpath(f"{prefix}.stderr").write_bytes(b"injected removal failure")


def _run_docker_lifecycle_verifier(root: Path) -> subprocess.CompletedProcess[str]:
    target = root / "receipt.json"
    return subprocess.run(
        [sys.executable, "-I", "-", str(root), str(target)],
        input=_python_heredoc_containing(
            GUARD, "fortgym.m1b-docker-canary-lifecycle/v1"
        ),
        text=True,
        capture_output=True,
        check=False,
    )


def _tcp_table(*peer_ports: int) -> str:
    header = "  sl  local_address rem_address   st\n"
    rows = [
        f" {index}: 0100007F:0016 0200007F:{port:04X} 01\n"
        for index, port in enumerate(peer_ports)
    ]
    return header + "".join(rows)


def _run_ssh_flow_discovery(
    root: Path,
) -> tuple[subprocess.Popen[str], Path, Path]:
    proc_root = root / "proc"
    net_root = proc_root / "net"
    net_root.mkdir(parents=True)
    tcp = net_root / "tcp"
    tcp6 = net_root / "tcp6"
    tcp.write_text(_tcp_table(49153, 49154), encoding="ascii")
    tcp6.write_text(_tcp_table(), encoding="ascii")
    target = root / "control-ssh-flow.json"
    process = subprocess.Popen(
        [sys.executable, "-I", "-", str(target), str(proc_root)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.stdin is not None
    process.stdin.write(
        _python_heredoc_containing(GUARD, "def established_ssh_flows()")
    )
    process.stdin.close()
    return process, target, tcp


def _guard_shell_function(name: str, next_name: str) -> str:
    text = _text(GUARD)
    start = text.index(f"{name}() {{")
    end = text.index(f"\n{next_name}() {{", start)
    return text[start:end]


def _expiry_shell_function(name: str, next_line: str) -> str:
    text = _text(EXPIRY)
    start = text.index(f"{name}() {{")
    end = text.index(f"\n{next_line}", start)
    return text[start:end]


def _run_injected_expiry_table_install(
    root: Path,
    *,
    list_returncode: int,
    list_stdout: str = "",
    batch_returncode: int = 0,
) -> subprocess.CompletedProcess[str]:
    batch = root / "batch.nft"
    cleanup_marker = root / "cleanup-reached"
    fake_nft = root / "nft"
    fake_nft.write_text(
        "#!/bin/bash\n"
        'if [[ "$1" == list ]]; then\n'
        f"  /usr/bin/printf '%s' {list_stdout!r}\n"
        f"  exit {list_returncode}\n"
        "fi\n"
        'if [[ "$1" == -f && "$2" == - ]]; then\n'
        f"  /bin/cat >{str(batch)!r}\n"
        f"  exit {batch_returncode}\n"
        "fi\n"
        "exit 99\n",
        encoding="utf-8",
    )
    fake_nft.chmod(0o755)
    function = _expiry_shell_function(
        "install_expiry_fail_close", "install_expiry_fail_close"
    )
    function = (
        function.replace(
            "    /usr/bin/timeout --signal=TERM --kill-after=2s 10s \\\n", ""
        )
        .replace("      /usr/bin/timeout --signal=TERM --kill-after=2s 10s \\\n", "")
        .replace("/usr/sbin/nft", str(fake_nft))
    )
    harness = (
        "set -euo pipefail\n"
        f"{function}\n"
        "install_expiry_fail_close\n"
        f"/usr/bin/touch {str(cleanup_marker)!r}\n"
    )
    return subprocess.run(
        ["/bin/bash", "-c", harness],
        text=True,
        capture_output=True,
        check=False,
    )


def _run_injected_docker_cleanup(
    root: Path,
    *,
    removal_returncode: int,
    listing_returncode: int,
    listing_stdout: str = "",
) -> subprocess.CompletedProcess[str]:
    fake_docker = root / "docker"
    fake_docker.write_text(
        "#!/bin/bash\n"
        'if [[ "$1" == rm ]]; then\n'
        f"  exit {removal_returncode}\n"
        "fi\n"
        'if [[ "$1" == ps ]]; then\n'
        f"  /usr/bin/printf '%s' {listing_stdout!r}\n"
        f"  exit {listing_returncode}\n"
        "fi\n"
        "exit 99\n",
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)
    functions = (
        _guard_shell_function("capture_docker_name_listing", "capture_docker_removal")
        + "\n"
        + _guard_shell_function("capture_docker_removal", "cleanup_security_canaries")
    )
    functions = functions.replace(
        "    /usr/bin/timeout --signal=TERM --kill-after=2s 15s \\\n", ""
    ).replace("/usr/bin/docker", str(fake_docker))
    prefix = root / "injected"
    harness = (
        "set -euo pipefail\n"
        f"{functions}\n"
        f"capture_docker_removal canary {prefix}-removal\n"
        f"capture_docker_name_listing canary {prefix}-after injected-cleanup 70\n"
    )
    return subprocess.run(
        ["/bin/bash", "-c", harness],
        text=True,
        capture_output=True,
        check=False,
    )


def _run_root_evidence_topology_verifier(
    root: Path,
) -> subprocess.CompletedProcess[str]:
    verifier = _python_heredoc_containing(
        GUARD, "required root evidence directory is absent"
    )
    verifier = verifier.replace(
        "root_info.st_uid != 0", "root_info.st_uid != int(sys.argv[2])"
    )
    verifier = verifier.replace(
        "root_info.st_gid != 0", "root_info.st_gid != int(sys.argv[3])"
    )
    verifier = verifier.replace("info.st_uid != 0", "info.st_uid != int(sys.argv[2])")
    verifier = verifier.replace("info.st_gid != 0", "info.st_gid != int(sys.argv[3])")
    root_info = root.lstat()
    return subprocess.run(
        [
            sys.executable,
            "-I",
            "-",
            str(root),
            str(root_info.st_uid),
            str(root_info.st_gid),
        ],
        input=verifier,
        text=True,
        capture_output=True,
        check=False,
    )


def _run_injected_bind_sources_mount_check(
    root: Path, *, returncode: int, stdout: str = ""
) -> subprocess.CompletedProcess[str]:
    fake_findmnt = root / "findmnt"
    fake_findmnt.write_text(
        f"#!/bin/bash\n/usr/bin/printf '%s' {stdout!r}\nexit {returncode}\n",
        encoding="utf-8",
    )
    fake_findmnt.chmod(0o755)
    function = _guard_shell_function(
        "verify_bind_sources_unmounted", "capture_live_rules"
    )
    function = function.replace(
        "    /usr/bin/timeout --signal=TERM --kill-after=2s 10s \\\n", ""
    ).replace("/usr/bin/findmnt", str(fake_findmnt))
    guard_work = root / "work"
    guard_work.mkdir(mode=0o700)
    bind_sources = root / "root-evidence" / "bind-sources"
    bind_sources.mkdir(parents=True, mode=0o700)
    harness = (
        "set -euo pipefail\n"
        f"root_evidence={str(bind_sources.parent)!r}\n"
        f"guard_work={str(guard_work)!r}\n"
        "mode=verify-only\n"
        f"{function}\n"
        "verify_bind_sources_unmounted\n"
    )
    return subprocess.run(
        ["/bin/bash", "-c", harness],
        text=True,
        capture_output=True,
        check=False,
    )


def test_security_scripts_are_shell_and_embedded_python_syntax_clean() -> None:
    for script in SCRIPTS:
        subprocess.run(
            ["/bin/bash", "-n", str(script)],
            check=True,
            capture_output=True,
            text=True,
        )
        blocks = [
            match.group("body") for match in PYTHON_HEREDOC.finditer(_text(script))
        ]
        assert blocks, f"{script.name} must contain at least one explicit verifier"
        for index, block in enumerate(blocks):
            compile(block, f"{script.name}:heredoc-{index}", "exec")


def test_bootstrap_requires_out_of_band_digest_and_exact_packet_set() -> None:
    text = _text(BOOTSTRAP)
    expected = {
        "docker-runtime-manifest.json",
        "MANIFEST.sha256",
        "PACKET.json",
        "fortgym-df-m1a.tar.zst",
        "fortgym-m1b-docker-runtime.tar",
        "fortgym-m1b-source.tar",
        "fortgym-m1b-wheelhouse.tar",
        "live-requirements.lock",
        "live-wheelhouse.sha256",
        "seed_tree.sha256z",
        "source-manifest.json",
    }
    required_block = text.split("required = {", 1)[1].split("}", 1)[0]
    observed = set(
        re.findall(r'^\s+"([A-Za-z0-9_.+-]+)",$', required_block, re.MULTILINE)
    )

    assert observed == expected
    assert "--manifest-sha256" in text
    assert "out-of-band MANIFEST.sha256 digest differs" in text
    assert "packet top-level filename set differs" in text
    assert "MANIFEST.sha256 filename set differs" in text
    assert 'packet_dir="$packet_stage"' in text
    assert "/opt/fortgym-m1b/runtime-image.tar.zst" in text
    assert 'docker image inspect "$expected_runtime_image_ref"' in text
    assert "loaded runtime image identity or platform differs" in text
    assert '"runtime_image_id": sys.argv[8]' in text


def test_bootstrap_archive_preflight_is_type_path_and_content_bound() -> None:
    text = _text(BOOTSTRAP)

    assert "safe_member_name" in text
    assert "member.isfile()" in text
    assert "tarfile.REGTYPE" in text
    assert "member.issym()" in text
    assert "member.islnk()" in text
    assert "unsafe PAX headers" in text
    assert "duplicate tar member" in text
    assert "tar filename set differs" in text
    assert "tar member size differs" in text
    assert "tar digest differs" in text
    assert "os.O_EXCL | os.O_NOFOLLOW" in text
    assert "extractall(" not in text
    assert re.search(r"(?m)^\s*tar\s+-[A-Za-z]*x", text) is None


def test_bootstrap_uses_isolated_python_and_explicit_checks() -> None:
    text = _text(BOOTSTRAP)

    assert re.search(r"(?m)^\s*assert\b", text) is None
    assert "/usr/bin/python3 -m" not in text
    assert "/usr/bin/python3 - " not in text
    assert '/usr/bin/python3 -I -m venv --copies "$venv_root"' in text
    assert '"$venv_root/bin/python" -I' in text
    assert "sys.flags.isolated == 1" in text
    assert "PYTHONPATH=" not in text
    assert "unset BASH_ENV CDPATH ENV GLOBIGNORE PYTHONHOME PYTHONPATH" in text
    assert "provider credentials reached the bootstrap check" in text


def test_bootstrap_has_one_semantic_sudo_target_and_no_docker_group() -> None:
    text = _text(BOOTSTRAP)
    sudo_rule = (
        "fortgym ALL=(root) NOPASSWD: "
        "/usr/local/libexec/fortgym-m1b-root-broker --request "
        "/var/lib/fortgym-m1b/broker/requests/*.json"
    )

    assert text.count("NOPASSWD:") == 1
    assert sudo_rule in text
    assert "--groups docker" not in text
    assert "usermod" not in text
    assert "chown" not in text
    assert "service user group membership is broader than its private group" in text
    assert "service user unexpectedly has direct Docker socket access" in text
    assert "/bin/kill -KILL" not in text
    assert "/bin/systemctl restart docker.service" not in text
    assert '"$state_root/broker/requests"' in text
    assert '"$state_root/broker/claims" "$state_root/broker/claims/incoming"' in text
    assert '"$state_root/broker/grants" "$state_root/broker/receipts"' in text
    assert '"$state_root/broker/state"' in text
    assert '"$state_root/broker/state/inflight"' in text
    assert '"$state_root/canary"' in text
    assert '"$root_evidence/batches"' in text
    assert '"$root_evidence/bind-sources"' in text


def test_bootstrap_preserves_root_trust_while_exposing_only_runner_inputs() -> None:
    text = _text(BOOTSTRAP)

    assert '/bin/chmod 0755 "$install_root" "$packet_stage" "$venv_root"' in text
    assert (
        '/bin/chmod 0644 "$packet_stage/PACKET.json" "$packet_stage/source-manifest.json"'
        in text
    )
    assert "source_root_owned_nonwritable" in text
    assert "site_packages_owned_nonwritable" in text
    assert "fortgym-m1b-source.pth" in text
    assert 'source_pth.read_bytes() == b"/opt/fort-gym-m1a\\n"' in text
    assert "broker_owned_nonwritable" in text
    assert "packet_archives_root_only" in text
    assert "broker_receipts_root_only" in text
    assert (
        'runuser -u "$service_user" -- /usr/bin/test -x "$venv_root/bin/python"' in text
    )
    assert (
        'runuser -u "$service_user" -- /usr/bin/test -r "$install_root/runtime-image.tar.zst"'
        in text
    )
    assert '"$venv_root/bin/python" -I -' in text
    assert "nonroot import smoke unexpectedly retained root" in text
    assert "p1_measurement_code_digest()" in text
    assert '"nonroot_isolated_import_ok": True' in text
    assert '"nonroot_measurement_code_digest_ok": True' in text


def test_root_evidence_is_private_atomic_nofollow_and_never_service_owned() -> None:
    bootstrap = _text(BOOTSTRAP)
    guard = _text(GUARD)
    expiry = _text(EXPIRY)

    for text in (bootstrap, guard, expiry):
        assert "root_evidence" in text
        assert "os.O_NOFOLLOW" in text
        assert "os.link(" in text
        assert "os.fsync" in text
        assert "0o600" in text
        assert re.search(r"(?m)^\s*assert\b", text) is None
        assert "chown fortgym" not in text
    assert '"$install_root" "$packet_stage" "$docker_runtime_root"' in bootstrap
    assert "root:root:700" in bootstrap
    assert "root evidence trusted directory ownership or mode drifted" in bootstrap
    assert "root evidence bind-sources directory is not empty" in bootstrap
    assert "! -name batches ! -name bind-sources" in bootstrap
    assert "! -links 1" in bootstrap
    assert "immutable evidence target already exists" in bootstrap
    assert "immutable evidence target already exists" in guard
    assert "immutable expiry evidence already exists" in expiry


def test_build_commands_have_fixed_environment_and_absolute_tools() -> None:
    text = _text(BOOTSTRAP)

    assert "build_env=(" in text
    assert "CC=/usr/bin/gcc" in text
    assert "CLANG=/usr/bin/clang" in text
    assert "LLVM_STRIP=/usr/bin/llvm-strip" in text
    assert "PKG_CONFIG=/usr/bin/pkg-config" in text
    assert '"${build_env[@]}" /usr/bin/make' in text
    assert "/usr/bin/env -i" in text


def test_exact_expiry_timer_and_provider_deletion_remain_independent() -> None:
    bootstrap = _text(BOOTSTRAP)
    expiry = _text(EXPIRY)

    assert "date -u -d \"$authority_expiry\" '+%Y-%m-%d %H:%M:%S UTC'" in bootstrap
    assert '"OnCalendar=$timer_on_calendar"' in bootstrap
    assert "AccuracySec=1us" in bootstrap
    assert "RandomizedDelaySec=0" in bootstrap
    assert "Persistent=true" in bootstrap
    assert "NextElapseUSecRealtime" in bootstrap
    assert (
        '"$manifest_sha256" "$broker_installed_sha256" "$authority_expiry"' in bootstrap
    )
    assert '"expiry_timer_next_elapse": sys.argv[5]' in bootstrap
    assert (
        "ExecStart=/usr/bin/env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin LC_ALL=C "
        "/bin/bash --noprofile --norc /usr/local/libexec/fortgym-m1b-expire-live-host"
        in bootstrap
    )
    assert "refusing to revoke M1b authority before its exact expiry" in expiry
    assert "provider deletion remains mandatory" in expiry.lower()
    assert '"provider_api_called": False' in expiry
    assert expiry.count("delete table inet fortgym_m1b_expired") == 1
    assert '"outer_egress_fail_close_retained": True' in expiry
    assert "table inet fortgym_m1b_expired" in expiry
    assert "type filter hook output priority -300; policy drop;" in expiry
    assert "type filter hook forward priority -300; policy drop;" in expiry
    assert '"previous_control_ssh_flow_revoked": True' in expiry


def test_bootstrap_installs_only_packet_bound_docker_ce_before_first_start() -> None:
    text = _text(BOOTSTRAP)

    assert "fortgym-m1b-docker-runtime.tar" in text
    assert "docker-runtime-manifest.json" in text
    assert "fortgym.m1b-docker-runtime/v1" in text
    assert "9DC858229FC7DD38854AE2D88D81803C0EBFCD88" in text
    assert "D3306A018370199E527AE7997EA0A9C3F273FCD8" in text
    assert "docker-ce_29.1.3-1~debian.12~bookworm_amd64.deb" in text
    assert "docker-ce-cli_29.1.3-1~debian.12~bookworm_amd64.deb" in text
    assert "containerd.io_2.2.1-1~debian.12~bookworm_amd64.deb" in text
    apt_install = text.split("/usr/bin/apt-get install", 1)[1].split("\n\n", 1)[0]
    assert "docker.io" not in apt_install
    assert "/usr/bin/dpkg --install" in text
    assert '{"features":{"containerd-snapshotter":true},"userland-proxy":false}' in text
    assert '"userland_proxy_disabled": True' in text
    assert '"docker_userland_proxy_disabled": True' in text
    assert text.index("/usr/sbin/policy-rc.d") < text.index("/usr/bin/apt-get update")
    assert "apt-update.txt" in text
    assert "apt-install.txt" in text
    assert "docker-packages.tsv" in text
    assert "provider-toolchain.txt" in text
    assert "provider-capability-probe.stderr" in text
    assert "LIBBPF_LOG_LEVEL=debug" in text
    assert 'packet["acceptance_sha256"]' in text
    assert 'b"\\0".join(part.encode("ascii") for part in identity_parts)' in text
    assert "bootstrap-probe-${provider_probe_identity:0:16}" in text
    assert (
        "785246b86ef022b7e49b4b8291e6c73eeb96f262d502e1182fa541731f4509fb" not in text
    )
    assert text.index(
        '/usr/bin/install -o root -g root -m 0644 "$bootstrap_work/daemon.json"'
    ) < text.index("/usr/bin/dpkg --install")
    assert text.index("/usr/bin/dpkg --install") < text.index(
        "/usr/bin/systemctl enable --now"
    )
    assert "Docker Server.Version differs from 29.1.3" in text
    assert '["driver-type", "io.containerd.snapshotter.v1"]' in text
    version_pattern_match = re.search(
        r'CONTAINERD_VERSION_PATTERN = \(\n\s+r"([^"]+)"\n\s+r"([^"]+)"\n\)',
        text,
    )
    assert version_pattern_match is not None
    version_pattern = "".join(version_pattern_match.groups())
    assert re.fullmatch(
        version_pattern,
        "containerd containerd.io v2.2.1 dea7da592f5d1d2b7755e3a161be07f43fad8f75\n",
    )
    assert not re.fullmatch(
        version_pattern,
        "containerd github.com/containerd/containerd/v2 v2.2.1 "
        "dea7da592f5d1d2b7755e3a161be07f43fad8f75\n",
    )
    assert not re.fullmatch(
        version_pattern,
        "containerd containerd.io v2.2.1 " + "0" * 40 + "\n",
    )
    assert '"docker_server_29_1_3_containerd_store": True' in text
    assert '"distro_docker_io_installed": False' in text


def test_bootstrap_attests_exact_runtime_descriptor_archive_and_provider_helper() -> (
    None
):
    text = _text(BOOTSTRAP)

    assert 'descriptor.get("digest") != sys.argv[2]' in text
    assert 'descriptor.get("size") != 2306' in text
    assert '"application/vnd.oci.image.manifest.v1+json"' in text
    assert 'f"fortgym-df@{sys.argv[2]}" not in repo_digests' in text
    assert "docker-image-descriptor-attestation.json" in text
    assert "runtime-archive-attestation.json" in text
    assert "provider-helper-bpf-attestation.json" in text
    assert '"runtime_archive_digest_exact": True' in text
    assert '"provider_helper_bpf_attested": True' in text
    assert '"reproducible_build_outputs_match": True' in text
    assert "/usr/local/libexec/fortgym-provider-network-helper probe" in text
    assert "/usr/local/libexec/fortgym-provider-network-helper prepare" in text
    assert "/usr/local/libexec/fortgym-provider-network-helper enter" in text
    assert "/usr/local/libexec/fortgym-provider-network-helper snapshot" in text
    assert text.count("/usr/local/libexec/fortgym-provider-network-helper cleanup") >= 3
    assert "--negative-canary-poison 203.0.113.77:44444" in text
    assert "FORT_GYM_NETWORK_ALLOWED_HOST=127.0.0.1" in text
    assert 'snapshot.get("event_count") == 7' in text
    assert '"negative_canary_event_count": 6' in text
    assert '"live_setuid_helper_exercised_as_nonroot": True' in text
    assert '"kernel_bpf_load_attested": True' in text
    assert '"cgroup_hooks_attached": True' in text
    assert '"default_deny_negative_canary_attested": True' in text
    assert '"exact_loopback_allow_attested": True' in text
    assert '"zero_lost_events": True' in text
    assert '"cleanup_idempotent": True' in text
    assert text.index('"provider_helper_bpf_attested": True') > text.index(
        'snapshot.get("event_count") == 7'
    )
    provider_verifier = next(
        block
        for block in PYTHON_HEREDOC.findall(text)
        if "fortgym.m1b-provider-helper-bpf-attestation/v1" in block
    )
    compile(provider_verifier, "provider-helper-bpf-verifier", "exec")
    for index, name in enumerate(
        (
            "probe_path",
            "prepare_path",
            "snapshot_path",
            "cleanup_path",
            "cleanup_idempotent_path",
            "guard_path",
            "inner_path",
        ),
        start=9,
    ):
        assert f"{name} = pathlib.Path(sys.argv[{index}])" in provider_verifier
    assert '"docker_runtime_attestation_sha256"' in text
    assert '"runtime_archive_attestation_sha256"' in text
    assert '"provider_helper_bpf_attestation_sha256"' in text
    assert '"docker_image_descriptor_attestation_sha256"' in text
    assert '"trusted_paths_sha256"' in text


def test_expiry_fail_close_precedes_and_bounds_all_cleanup() -> None:
    text = _text(EXPIRY)

    assert text.count("table inet fortgym_m1b_expired {") == 2
    nft_blocks = [match.group("body") for match in NFT_HEREDOC.finditer(text)]
    assert len(nft_blocks) == 2
    replacement_lines = nft_blocks[0].splitlines()
    assert replacement_lines[0] == "delete table inet fortgym_m1b_expired"
    assert "\n".join(replacement_lines[1:]) == nft_blocks[1]
    first_fail_close = text.index("table inet fortgym_m1b_expired {")
    first_cleanup = text.index("bounded_cleanup 5s /bin/rm")
    assert first_fail_close < first_cleanup
    assert text.index("early expiry fail-close base chain differs") < first_cleanup
    assert "type filter hook output priority -300; policy drop;" in text
    assert "type filter hook forward priority -300; policy drop;" in text
    for command in (
        "pkill -KILL",
        "docker ps",
        "docker rm --force",
        "findmnt --raw",
        "/usr/bin/awk",
        "/bin/umount",
        "systemctl stop",
        "systemctl mask",
        "/bin/rmdir",
    ):
        lines = [line for line in text.splitlines() if command in line]
        assert lines, command
        assert all("bounded_cleanup" in line for line in lines), command
    assert '"expiry_fail_close_installed_before_cleanup": True' in text
    assert '"cleanup_commands_bounded": True' in text
    assert "/var/lib/fortgym-m1b-root-evidence/bind-sources/" in text
    assert '"root_bind_source_unmount_attempted": True' in text
    assert '"root_bind_source_empty_directory_cleanup_attempted": True' in text


def test_expiry_atomically_replaces_malformed_preexisting_table(tmp_path: Path) -> None:
    result = _run_injected_expiry_table_install(
        tmp_path,
        list_returncode=0,
        list_stdout="table inet fortgym_m1b_expired { chain output { policy accept; } }\n",
    )

    assert result.returncode == 0, result.stderr
    batch = tmp_path.joinpath("batch.nft").read_text(encoding="utf-8")
    assert batch.startswith("delete table inet fortgym_m1b_expired\n")
    assert "type filter hook output priority -300; policy drop;" in batch
    assert "type filter hook forward priority -300; policy drop;" in batch
    assert tmp_path.joinpath("cleanup-reached").is_file()


def test_expiry_replacement_failure_stops_before_cleanup(tmp_path: Path) -> None:
    result = _run_injected_expiry_table_install(
        tmp_path,
        list_returncode=0,
        list_stdout="malformed pre-existing table\n",
        batch_returncode=125,
    )

    assert result.returncode == 125
    assert not tmp_path.joinpath("cleanup-reached").exists()


def test_outer_guard_has_exact_fail_close_and_live_counter_proofs() -> None:
    text = _text(GUARD)

    assert text.count("type filter hook output priority -200; policy drop;") == 1
    assert text.count("type filter hook forward priority -10; policy drop;") == 1
    assert "ssh_flow_rule=" in text
    assert "expected one exact established SSH control flow" in text
    assert "tcp sport 22 tcp dport $ssh_client_port counter accept" in text
    assert "ct state" not in text
    assert "established,related" not in text
    assert "FORTGYM_M1B_EXACT_SSH_FLOW_CHECKPOINT" in text
    assert 'receipt.get("runtime_image_id") != sys.argv[4]' in text
    assert "exact SSH control-flow checkpoint was not observed live" in text
    assert "counter name output_denied reject" in text
    assert "counter name forward_denied reject" in text
    assert "verify_live_rules" in text
    assert text.count("verify_live_rules ") >= 2
    assert "output_after - output_before < 2" in text
    assert "forward_after - forward_before < 1" in text
    assert "198.51.100.10" in text
    assert "203.0.113.10" in text
    assert "2001:db8::10" in text
    assert "--network bridge" in text
    assert "--pull never" in text
    assert "--publish 127.0.0.1:44991:44991/tcp" in text
    assert "FORTGYM_LOOPBACK_OK" in text
    assert "while len(response) < 128:" in text
    assert 'if response.endswith(b"\\n"):' in text
    assert 'if observed == b"FORTGYM_LOOPBACK_OK\\n":' in text
    assert 'last_error = "UnexpectedResponse"' in text
    assert "/usr/bin/pgrep --exact docker-proxy" in text
    assert "Docker userland proxy remains enabled" in text
    assert '"docker_userland_proxy_process_absent": True' in text
    assert "sha256={hashlib.sha256(last_unexpected).hexdigest()}" in text
    assert '"real_df_runtime_attempt": False' in text
    assert "loopback canary residue remains" in text
    assert "forward canary residue remains" in text
    assert "capture_docker_name_listing" in text
    assert "capture_docker_removal" in text
    assert "fortgym.m1b-docker-canary-lifecycle/v1" in text
    assert '"all_absence_listings_returncode_zero": True' in text
    assert '"all_absence_stdout_exact_empty": True' in text
    assert '"removal_failure_accepted_only_after_independent_absence": True' in text
    assert "/usr/bin/docker ps" in text
    assert "docker ps --all --quiet --no-trunc" not in "\n".join(
        line for line in text.splitlines() if "/usr/bin/grep" in line
    )
    assert "provider_calls" in text
    assert "provider_cost_usd" in text
    assert '"acceptance_sha256": sys.argv[10]' in text


def test_outer_guard_waits_for_one_stable_control_flow(tmp_path: Path) -> None:
    process, target, tcp = _run_ssh_flow_discovery(tmp_path)
    time.sleep(0.35)
    tcp.write_text(_tcp_table(49153), encoding="ascii")
    returncode = process.wait(timeout=3)
    stderr = process.stderr.read() if process.stderr is not None else ""

    assert returncode == 0, stderr
    assert json.loads(target.read_text(encoding="utf-8")) == {
        "schema": "fortgym.m1b-control-ssh-flow/v1",
        "exact_flow_count": 1,
        "flow": {
            "family": "ipv4",
            "server_address": "127.0.0.1",
            "server_port": 22,
            "client_address": "127.0.0.2",
            "client_port": 49153,
        },
    }


def test_outer_guard_has_read_only_post_run_verification_seam() -> None:
    text = _text(GUARD)

    assert '[[ "$1" == --verify-only ]]' in text
    assert "FORTGYM_M1B_POST_RUN_SSH_CHECKPOINT" in text
    assert "post_run_ssh_after - post_run_ssh_before < 1" in text
    assert '"verification_mode": "read-only"' in text
    assert '"network_rules_mutated": False' in text
    assert "outer-egress-post-run-rules-before.json" in text
    assert "outer-egress-post-run-rules.json" in text
    assert "outer-egress-post-run.json" in text
    assert '"bind_sources_residue": bind_sources_residue' in text
    assert "fortgym.m1b-bind-sources-residue/v1" in text


def test_outer_guard_allows_only_exact_root_evidence_trusted_directories() -> None:
    text = _text(GUARD)
    verifier = _python_heredoc_containing(
        GUARD, "required root evidence directory is absent"
    )

    assert "verify_root_evidence_topology" in text
    assert text.count("verify_root_evidence_topology") >= 4
    assert 'required_directories = {"batches", "bind-sources"}' in verifier
    assert "if not required_directories.issubset(names)" in verifier
    assert "if name in required_directories" in verifier
    assert 'if name == "bind-sources"' in verifier
    assert "if os.listdir(bind_sources_fd)" in verifier
    assert "stat.S_ISDIR(info.st_mode)" in verifier
    assert "stat.S_ISREG(info.st_mode)" in verifier
    assert "stat.S_IMODE(info.st_mode) != 0o700" in verifier
    assert "stat.S_IMODE(info.st_mode) != 0o600" in verifier
    assert "info.st_nlink != 1" in verifier
    compile(verifier, "root-evidence-topology", "exec")


def test_outer_guard_rejects_nonempty_bind_sources(tmp_path: Path) -> None:
    root = tmp_path / "root-evidence"
    root.mkdir(mode=0o700)
    root.joinpath("batches").mkdir(mode=0o700)
    bind_sources = root / "bind-sources"
    bind_sources.mkdir(mode=0o700)
    bind_sources.joinpath("g02-a01-peer_a").mkdir(mode=0o700)

    result = _run_root_evidence_topology_verifier(root)

    assert result.returncode != 0
    assert "root evidence bind-sources directory is not empty" in result.stderr


def test_outer_guard_root_evidence_topology_rejects_every_other_directory_and_hardlink(
    tmp_path: Path,
) -> None:
    valid = tmp_path / "valid"
    valid.mkdir(mode=0o700)
    valid.joinpath("batches").mkdir(mode=0o700)
    valid.joinpath("bind-sources").mkdir(mode=0o700)
    valid.joinpath("bootstrap.json").write_text("{}\n", encoding="utf-8")
    valid.joinpath("bootstrap.json").chmod(0o600)
    assert _run_root_evidence_topology_verifier(valid).returncode == 0

    missing = tmp_path / "missing"
    missing.mkdir(mode=0o700)
    missing.joinpath("batches").mkdir(mode=0o700)
    missing_result = _run_root_evidence_topology_verifier(missing)
    assert missing_result.returncode != 0
    assert "required root evidence directory is absent" in missing_result.stderr

    wrong_mode = tmp_path / "wrong-mode"
    wrong_mode.mkdir(mode=0o700)
    wrong_mode.joinpath("batches").mkdir(mode=0o755)
    wrong_mode.joinpath("bind-sources").mkdir(mode=0o700)
    wrong_mode_result = _run_root_evidence_topology_verifier(wrong_mode)
    assert wrong_mode_result.returncode != 0
    assert (
        "root evidence directory metadata differs: batches" in wrong_mode_result.stderr
    )

    extra_directory = tmp_path / "extra-directory"
    extra_directory.mkdir(mode=0o700)
    extra_directory.joinpath("batches").mkdir(mode=0o700)
    extra_directory.joinpath("bind-sources").mkdir(mode=0o700)
    extra_directory.joinpath("unexpected").mkdir(mode=0o700)
    extra_result = _run_root_evidence_topology_verifier(extra_directory)
    assert extra_result.returncode != 0
    assert "top-level member metadata differs: unexpected" in extra_result.stderr

    hardlink = tmp_path / "hardlink"
    hardlink.mkdir(mode=0o700)
    hardlink.joinpath("batches").mkdir(mode=0o700)
    hardlink.joinpath("bind-sources").mkdir(mode=0o700)
    hardlink.joinpath("bootstrap.json").write_text("{}\n", encoding="utf-8")
    hardlink.joinpath("bootstrap.json").chmod(0o600)
    hardlink.joinpath("bootstrap-alias.json").hardlink_to(hardlink / "bootstrap.json")
    hardlink_result = _run_root_evidence_topology_verifier(hardlink)
    assert hardlink_result.returncode != 0
    assert "top-level member metadata differs" in hardlink_result.stderr


def test_outer_guard_rejects_mounted_bind_sources(tmp_path: Path) -> None:
    result = _run_injected_bind_sources_mount_check(
        tmp_path,
        returncode=0,
        stdout=f"{tmp_path}/root-evidence/bind-sources\n",
    )

    assert result.returncode == 70
    assert "bind-sources directory is mounted or findmnt failed" in result.stderr


def test_outer_guard_rejects_bind_sources_findmnt_failure(tmp_path: Path) -> None:
    result = _run_injected_bind_sources_mount_check(tmp_path, returncode=125)

    assert result.returncode == 70
    assert "bind-sources directory is mounted or findmnt failed" in result.stderr


def test_outer_guard_records_exact_unmounted_bind_sources_proof(tmp_path: Path) -> None:
    result = _run_injected_bind_sources_mount_check(tmp_path, returncode=1)

    assert result.returncode == 0, result.stderr
    receipt = json.loads(
        tmp_path.joinpath("work/bind-sources-residue.json").read_text(encoding="utf-8")
    )
    assert receipt == {
        "schema": "fortgym.m1b-bind-sources-residue/v1",
        "ok": True,
        "mode": "verify-only",
        "path": str(tmp_path / "root-evidence/bind-sources"),
        "empty": True,
        "unmounted": True,
        "findmnt_returncode": 1,
        "findmnt_stdout_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "findmnt_stderr_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    }


def test_docker_absence_verifier_allows_failed_rm_only_after_rc0_empty_ps(
    tmp_path: Path,
) -> None:
    _write_docker_lifecycle_inputs(
        tmp_path,
        removal_returncodes={
            "loopback-removal": 125,
            "forward-removal": 1,
        },
    )

    result = _run_docker_lifecycle_verifier(tmp_path)

    assert result.returncode == 0, result.stderr
    receipt = json.loads(tmp_path.joinpath("receipt.json").read_text(encoding="utf-8"))
    assert receipt["removals"]["loopback"]["returncode"] == 125
    assert receipt["removals"]["forward"]["returncode"] == 1
    assert receipt["all_absence_listings_returncode_zero"] is True
    assert receipt["all_absence_stdout_exact_empty"] is True


def test_docker_absence_verifier_rejects_injected_ps_rc125(tmp_path: Path) -> None:
    _write_docker_lifecycle_inputs(
        tmp_path,
        listing_returncodes={"forward-after": 125},
    )

    result = _run_docker_lifecycle_verifier(tmp_path)

    assert result.returncode != 0
    assert "Docker exact-name absence proof differs" in result.stderr
    assert not tmp_path.joinpath("receipt.json").exists()


def test_docker_absence_verifier_rejects_rm_failure_plus_ps_failure(
    tmp_path: Path,
) -> None:
    _write_docker_lifecycle_inputs(
        tmp_path,
        listing_returncodes={"loopback-after": 125},
        removal_returncodes={"loopback-removal": 125},
    )

    result = _run_docker_lifecycle_verifier(tmp_path)

    assert result.returncode != 0
    assert "Docker exact-name absence proof differs" in result.stderr
    assert not tmp_path.joinpath("receipt.json").exists()


def test_docker_absence_verifier_rejects_nonempty_listing(tmp_path: Path) -> None:
    _write_docker_lifecycle_inputs(
        tmp_path,
        listing_stdout={"loopback-before": b"a" * 64 + b"\n"},
    )

    result = _run_docker_lifecycle_verifier(tmp_path)

    assert result.returncode != 0
    assert "Docker exact-name absence proof differs" in result.stderr
    assert not tmp_path.joinpath("receipt.json").exists()


def test_guard_shell_allows_rm125_only_after_independent_rc0_empty_ps(
    tmp_path: Path,
) -> None:
    result = _run_injected_docker_cleanup(
        tmp_path,
        removal_returncode=125,
        listing_returncode=0,
    )

    assert result.returncode == 0, result.stderr
    assert tmp_path.joinpath("injected-removal.rc").read_text() == "125\n"
    assert tmp_path.joinpath("injected-after.rc").read_text() == "0\n"
    assert tmp_path.joinpath("injected-after.stdout").read_bytes() == b""


def test_guard_shell_rejects_rm_failure_followed_by_ps_failure(
    tmp_path: Path,
) -> None:
    result = _run_injected_docker_cleanup(
        tmp_path,
        removal_returncode=125,
        listing_returncode=125,
    )

    assert result.returncode == 70
    assert "Docker listing failed with return code 125" in result.stderr
    assert tmp_path.joinpath("injected-removal.rc").read_text() == "125\n"
    assert tmp_path.joinpath("injected-after.rc").read_text() == "125\n"

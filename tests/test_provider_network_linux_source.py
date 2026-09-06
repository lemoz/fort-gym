from __future__ import annotations

import os
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "infra" / "m1b" / "provider_network"


def _text(name: str) -> str:
    return (SOURCE_ROOT / name).read_text(encoding="utf-8")


def _c_function(source: str, signature: str) -> str:
    start = source.index(signature)
    opening = source.index("{", start)
    depth = 0
    for index in range(opening, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    raise AssertionError(f"unterminated C function: {signature}")


def test_bpf_source_has_exact_default_deny_hook_surface() -> None:
    source = _text("provider_network.bpf.c")

    assert source.count('SEC("cgroup/connect4")') == 1
    assert source.count('SEC("cgroup/connect6")') == 1
    assert source.count('SEC("cgroup/sendmsg4")') == 1
    assert source.count('SEC("cgroup/sendmsg6")') == 1
    assert "hook == FORTGYM_HOOK_CONNECT4" in source
    assert "ctx->user_family == AF_INET" in source
    assert "#ifndef AF_INET\n#define AF_INET 2\n#endif" in source
    assert "ctx->protocol == IPPROTO_TCP" in source
    assert "ctx->user_ip4 == configured->allowed_ipv4_be" in source
    assert "ctx->user_port == configured->allowed_port_be" in source
    assert "hook == FORTGYM_HOOK_CONNECT4 || hook == FORTGYM_HOOK_SENDMSG4" in source
    assert source.count("event->destination_ipv4_be = ctx->user_ip4;") == 1
    assert source.count("event->destination_ipv6, ctx->user_ip6") == 1
    assert "return allowed ? 1 : 0;" in source
    assert "note_lost_event();" in source


def test_helper_exposes_only_exact_json_commands_and_atomic_enter() -> None:
    source = _text("provider_network_helper.c")

    for command in ("probe", "prepare", "enter", "snapshot", "inspect", "cleanup"):
        assert f"command_{command}" in source
        assert f'strcmp(argv[1], "{command}") == 0' in source
    for schema in (
        "fortgym.provider-network-capabilities/v1",
        "fortgym.provider-network-prepare/v1",
        "fortgym.provider-network-inspect/v1",
        "fortgym.provider-network-capture/v1",
        "fortgym.provider-network-cleanup/v1",
        "fortgym.python-network-guard-attestation/v1",
    ):
        assert schema in source
    assert source.index("update_guard_policy(") < source.index("join_owned_cgroup(")
    enter_body = source[source.index("static int command_enter") :]
    assert enter_body.index("join_owned_cgroup(cgroup_path)") < enter_body.index(
        "perform_negative_canary(&policy)"
    )
    assert enter_body.index("perform_negative_canary(&policy)") < enter_body.index(
        "write_guard_attestation_as_caller("
    )
    assert enter_body.index("write_guard_attestation_as_caller(") < enter_body.index(
        "execve(argv[11], &argv[11], environ)"
    )
    assert "PR_SET_NO_NEW_PRIVS" in source
    assert "PR_CAP_AMBIENT_CLEAR_ALL" in source
    assert "expect_denied_connect4" in source
    assert "expect_denied_connect6" in source
    assert "expect_denied_sendmsg4" in source
    assert "expect_denied_sendmsg6" in source
    assert "BPF object open failed" in source
    assert "required BPF program is absent" in source
    assert "required BPF map is absent" in source
    assert "BPF object load failed: result=%d errno=%d %s" in source
    assert "#define FORTGYM_BPF_LOG_BYTES 65536" in source
    assert ".kernel_log_buf = bpf_kernel_log" in source
    assert ".kernel_log_size = sizeof(bpf_kernel_log)" in source
    assert ".kernel_log_level = 1" in source
    assert "BPF verifier log follows" in source


def test_enter_guard_is_single_create_fail_closed_and_recoverable() -> None:
    source = _text("provider_network_helper.c")
    writer = _c_function(source, "static int write_guard_payload_exclusive")
    enter = _c_function(source, "static int command_enter")

    exclusive_opens = re.findall(r"\bopen\s*\([^;]*\bO_EXCL\b[^;]*\);", source)
    assert len(exclusive_opens) == 1
    assert writer.count("open(") == 1
    assert "O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC | O_NOFOLLOW" in writer
    assert "goto remove_partial;" in writer
    close_failure = writer.index("if (close(descriptor) != 0)")
    close_failure_unlink = writer.index("(void)unlink(path);", close_failure)
    close_failure_return = writer.index("return -1;", close_failure)
    assert close_failure < close_failure_unlink < close_failure_return
    remove_partial = writer.index("remove_partial:")
    assert writer.index("(void)unlink(path);", remove_partial) < writer.index(
        "(void)close(descriptor);", remove_partial
    )
    assert enter.count("owned enforcement") == 2
    assert enter.count("reconciliation") == 2
    failed_guard = enter.index("write_guard_attestation_as_caller(")
    failure_return = enter.index("return fail_closed(", failed_guard)
    inner_exec = enter.index("execve(argv[11], &argv[11], environ)")
    assert failed_guard < failure_return < inner_exec
    assert enter.count("execve(") == 1
    assert "unlink(guard_path)" not in enter
    assert (
        "Keep the complete guard so snapshot-and-cleanup can prove this failure"
        in enter
    )


def test_exclusive_guard_writer_closes_and_removes_partial_file(
    tmp_path: Path,
) -> None:
    compiler = shutil.which("cc") or shutil.which("clang")
    if compiler is None:
        return

    source = _text("provider_network_helper.c")
    writer = _c_function(source, "static int write_guard_payload_exclusive")
    harness = tmp_path / "guard_writer_harness.c"
    executable = tmp_path / "guard_writer_harness"
    harness.write_text(
        textwrap.dedent(
            f"""
            #define _GNU_SOURCE
            #include <errno.h>
            #include <fcntl.h>
            #include <signal.h>
            #include <stddef.h>
            #include <stdio.h>
            #include <string.h>
            #include <sys/resource.h>
            #include <sys/stat.h>
            #include <sys/types.h>
            #include <unistd.h>

            {writer}

            static int require_mode(const char *path, mode_t expected)
            {{
                struct stat metadata;
                return stat(path, &metadata) == 0 &&
                       (metadata.st_mode & 0777) == expected ? 0 : -1;
            }}

            int main(int argc, char **argv)
            {{
                const char payload[] = "exact-guard-payload\\n";
                char path[4096];
                struct rlimit file_limit = {{64, 64}};
                struct rlimit size_limit = {{0, 0}};
                int index;

                if (argc != 2 || setrlimit(RLIMIT_NOFILE, &file_limit) != 0)
                    return 10;
                for (index = 0; index < 128; ++index) {{
                    if (snprintf(path, sizeof(path), "%s/success-%d", argv[1],
                                 index) >= (int)sizeof(path) ||
                        write_guard_payload_exclusive(path, payload,
                                                       sizeof(payload) - 1) != 0 ||
                        require_mode(path, 0600) != 0 || unlink(path) != 0)
                        return 11;
                }}
                if (snprintf(path, sizeof(path), "%s/collision", argv[1]) >=
                        (int)sizeof(path))
                    return 12;
                {{
                    int fd = open(path, O_WRONLY | O_CREAT | O_EXCL, 0600);
                    if (fd < 0 || write(fd, "sentinel", 8) != 8 || close(fd) != 0)
                        return 13;
                }}
                if (write_guard_payload_exclusive(path, payload,
                                                   sizeof(payload) - 1) == 0)
                    return 14;
                {{
                    char value[9] = {{0}};
                    int fd = open(path, O_RDONLY);
                    if (fd < 0 || read(fd, value, 8) != 8 || close(fd) != 0 ||
                        strcmp(value, "sentinel") != 0 || unlink(path) != 0)
                        return 15;
                }}
                if (signal(SIGXFSZ, SIG_IGN) == SIG_ERR ||
                    setrlimit(RLIMIT_FSIZE, &size_limit) != 0)
                    return 16;
                for (index = 0; index < 128; ++index) {{
                    if (snprintf(path, sizeof(path), "%s/failure-%d", argv[1],
                                 index) >= (int)sizeof(path) ||
                        write_guard_payload_exclusive(path, payload,
                                                       sizeof(payload) - 1) == 0 ||
                        access(path, F_OK) == 0 || errno != ENOENT)
                        return 17;
                }}
                if (snprintf(path, sizeof(path), "%s/fd-probe", argv[1]) >=
                        (int)sizeof(path))
                    return 18;
                {{
                    int fd = open(path, O_WRONLY | O_CREAT | O_EXCL, 0600);
                    if (fd < 0 || close(fd) != 0)
                        return 19;
                }}
                return 0;
            }}
            """
        ),
        encoding="utf-8",
    )
    compile_result = subprocess.run(
        [
            compiler,
            "-std=c17",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(harness),
            "-o",
            str(executable),
        ],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "TMPDIR": str(tmp_path)},
    )
    assert compile_result.returncode == 0, compile_result.stderr
    run_result = subprocess.run(
        [str(executable), str(tmp_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert run_result.returncode == 0, run_result.stderr

    injected_writer = writer.replace("close(descriptor)", "injected_close(descriptor)")
    assert injected_writer.count("injected_close(descriptor)") == 2
    close_harness = tmp_path / "guard_writer_close_failure.c"
    close_executable = tmp_path / "guard_writer_close_failure"
    close_harness.write_text(
        textwrap.dedent(
            f"""
            #define _GNU_SOURCE
            #include <errno.h>
            #include <fcntl.h>
            #include <stddef.h>
            #include <stdio.h>
            #include <sys/resource.h>
            #include <sys/types.h>
            #include <unistd.h>

            static int injected_close_calls = 0;

            static int injected_close(int descriptor)
            {{
                (void)close(descriptor);
                ++injected_close_calls;
                errno = EIO;
                return -1;
            }}

            {injected_writer}

            int main(int argc, char **argv)
            {{
                const char payload[] = "exact-guard-payload\\n";
                char path[4096];
                struct rlimit file_limit = {{64, 64}};
                int index;

                if (argc != 2 || setrlimit(RLIMIT_NOFILE, &file_limit) != 0)
                    return 20;
                for (index = 0; index < 128; ++index) {{
                    if (snprintf(path, sizeof(path), "%s/close-failure-%d", argv[1],
                                 index) >= (int)sizeof(path) ||
                        write_guard_payload_exclusive(path, payload,
                                                       sizeof(payload) - 1) == 0 ||
                        errno != EIO || access(path, F_OK) == 0 || errno != ENOENT)
                        return 21;
                }}
                if (injected_close_calls != 128)
                    return 22;
                if (snprintf(path, sizeof(path), "%s/close-fd-probe", argv[1]) >=
                        (int)sizeof(path))
                    return 23;
                {{
                    int fd = open(path, O_WRONLY | O_CREAT | O_EXCL, 0600);
                    if (fd < 0 || close(fd) != 0)
                        return 24;
                }}
                return 0;
            }}
            """
        ),
        encoding="utf-8",
    )
    close_compile = subprocess.run(
        [
            compiler,
            "-std=c17",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(close_harness),
            "-o",
            str(close_executable),
        ],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "TMPDIR": str(tmp_path)},
    )
    assert close_compile.returncode == 0, close_compile.stderr
    close_run = subprocess.run(
        [str(close_executable), str(tmp_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert close_run.returncode == 0, close_run.stderr


def test_helper_is_shell_free_scoped_and_secret_safe() -> None:
    source = _text("provider_network_helper.c")

    assert not re.search(r"\b(?:system|popen)\s*\(", source)
    assert "execve(argv[11], &argv[11], environ)" in source
    assert '#define FORTGYM_CGROUP_ROOT "/sys/fs/cgroup/fortgym-provider-net"' in source
    assert '#define FORTGYM_BPFFS_ROOT "/sys/fs/bpf/fortgym-provider-net"' in source
    assert "is_direct_child(cgroup_path, FORTGYM_CGROUP_ROOT)" in source
    assert "is_direct_child(pin_root, FORTGYM_BPFFS_ROOT)" in source
    assert (
        "resource_component_matches_identity(cgroup_path, pin_root, identity)" in source
    )
    assert "member_count != 0" in source
    assert "--expected-helper-sha256" in source
    assert "--expected-bpf-object-sha256" in source
    assert "require_secure_artifact(helper_path, true)" in source
    assert "require_secure_artifact(object_path, false)" in source
    assert "(metadata.st_mode & 0777) != 0700" in source
    assert "FORT_GYM_RUN_NONCE" in source
    assert "print_json_string(nonce)" not in source
    assert 'getenv("OPENAI_API_KEY")' not in source
    assert 'getenv("OPENROUTER_API_KEY")' not in source


def test_reproducible_build_recipe_is_offline_and_byte_compares() -> None:
    makefile = _text("Makefile")
    readme = _text("README.md")
    normalized_readme = " ".join(readme.split())

    assert "-target bpf" in makefile
    assert "-D__TARGET_ARCH_x86" in makefile
    assert "-ffile-prefix-map=" in makefile
    assert "SOURCE_DATE_EPOCH" in makefile
    assert "cmp build-repro-a/provider_network.bpf.o" in makefile
    assert "cmp build-repro-a/fortgym-provider-network-helper" in makefile
    assert "curl" not in makefile and "wget" not in makefile
    assert "has not been built, installed, loaded, or exercised" in normalized_readme
    assert "Passing the Python fake/static tests is not the real" in normalized_readme
    assert "do not manually substitute JSON" in normalized_readme


def test_clean_target_is_confined_to_exact_build_basenames() -> None:
    for unsafe in ("/", ".", "..", "../escape", "build/../../..", "build other"):
        completed = subprocess.run(
            ["make", "-n", f"BUILD_DIR={unsafe}", "clean"],
            cwd=SOURCE_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert completed.returncode != 0
        assert "rm -rf" not in completed.stdout

    for safe in ("build", "build-repro-a", "build-repro-b"):
        completed = subprocess.run(
            ["make", "-n", f"BUILD_DIR={safe}", "clean"],
            cwd=SOURCE_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0
        assert completed.stdout.strip() == f"rm -rf -- {safe}"

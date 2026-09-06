"""Temporary launcher contract; never starts a real server."""

import io
import tarfile

import pytest

from scripts import campaign_llama_server as launcher
from fort_gym.bench.run.campaign_config import load_segment_config
from tests.test_campaign_llama import CONFIG, MODEL


def test_launcher_arguments_disable_external_surfaces_and_context_shift(tmp_path):
    config = load_segment_config(CONFIG, MODEL)
    weights = tmp_path / config["local_inference"]["model_files"][MODEL]
    args = launcher.launch_arguments(config, MODEL, tmp_path / "llama-server", weights, 11440)
    assert args[args.index("--host") + 1] == "127.0.0.1"
    assert args[args.index("--alias") + 1] == MODEL
    assert args[args.index("--ctx-size") + 1] == "32768"
    assert args[args.index("--parallel") + 1] == "1"
    assert args[args.index("--cors-origins") + 1] == "http://127.0.0.1:11440"
    assert {
        "--offline",
        "--no-context-shift",
        "--no-webui",
        "--no-agent",
        "--no-ui-mcp-proxy",
        "--no-models-autoload",
        "--no-slots",
        "--no-cors-credentials",
    } <= set(args)
    assert "--props" not in args and "--media-path" not in args and "--tools" not in args


@pytest.mark.parametrize("port", [True, 0, 5000, 11434, 65536])
def test_launcher_rejects_nondedicated_ports(tmp_path, port):
    config = load_segment_config(CONFIG, MODEL)
    weights = tmp_path / config["local_inference"]["model_files"][MODEL]
    with pytest.raises(ValueError, match="dedicated"):
        launcher.launch_arguments(config, MODEL, tmp_path / "binary", weights, port)


def archive(tmp_path, monkeypatch, *, name="llama-b10516/llama-server", link=None):
    path = tmp_path / launcher.ARCHIVE_NAME
    with tarfile.open(path, "w:gz") as tar:
        item = tarfile.TarInfo(name)
        if link:
            item.type, item.linkname = tarfile.SYMTYPE, link
            tar.addfile(item)
        else:
            item.size = 5
            tar.addfile(item, io.BytesIO(b"valid"))
    monkeypatch.setattr(launcher, "ARCHIVE_SHA256", launcher.file_digest(path))
    return path


def test_runtime_verifies_every_installed_archive_member(tmp_path, monkeypatch):
    binary = tmp_path / "llama-server"
    binary.write_bytes(b"valid")
    binary.chmod(0o700)
    archive(tmp_path, monkeypatch)
    assert launcher.verify_runtime(tmp_path) == binary
    binary.write_bytes(b"other")
    with pytest.raises(ValueError, match="file digest"):
        launcher.verify_runtime(tmp_path)


def test_runtime_rejects_archive_digest_mismatch(tmp_path):
    (tmp_path / launcher.ARCHIVE_NAME).write_bytes(b"invalid")
    with pytest.raises(ValueError, match="archive digest"):
        launcher.verify_runtime(tmp_path)


@pytest.mark.parametrize("name", ["elsewhere/llama-server", "llama-b10516/../escape"])
def test_runtime_rejects_archive_path_escape(tmp_path, monkeypatch, name):
    archive(tmp_path, monkeypatch, name=name)
    with pytest.raises(ValueError):
        launcher.verify_runtime(tmp_path)


def test_runtime_rejects_symlink_escape(tmp_path, monkeypatch):
    outside = tmp_path.parent / "outside-llama-fixture"
    outside.write_bytes(b"fixture")
    (tmp_path / "llama-server").symlink_to(outside)
    archive(tmp_path, monkeypatch, link=str(outside))
    with pytest.raises(ValueError):
        launcher.verify_runtime(tmp_path)

from __future__ import annotations

from pathlib import Path

from fort_gym.bench import dfhack_backend
from fort_gym.bench import dfhack_exec


def test_run_lua_file_parses_last_json_line(monkeypatch) -> None:
    monkeypatch.setattr(
        dfhack_exec,
        "run_dfhack",
        lambda *args, **kwargs: "notice from dfhack\n\x1b[0m{\"ok\": true, \"value\": 3}\x1b[0m",
    )

    assert dfhack_exec.run_lua_file("/tmp/hook.lua") == {"ok": True, "value": 3}


def test_hook_path_prefers_repo_hook_over_installed_copy(tmp_path, monkeypatch) -> None:
    repo_hook = tmp_path / "repo" / "hook"
    installed_hook = tmp_path / "installed" / "hook"
    repo_hook.mkdir(parents=True)
    installed_hook.mkdir(parents=True)
    (repo_hook / "work_metrics.lua").write_text("-- repo", encoding="utf-8")
    (installed_hook / "work_metrics.lua").write_text("-- stale installed", encoding="utf-8")
    monkeypatch.setattr(dfhack_backend, "REPO_HOOK_ROOT", repo_hook)
    monkeypatch.setattr(dfhack_backend, "HOOK_ROOT", installed_hook)

    assert Path(dfhack_backend._hook_path("work_metrics.lua")) == repo_hook / "work_metrics.lua"


def test_prepare_keystroke_workshop_target_moves_cursor_before_confirm() -> None:
    hook_path = (
        Path(__file__).resolve().parents[1]
        / "hook"
        / "prepare_keystroke_target.lua"
    )
    hook_text = hook_path.read_text(encoding="utf-8")

    assert "local function append_cursor_moves" in hook_text
    assert "placement_cursor_before_moves" in hook_text
    assert "blocked_workshop_targets" in hook_text
    assert "blocked_workshop_targets[workshop_target_key(x1, y1, z)]" in hook_text
    assert (
        "append_cursor_moves(recommended_keys, placement_cursor_x, placement_cursor_y, x1, y1)"
        in hook_text
    )
    assert "'HOTKEY_BUILDING_WORKSHOP_CARPENTER',\n  }\n  append_cursor_moves" in hook_text


def test_prepare_keystroke_target_passes_blocked_workshop_targets(monkeypatch) -> None:
    captured = {}

    def fake_run_lua_file(path, *args, **kwargs):
        captured["path"] = path
        captured["args"] = args
        captured["kwargs"] = kwargs
        return {"ok": True}

    monkeypatch.setattr(dfhack_backend, "run_lua_file", fake_run_lua_file)

    assert dfhack_backend.prepare_keystroke_target(
        "workshop",
        blocked_workshop_targets=[(97, 93, 177), (88, 98, 177)],
    ) == {"ok": True}

    assert captured["args"] == ("workshop", "97,93,177;88,98,177")
    assert captured["kwargs"]["timeout"] == 10.0


def test_prepare_keystroke_tree_material_target_uses_broad_selection() -> None:
    hook_path = (
        Path(__file__).resolve().parents[1]
        / "hook"
        / "prepare_keystroke_target.lua"
    )
    hook_text = hook_path.read_text(encoding="utf-8")

    assert "local TREE_SELECT_WIDTH = 7" in hook_text
    assert "local TREE_SELECT_HEIGHT = 3" in hook_text
    assert "count_designatable_rect" in hook_text
    assert "selection_payload(" in hook_text
    assert "chop a broad visible tree area" in hook_text

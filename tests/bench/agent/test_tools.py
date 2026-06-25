from __future__ import annotations

from fort_gym.bench.agent.tools import DFWikiTool, ToolManager


def test_df_wiki_tool_answers_designations() -> None:
    tool = DFWikiTool()
    response = tool.query("How do I designate a dig area?")
    assert "Designations" in response or "designations" in response


def test_tool_manager_exposes_df_wiki_spec() -> None:
    manager = ToolManager(["df_wiki"])
    specs = manager.tool_specs()
    assert any(spec.get("name") == "df_wiki" for spec in specs)


def test_tool_manager_exposes_perception_review_specs() -> None:
    manager = ToolManager(["record_screen_read", "review_last_action"])
    specs = manager.tool_specs()

    assert {spec.get("name") for spec in specs} == {
        "record_screen_read",
        "review_last_action",
    }
    assert "mode=main_map" in manager.handle(
        "record_screen_read",
        {
            "mode": "main_map",
            "evidence": ["main map visible"],
            "cursor_or_selection": "cursor",
            "confidence": "medium",
        },
    )
    assert "should_retry_same_path=False" in manager.handle(
        "review_last_action",
        {
            "worked": False,
            "evidence": ["changed=none"],
            "mismatch_reason": "no state changed",
            "should_retry_same_path": False,
        },
    )

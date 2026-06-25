from __future__ import annotations

from fort_gym.bench.agent.tools import DFWikiTool, ToolManager


def test_df_wiki_tool_answers_designations() -> None:
    tool = DFWikiTool()
    response = tool.query("How do I designate a dig area?")
    assert "Designations" in response or "designations" in response


def test_df_wiki_tool_prioritizes_manager_work_orders() -> None:
    tool = DFWikiTool()
    response = tool.query(
        "How do I create a manager work order for wooden furniture like a bed or table?"
    )
    first_title = response.splitlines()[0]
    assert first_title == "Title: Manager orders and standing orders"
    assert "D_JOBLIST" in response
    assert "UNITJOB_MANAGER" in response
    assert "MANAGER_NEW_ORDER" in response
    assert "bed" in response


def test_df_wiki_tool_answers_direct_workshop_tasks() -> None:
    tool = DFWikiTool()
    response = tool.query("How do I add a carpenter workshop task directly?")
    first_title = response.splitlines()[0]
    assert first_title == "Title: Buildings and workshops"
    assert "D_BUILDJOB" in response
    assert "BUILDJOB_ADD" in response
    assert "SELECT picks" in response
    assert "highlighted row" in response
    assert "STANDARDSCROLL_DOWN" in response
    assert "STANDARDSCROLL_UP" in response
    assert "CURSOR_DOWN/CURSOR_UP can move the map cursor" in response


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

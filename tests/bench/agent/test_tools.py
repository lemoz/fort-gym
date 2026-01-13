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

from __future__ import annotations

from fort_gym.bench.eval.analyzer import TraceAnalyzer


def test_trace_analyzer_uses_current_configurable_gemini_model(monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_ANALYZER_MODEL", raising=False)
    analyzer = TraceAnalyzer(api_key="test-key")
    assert analyzer.model == "gemini-2.5-flash"

    monkeypatch.setenv("GEMINI_ANALYZER_MODEL", "gemini-custom")
    analyzer = TraceAnalyzer(api_key="test-key")
    assert analyzer.model == "gemini-custom"

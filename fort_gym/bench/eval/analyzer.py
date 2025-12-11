"""
LLM-based trace analyzer for identifying agent failure patterns.

Uses Gemini 3.0 Pro Preview (1M token context) to analyze trace.jsonl files.
For traces > 1M tokens, chunks at 500k with carry-forward of insights.

No hardcoded heuristics - the LLM identifies patterns and generates hypotheses.
"""
from __future__ import annotations

import json
import os
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Rough estimate: 1 token ≈ 4 characters for JSON
CHARS_PER_TOKEN = 4
MAX_TOKENS = 1_000_000
CHUNK_TOKENS = 500_000
MAX_CHUNK_CHARS = CHUNK_TOKENS * CHARS_PER_TOKEN


ANALYSIS_PROMPT = """You are analyzing a Dwarf Fortress agent run trace. The trace contains step-by-step data of an AI agent attempting to play Dwarf Fortress.

Each step in the trace includes:
- `step`: Step number
- `observation`: Game state the agent saw (population, food, drink, etc.)
- `action`: Action the agent took (type, params, intent)
- `validation`: Whether the action was valid
- `execute`: Whether the action was accepted and resulting state
- `state_after_apply`: State after action applied (before time advances)
- `state_after_advance`: State after game time advances
- `metrics`: Key metrics (time, population, food, drink, wealth)
- `score`: Current score and milestones

Your task is to analyze this trace and identify:

1. **Anomalies**: Any unusual patterns, failures, or concerning behaviors
   - Actions that don't produce expected effects
   - Game state not changing when it should
   - Time not advancing (game may be paused)
   - Repeated identical actions
   - Validation or execution failures
   - Resource depletion trends
   - Population changes

2. **Root Cause Hypotheses**: For each anomaly, suggest what might be causing it
   - Is the agent missing information it needs?
   - Is the game in a state the agent doesn't understand?
   - Is there a bug in how actions are executed?

3. **Suggested Fixes**: What changes might help the agent perform better?
   - Information to add to observations
   - Behaviors the agent should learn
   - System changes that might help

Respond in JSON format:
```json
{
  "summary": "Brief overall assessment of the run",
  "anomalies": [
    {
      "type": "descriptive_type_name",
      "severity": "info|warning|critical",
      "step_range": [start_step, end_step],
      "description": "What was observed",
      "evidence": "Specific data from trace supporting this",
      "hypothesis": "Why this might be happening",
      "suggested_fix": "What might help"
    }
  ],
  "patterns": [
    {
      "name": "pattern_name",
      "description": "Description of behavioral pattern observed",
      "frequency": "how often it occurs",
      "impact": "effect on agent performance"
    }
  ],
  "recommendations": [
    "High-level recommendation for improving agent"
  ]
}
```

Be thorough but concise. Focus on actionable insights."""


CONTINUATION_PROMPT = """You are continuing analysis of a Dwarf Fortress agent run trace. This is chunk {chunk_num} of {total_chunks}.

Previous analysis found these key insights:
{prior_insights}

Continue analyzing, looking for:
1. Patterns that continue or change from previous chunks
2. New anomalies
3. How issues identified earlier evolve

Trace data for this chunk (steps {start_step} to {end_step}):
"""


MERGE_PROMPT = """You have analyzed a Dwarf Fortress agent run trace in {num_chunks} chunks. Here are the results from each chunk:

{chunk_results}

Please merge these into a single cohesive analysis:
1. Combine similar anomalies
2. Identify patterns that span multiple chunks
3. Prioritize the most important findings
4. Generate a unified summary

Respond in the same JSON format as individual chunk analyses."""


@dataclass
class Anomaly:
    """An anomaly detected by the LLM."""
    type: str
    severity: str
    step_range: tuple[int, int]
    description: str
    evidence: str = ""
    hypothesis: str = ""
    suggested_fix: str = ""


@dataclass
class Pattern:
    """A behavioral pattern observed by the LLM."""
    name: str
    description: str
    frequency: str = ""
    impact: str = ""


@dataclass
class AnalysisReport:
    """Complete analysis report from LLM."""
    run_id: str
    total_steps: int
    summary: str = ""
    anomalies: list[Anomaly] = field(default_factory=list)
    patterns: list[Pattern] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    raw_response: str = ""

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "total_steps": self.total_steps,
            "summary": self.summary,
            "anomalies": [
                {
                    "type": a.type,
                    "severity": a.severity,
                    "step_range": list(a.step_range),
                    "description": a.description,
                    "evidence": a.evidence,
                    "hypothesis": a.hypothesis,
                    "suggested_fix": a.suggested_fix,
                }
                for a in self.anomalies
            ],
            "patterns": [
                {
                    "name": p.name,
                    "description": p.description,
                    "frequency": p.frequency,
                    "impact": p.impact,
                }
                for p in self.patterns
            ],
            "recommendations": self.recommendations,
        }

    def to_text(self) -> str:
        """Generate human-readable report."""
        lines = [
            f"# Trace Analysis Report",
            f"Run ID: {self.run_id}",
            f"Total Steps: {self.total_steps}",
            "",
            "## Summary",
            self.summary or "No summary generated.",
            "",
        ]

        if self.anomalies:
            lines.append(f"## Anomalies ({len(self.anomalies)})")
            lines.append("")

            # Group by severity
            for severity in ["critical", "warning", "info"]:
                group = [a for a in self.anomalies if a.severity == severity]
                if group:
                    lines.append(f"### {severity.upper()}")
                    for a in group:
                        lines.append(f"**[{a.type}]** Steps {a.step_range[0]}-{a.step_range[1]}")
                        lines.append(f"  {a.description}")
                        if a.hypothesis:
                            lines.append(f"  *Hypothesis*: {a.hypothesis}")
                        if a.suggested_fix:
                            lines.append(f"  *Suggested Fix*: {a.suggested_fix}")
                        lines.append("")

        if self.patterns:
            lines.append(f"## Patterns ({len(self.patterns)})")
            lines.append("")
            for p in self.patterns:
                lines.append(f"**{p.name}**: {p.description}")
                if p.frequency:
                    lines.append(f"  Frequency: {p.frequency}")
                if p.impact:
                    lines.append(f"  Impact: {p.impact}")
                lines.append("")

        if self.recommendations:
            lines.append("## Recommendations")
            lines.append("")
            for i, rec in enumerate(self.recommendations, 1):
                lines.append(f"{i}. {rec}")

        return "\n".join(lines)


class TraceAnalyzer:
    """LLM-based trace analyzer using Gemini API via raw HTTP."""

    # Gemini API endpoint
    API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

    def __init__(self, api_key: str | None = None):
        """
        Initialize the analyzer.

        Args:
            api_key: Google API key. If not provided, uses GOOGLE_API_KEY env var.
        """
        self.api_key = api_key or os.environ.get("GOOGLE_API_KEY")
        if not self.api_key:
            raise ValueError("GOOGLE_API_KEY environment variable not set")

    def _call_gemini_api(self, prompt: str) -> str:
        """Call Gemini API via raw HTTP request."""
        url = f"{self.API_URL}?key={self.api_key}"

        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt}
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 8192,
            }
        }

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
            },
            method="POST"
        )

        try:
            with urllib.request.urlopen(req, timeout=120) as response:
                result = json.loads(response.read().decode("utf-8"))
                # Extract text from response
                candidates = result.get("candidates", [])
                if candidates:
                    content = candidates[0].get("content", {})
                    parts = content.get("parts", [])
                    if parts:
                        return parts[0].get("text", "")
                return ""
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8") if e.fp else ""
            raise RuntimeError(f"Gemini API error {e.code}: {error_body}")
        except urllib.error.URLError as e:
            raise RuntimeError(f"Gemini API connection error: {e.reason}")

    def analyze(self, trace_path: Path) -> AnalysisReport:
        """Analyze a trace file and return a report."""
        trace_content = self._load_trace_as_text(trace_path)
        steps = self._load_trace(trace_path)

        if not steps:
            return AnalysisReport(run_id="unknown", total_steps=0, summary="Empty trace")

        run_id = steps[0].get("run_id", "unknown")
        total_steps = len(steps)

        # Check if we need to chunk
        if len(trace_content) <= MAX_CHUNK_CHARS:
            # Single chunk analysis
            result = self._analyze_single(trace_content, run_id, total_steps)
        else:
            # Multi-chunk analysis
            result = self._analyze_chunked(trace_path, steps, run_id, total_steps)

        return result

    def _load_trace(self, trace_path: Path) -> list[dict]:
        """Load trace.jsonl file as list of dicts."""
        steps = []
        try:
            with open(trace_path) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        steps.append(json.loads(line))
        except Exception as e:
            print(f"Error loading trace: {e}")
        return steps

    def _load_trace_as_text(self, trace_path: Path) -> str:
        """Load trace file as raw text."""
        return trace_path.read_text()

    def _analyze_single(self, trace_content: str, run_id: str, total_steps: int) -> AnalysisReport:
        """Analyze trace in a single LLM call."""
        prompt = ANALYSIS_PROMPT + "\n\nTrace data:\n" + trace_content

        raw_response = self._call_gemini_api(prompt)

        return self._parse_response(raw_response, run_id, total_steps)

    def _analyze_chunked(
        self, trace_path: Path, steps: list[dict], run_id: str, total_steps: int
    ) -> AnalysisReport:
        """Analyze trace in chunks with carry-forward."""
        chunks = self._create_chunks(steps)
        chunk_results = []
        prior_insights = ""

        for i, chunk_steps in enumerate(chunks):
            chunk_text = "\n".join(json.dumps(s) for s in chunk_steps)
            start_step = chunk_steps[0].get("step", 0)
            end_step = chunk_steps[-1].get("step", 0)

            if i == 0:
                prompt = ANALYSIS_PROMPT + f"\n\nTrace data (steps {start_step}-{end_step}):\n" + chunk_text
            else:
                prompt = CONTINUATION_PROMPT.format(
                    chunk_num=i + 1,
                    total_chunks=len(chunks),
                    prior_insights=prior_insights,
                    start_step=start_step,
                    end_step=end_step,
                ) + chunk_text

            response_text = self._call_gemini_api(prompt)
            chunk_results.append(response_text)

            # Extract key insights for carry-forward
            prior_insights = self._extract_key_insights(response_text)

        # Merge all chunk results
        return self._merge_chunk_results(chunk_results, run_id, total_steps)

    def _create_chunks(self, steps: list[dict]) -> list[list[dict]]:
        """Split steps into chunks that fit within token limits."""
        chunks = []
        current_chunk = []
        current_size = 0

        for step in steps:
            step_text = json.dumps(step)
            step_size = len(step_text)

            if current_size + step_size > MAX_CHUNK_CHARS and current_chunk:
                chunks.append(current_chunk)
                current_chunk = []
                current_size = 0

            current_chunk.append(step)
            current_size += step_size

        if current_chunk:
            chunks.append(current_chunk)

        return chunks

    def _extract_key_insights(self, response_text: str) -> str:
        """Extract key insights from a chunk response for carry-forward."""
        try:
            # Try to parse JSON response
            json_start = response_text.find("{")
            json_end = response_text.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                data = json.loads(response_text[json_start:json_end])
                insights = []
                if data.get("summary"):
                    insights.append(f"Summary: {data['summary']}")
                for a in data.get("anomalies", [])[:5]:  # Top 5 anomalies
                    insights.append(f"- {a.get('type', 'anomaly')}: {a.get('description', '')}")
                return "\n".join(insights)
        except:
            pass

        # Fallback: return truncated response
        return response_text[:2000]

    def _merge_chunk_results(
        self, chunk_results: list[str], run_id: str, total_steps: int
    ) -> AnalysisReport:
        """Merge multiple chunk results into a single report."""
        chunk_summaries = "\n\n---\n\n".join(
            f"Chunk {i+1}:\n{result}" for i, result in enumerate(chunk_results)
        )

        prompt = MERGE_PROMPT.format(
            num_chunks=len(chunk_results),
            chunk_results=chunk_summaries,
        )

        response_text = self._call_gemini_api(prompt)
        return self._parse_response(response_text, run_id, total_steps)

    def _parse_response(self, response_text: str, run_id: str, total_steps: int) -> AnalysisReport:
        """Parse LLM response into AnalysisReport."""
        report = AnalysisReport(
            run_id=run_id,
            total_steps=total_steps,
            raw_response=response_text,
        )

        try:
            # Find JSON in response
            json_start = response_text.find("{")
            json_end = response_text.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                data = json.loads(response_text[json_start:json_end])

                report.summary = data.get("summary", "")

                for a in data.get("anomalies", []):
                    step_range = a.get("step_range", [0, 0])
                    if isinstance(step_range, list) and len(step_range) >= 2:
                        step_range = (step_range[0], step_range[1])
                    else:
                        step_range = (0, 0)

                    report.anomalies.append(Anomaly(
                        type=a.get("type", "unknown"),
                        severity=a.get("severity", "info"),
                        step_range=step_range,
                        description=a.get("description", ""),
                        evidence=a.get("evidence", ""),
                        hypothesis=a.get("hypothesis", ""),
                        suggested_fix=a.get("suggested_fix", ""),
                    ))

                for p in data.get("patterns", []):
                    report.patterns.append(Pattern(
                        name=p.get("name", ""),
                        description=p.get("description", ""),
                        frequency=p.get("frequency", ""),
                        impact=p.get("impact", ""),
                    ))

                report.recommendations = data.get("recommendations", [])

        except json.JSONDecodeError as e:
            report.summary = f"Failed to parse LLM response: {e}"

        return report


def analyze_run(run_id: str, artifacts_dir: Path | None = None) -> AnalysisReport:
    """Convenience function to analyze a run by ID."""
    if artifacts_dir is None:
        artifacts_dir = Path(__file__).parent.parent.parent / "artifacts"

    trace_path = artifacts_dir / run_id / "trace.jsonl"
    if not trace_path.exists():
        raise FileNotFoundError(f"Trace not found: {trace_path}")

    analyzer = TraceAnalyzer()
    return analyzer.analyze(trace_path)


def save_analysis(report: AnalysisReport, output_dir: Path) -> tuple[Path, Path]:
    """Save analysis report as JSON and text files."""
    output_dir.mkdir(parents=True, exist_ok=True)

    json_path = output_dir / "analysis.json"
    text_path = output_dir / "analysis.txt"

    with open(json_path, "w") as f:
        json.dump(report.to_dict(), f, indent=2)

    with open(text_path, "w") as f:
        f.write(report.to_text())

    return json_path, text_path

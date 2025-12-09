# Agent Memory, Tools & Experimentation System

## Overview

This document describes the planned system for adding memory, tools, and experimentation capabilities to fort-gym agents.

## Problem Statement

### Current Architecture Issues

**Agent Memory: NONE**
- Each step is **completely stateless** - fresh LLM call
- Agent only sees current observation, not history
- Keystroke mode has minimal memory: last 5 actions shown in observation text
- No conversation history between steps
- No goal/plan tracking across steps

### Key Files
- `fort_gym/bench/agent/llm_anthropic.py` - Agent implementation
- `fort_gym/bench/run/runner.py` - Run loop (calls agent.decide() each step)
- `fort_gym/bench/env/encoder.py` - Builds observation text

---

## Design Decisions

### Memory Strategy: Hybrid
- **Last N steps**: Keep full conversation history for recent steps (configurable window, default 10)
- **Summary of older steps**: Compress older history into a running summary
- Best of both worlds: detail for recent context, compression for long runs

### Tools
- Web search for DF information lookup
- DF Wiki tool for embedded documentation queries

### Experimentation
- Full framework for testing different configurations
- YAML-based experiment configs
- A/B testing between agent variants

---

## Architecture

```
Experiment Config (YAML/JSON)
       │
       ▼
┌─────────────────┐
│  ExperimentRun  │ ── creates ──▶ AgentVariant (configured agent)
└─────────────────┘
       │
       ▼
┌─────────────────┐
│  Runner Loop    │ ── uses ──▶ MemoryManager, ToolManager
└─────────────────┘
       │
       ▼
   Trace + Logs ──▶ Analysis/Comparison
```

---

## New Components

### 1. Experiment Config (`fort_gym/bench/experiment/config.py`)

```python
@dataclass
class ExperimentConfig:
    name: str
    agent_type: str  # "anthropic-keystroke", etc.

    # Memory settings
    memory_strategy: str  # "none", "conversation", "summary", "hybrid"
    memory_window: int = 10  # Steps to keep verbatim

    # Prompt settings
    system_prompt: str | None  # Override default prompt
    prompt_file: str | None    # Load from file

    # Tools
    tools_enabled: list[str]  # ["web_search", "df_wiki"]

    # Run settings
    max_steps: int = 50
    ticks_per_step: int = 200
```

### 2. Memory Manager (`fort_gym/bench/agent/memory.py`)

```python
class MemoryManager:
    def __init__(self, strategy: str, window: int = 10):
        self.strategy = strategy
        self.window = window
        self.history = []  # Full message history
        self.summary = ""  # Compressed older history

    def add_step(self, observation: str, action: dict, result: str):
        """Record a step"""

    def get_context(self) -> list[dict]:
        """Get messages for LLM call"""
        # Returns: recent N steps + summary prefix

    def summarize_old(self):
        """Compress old history into summary"""
```

### 3. Enhanced Agent (`fort_gym/bench/agent/experimental.py`)

```python
class ExperimentalAgent(Agent):
    def __init__(self, config: ExperimentConfig):
        self.config = config
        self.memory = MemoryManager(config.memory_strategy, config.memory_window)
        self.tools = ToolManager(config.tools_enabled)

    def decide(self, obs_text: str, obs_json: dict) -> dict:
        # Build messages with memory context
        messages = self.memory.get_context()
        messages.append({"role": "user", "content": obs_text})

        # Call LLM with tools if enabled
        response = self._call_llm(messages, tools=self.tools.get_specs())

        # Handle tool calls (web search, etc.)
        while response.has_tool_calls:
            tool_results = self.tools.execute(response.tool_calls)
            messages.extend(tool_results)
            response = self._call_llm(messages, tools=self.tools.get_specs())

        # Record for memory
        self.memory.add_step(obs_text, response.action, ...)

        return response.action
```

### 4. Tool Manager (`fort_gym/bench/agent/tools.py`)

```python
class ToolManager:
    AVAILABLE_TOOLS = {
        "web_search": WebSearchTool(),
        "df_wiki": DFWikiTool(),
    }

    def __init__(self, enabled: list[str]):
        self.enabled = {k: v for k, v in self.AVAILABLE_TOOLS.items() if k in enabled}

    def get_specs(self) -> list[dict]:
        """Get tool specifications for LLM"""

    def execute(self, tool_calls: list) -> list[dict]:
        """Execute tool calls, return results"""
```

### 5. Experiment Runner (`fort_gym/bench/experiment/runner.py`)

```python
def run_experiment(config_path: str) -> str:
    """Run an experiment from config file"""
    config = load_config(config_path)
    agent = ExperimentalAgent(config)

    run_id = run_once(
        agent,
        backend="dfhack",
        model=config.name,
        max_steps=config.max_steps,
        ...
    )

    # Log experiment metadata
    save_experiment_meta(run_id, config)
    return run_id
```

---

## File Structure

```
fort_gym/bench/
├── agent/
│   ├── experimental.py    # New configurable agent
│   ├── memory.py          # Memory management
│   └── tools.py           # Tool implementations
├── experiment/
│   ├── config.py          # Config dataclasses
│   ├── runner.py          # Experiment execution
│   └── analysis.py        # Comparison utilities
└── experiments/           # Config files
    ├── baseline.yaml
    ├── with_memory.yaml
    └── with_tools.yaml
```

---

## Example Configs

### baseline.yaml (current behavior)
```yaml
name: baseline-no-memory
agent_type: anthropic-keystroke
memory_strategy: none
tools_enabled: []
max_steps: 50
```

### with_memory.yaml
```yaml
name: hybrid-memory-10
agent_type: anthropic-keystroke
memory_strategy: hybrid
memory_window: 10
tools_enabled: []
max_steps: 50
```

### with_tools.yaml
```yaml
name: memory-plus-wiki
agent_type: anthropic-keystroke
memory_strategy: hybrid
memory_window: 10
tools_enabled: [df_wiki]
max_steps: 50
```

---

## API Additions

### POST /experiments
```json
{
  "config": "with_memory.yaml"
}
```

### GET /experiments
List all experiment runs with configs and scores

### GET /experiments/compare?ids=run1,run2,run3
Compare scores/metrics across experiment runs

---

## Implementation Order

1. **Memory Manager** - Core memory abstraction
2. **Experimental Agent** - Agent that uses memory
3. **Config System** - Load experiments from YAML
4. **Tool Manager** - Web search / wiki tools (optional start)
5. **API Endpoints** - Launch/compare experiments
6. **Analysis Tools** - Compare results

---

## Quick Start Option

If we want to test memory quickly before building the full system:
1. Just add `message_history: list` to `AnthropicKeystrokeAgent`
2. Accumulate messages in `decide()`
3. Run a test to see if it helps

Then iterate toward the full framework.

---

## Prerequisites / Blockers

*List any changes that need to happen before implementing this plan:*

- [ ] TBD - user to specify

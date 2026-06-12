# Claude Sonnet mock trace

This directory contains a one-step mock backend run produced by `AnthropicActionAgent`
with `claude-sonnet-4-6`.

## Reproduce

```bash
python -m pip install -e '.[agent]'
export ANTHROPIC_API_KEY=...

env -u GOOGLE_API_KEY \
  ANTHROPIC_MODEL=claude-sonnet-4-6 \
  ARTIFACTS_DIR=/tmp/fort-gym-claude-sample \
  LLM_RATE_LIMIT_TPS=0 \
  python - <<'PY'
from pathlib import Path

from fort_gym.bench.agent.llm_anthropic import AnthropicActionAgent
from fort_gym.bench.config import get_settings
from fort_gym.bench.run.runner import run_once

get_settings.cache_clear()
run_id = run_once(
    AnthropicActionAgent(),
    backend="mock",
    model="anthropic",
    max_steps=1,
    ticks_per_step=10,
    run_id="claude-sonnet-4-6-mock-1step",
)
root = Path("/tmp/fort-gym-claude-sample") / run_id
print(root / "trace.jsonl")
print(root / "summary.json")
PY
```

The committed trace was generated on 2026-06-12. Its recorded Anthropic usage is:

```text
input_tokens: 1050
output_tokens: 331
cache_creation_input_tokens: 0
cache_read_input_tokens: 0
```

Using the documented Sonnet 4.6 price of $3/input MTok and $15/output MTok, the
estimated request cost is:

```text
(1050 * 3 + 331 * 15) / 1_000_000 = $0.008115
```

Re-check Anthropic pricing before larger runs.

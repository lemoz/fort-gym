# fort-gym 3-minute demo

This script is for a live interview demo from a prepared local checkout. It uses
the mock backend, so it does not require DFHack or any LLM API key.

## Before the call

Run these once before the interview starts:

```bash
git clone https://github.com/lemoz/fort-gym.git
cd fort-gym
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pytest -q
```

Expected test result:

```text
... passed, ... skipped
```

Keep two terminals open in the repo root and have a browser ready.

If the live DFHack VM is part of the interview, rehearse it before the call:

```bash
make vm-live-demo VM_LIVE_DEMO_REF=main
```

Expected output shape:

```text
RUN_DIR=/home/cdossman/fort-gym-live-demo.<suffix>
{
  "ok": true,
  "live_smoke": {
    "ok": true,
    "trace": ".../trace.jsonl",
    "summary": ".../summary.json"
  },
  "packet": ".../live_demo_packet.md",
  "public_endpoint_checks": [...]
}
```

Open the generated packet if you want the live DFHack artifact paths and endpoint
checks in one place before the demo.

To rehearse a real model run that appears in the public UI and compares against a
deterministic baseline:

```bash
make vm-deploy SHA=origin/main
make vm-live-agent VM_LIVE_AGENT_REF=main LIVE_AGENT_MODEL=openrouter-keystroke-perception-review LIVE_AGENT_MAX_STEPS=4
```

Expected output shape:

```text
RUN_DIR=/home/cdossman/fort-gym-live-agent.<suffix>
{
  "ok": true,
  "comparison": {
    "baseline_score": <number>,
    "model_score": <number>,
    "score_delta": <number>
  },
  "runs": {
    "baseline": {"public_run_url": "...", "public_replay_url": "..."},
    "model": {"public_run_url": "...", "public_replay_url": "..."}
  },
  "packet": ".../live_agent_report.md"
}
```

To compare multiple live model/control variants across repeated trials, run the
suite command:

```bash
make vm-deploy SHA=origin/main
make vm-live-agent-suite VM_LIVE_AGENT_REF=main \
  LIVE_AGENT_MODELS=openrouter-keystroke-perception-review,openrouter-glm-5.2 \
  LIVE_AGENT_TRIALS=2 LIVE_AGENT_MAX_STEPS=6
```

The suite writes a Markdown packet and `scorecard.json` with median scores,
work scores, completion scores, utility scores, production scores, complexity
scores, target-room designation/completion/utility/production/complexity
progress, public run/replay URLs, and trace diagnostics such as invalid actions,
status menu exploration, tick-only scoring, no-mining-progress blockers,
completed-room-without-utility blockers, completed-room-without-production
blockers, production-without-complexity blockers, dig attempts, utility attempts,
production attempts, complexity attempts, and ticks advanced. The suite exits
non-zero unless at least one model has positive median completion, utility,
production, and visible fortress complexity progress.

## Live sequence

### 0:00 to 0:20 - frame the project

What to say:

> fort-gym is an open-source benchmark harness for agentic systems. The fast path
> is a deterministic mock Dwarf Fortress-like environment, and the live path uses
> DFHack. The demo shows the harness loop: run an agent, capture a JSONL trace,
> summarize it, and surface the run on the leaderboard.

Point at:

- the CI badge in `README.md`
- the leaderboard screenshot near the top of `README.md`

### 0:20 to 1:05 - run a local benchmark

Terminal 1:

```bash
rm -rf /tmp/fort-gym-demo
ARTIFACTS_DIR=/tmp/fort-gym-demo fort-gym quickstart --no-serve --max-steps 3 --ticks-per-step 10
```

Expected output shape:

```text
Mock run complete.
  run_id: <hex id>
  trace: <artifact root>/<run_id>/trace.jsonl
  summary: <artifact root>/<run_id>/summary.json
  public token: <token>
  leaderboard series: 1
```

What to say:

> This just ran a baseline agent against the mock backend. The important part is
> that every step is written to a trace, and the summary is registered for the
> public leaderboard.

### 1:05 to 1:45 - show the artifacts

Terminal 1:

```bash
export RUN_ID=$(find /tmp/fort-gym-demo -mindepth 1 -maxdepth 1 -type d | sort | tail -n 1 | xargs basename)
python - <<'PY'
import json
import os

path = f"/tmp/fort-gym-demo/{os.environ['RUN_ID']}/trace.jsonl"
with open(path, encoding="utf-8") as handle:
    record = json.loads(handle.readline())
preview_keys = ("run_id", "step", "action", "validation", "metrics", "score")
preview = {key: record.get(key) for key in preview_keys}
print(json.dumps(preview, indent=2))
PY
cat "/tmp/fort-gym-demo/$RUN_ID/summary.json"
```

Expected trace fields:

```text
"run_id": "<same id>"
"step": 0
"action"
"validation"
"metrics"
"score"
```

Expected summary fields:

```text
"backend": "mock"
"model": "random"
"steps": 3
"total_score": <number>
```

What to say:

> This is the audit trail. A reviewer can inspect the observation, the chosen
> action, validation, execution result, metrics, and score in the full JSONL
> trace. The summary is the compact result used by the dashboard.

### 1:45 to 2:40 - show the leaderboard

Terminal 2:

```bash
ARTIFACTS_DIR=/tmp/fort-gym-demo FORT_GYM_INSECURE_ADMIN=1 fort-gym api --port 8018 --no-reload
```

Browser:

```text
http://127.0.0.1:8018/leaderboard
```

Expected page state:

- header says `Fort-Gym Leaderboard`
- chart contains one `random@<git_sha> (mock)` series
- table shows backend `mock`, runs `1`, and a numeric best score

What to say:

> The API and dashboard read from the same local registry. This is still the mock
> path, but it exercises the trace capture, scoring summary, share token, and
> public leaderboard flow end to end.

### 2:40 to 3:00 - close with the expansion path

What to say:

> The live DFHack backend is the extension point for real fortress runs. The
> value of the harness is that mock and live runs share the same artifacts,
> leaderboard, and evaluation surface, so improvements can land safely before
> spending time on a live environment.

## Recovery notes

- If port 8018 is busy, rerun the API command with another port and open the same
  `/leaderboard` path on that port.
- If `fort-gym` is not found, activate the virtualenv with `source .venv/bin/activate`.
- If the leaderboard is empty, confirm both the quickstart and API commands used
  the same `ARTIFACTS_DIR=/tmp/fort-gym-demo` value.

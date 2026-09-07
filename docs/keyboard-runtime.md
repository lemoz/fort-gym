# Reusable keyboard campaign continuation

The native entrypoint is `python -m scripts.campaign_keyboard_native`.
It replaces the per-experiment native fixture while reusing CampaignLoop,
the native checkpoint/save verifier, isolated game launcher and model exchange.
The host-side model operation is
`fort_gym.bench.agent.keyboard_courier.answer_request`.
The outside VM/container owner remains responsible for its own provisioning,
read-only checkpoint mount, host courier transport and final VM teardown.

## Declared window

`experiments/campaign_astra_keyboard_window_20260907b.json` starts at cursor 72
and permits eight 16-decision segments. It preserves the existing cumulative
256-invocation/eight-million-returned-token extension. It does not reset usage,
change the model prompt, add strategy guidance, or extend that budget again.
The research hypothesis is descriptive metadata for evaluation, not an extra
instruction passed to the playing model.

The original condition remains `campaign_astra_keyboard_20260907.json`:
Astra Medium, ChatGPT subscription, native keyboard v2, readable 120x40 screen,
model-selected bounded advancement and a fresh account read before each call.
No API credentials or model runtime are needed inside the game container.

## Native command

Run inside the owned isolated game environment, on a clean committed checkout:

```sh
python -m scripts.campaign_keyboard_native run \
  --condition experiments/campaign_astra_keyboard_20260907.json \
  --window experiments/campaign_astra_keyboard_window_20260907b.json \
  --checkpoint /previous/checkpoint \
  --latest-usage /previous/loop/usage.jsonl \
  --source /opt/dwarf-fortress \
  --output /evidence/astra \
  --port 5530 \
  --revision FULL_EXECUTED_COMMIT
```

The checkpoint must be the latest fully settled one, and its latest usage journal
must match the checkpoint copy. A later unresolved tail is not permission to
restore an older game state. Each segment uses a distinct local port, verifies
the actual screen dimensions, loads the preceding native save, retains private
before/after observations and agent state, and creates a verified checkpoint.
The final runtime receipt distinguishes completion, budget pause and failure.
Unsettled failures retain a forensic native save where possible; that save is
explicitly not advertised as a resumable campaign checkpoint.

## Host courier and game-user response delivery

The outer owner reads a complete request from the dedicated exchange directory
and gives `answer_request` a unique private host directory. The courier records
a single-use claim before inference, performs the existing fresh subscription
check, and retains the response and actual returned-token summary. A second call
at the same directory cannot silently infer again. Ambiguous errors keep their
dispatch state unknown.

Before the first model call, send a harmless JSON object on stdin to:

```sh
python -m scripts.campaign_keyboard_native probe \
  --output /evidence/astra/transport-probe.json
```

Send the returned response JSON on stdin, as the same unprivileged game user, to:

```sh
python -m scripts.campaign_keyboard_native publish-response \
  --exchange /evidence/astra/exchange --request-id REQUEST_UUID_HEX
```

The publisher binds the response to the exact original request digest, publishes
without overwriting and verifies game-user readback. Do not copy a root-owned
private response into the game directory and assume the game can read it.
Neither courier nor publisher chooses native actions. Website publication remains
a separate explicit non-content projection; the exchange and native evidence
directories are private.

## Verification

Executed source `a004c490f` passed 96 focused runtime/checkpoint/transport tests,
2,326 broad-suite tests with ten skips, and changed-file Ruff/scoped mypy for
all four new source modules. The broad suite's one sandbox-denied localhost bind
passed separately with socket access. Exact-head
[CI passed](https://github.com/lemoz/fort-gym/actions/runs/34158366994).

The reusable command has now resumed the real cursor-72 campaign, completed its
first 16-decision segment and produced an independently re-verified cursor-88
checkpoint. It retains 2,800,235 cumulative tokens and 25,000 elapsed native
ticks, preserving the original model, memory and budget-extension condition.
The next native process was observed running. This is an in-progress 128-decision
window, not a completed window or a terminal public milestone. The final outcome,
usage and VM teardown still require verification after the owned run stops.

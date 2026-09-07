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

The reusable window is now terminal and failed, not active. It retained a verified
cursor-88 checkpoint, then committed through decision 100 at 29,000 elapsed ticks.
The 101st model response sent three confirmed key events, followed by a 2,000-tick
request that timed out with zero elapsed ticks while native focus remained
`dwarfmode/Build/Type`. The newer native save and all model usage are retained;
that forensic save is not a resumable checkpoint. Do not rewind to cursor 88.

An independent retained-evidence audit verifies 913,252 new tokens and 3,231,792
cumulative campaign tokens. Including prior failed deliveries gives 3,300,796.
Subscription charges remain unreported. Both native processes, the container and
owned VM are stopped. Original configuration, budget extension, memory handoffs
and trace/journal prefixes remain intact. The public non-content interruption is
`experiments/evidence/astra_native_keyboard_interruption_20260907.json`.

## Build-menu clock correction

The v2 adapter now reads the existing native keyboard probe before positive clock
requests. For the exact observed blocking build-menu focus, two matching probes
and paused calendar observations attest a zero-tick deferral without sending
keys or invoking the clock. The model receives factual requested/actual tick
feedback and chooses its next action. The boundary can checkpoint normally.
Other focuses retain the existing clock path; historical keyboard v1 and helper
conditions are unchanged. The original timed-out run is not reclassified.

Regression tests cover unchanged native boundaries, unknown/changed evidence,
no automatic recovery input, checkpoint continuation and failure usage retention.
The window also retains a failed worker's detailed receipt while recording
successful native cleanup separately. These corrections have offline test proof;
fresh native validation and reconciliation of the retained failed tail remain
next, before further campaign model calls. Website records distinguish the
interruption from the older resumable checkpoint and do not claim live activity.

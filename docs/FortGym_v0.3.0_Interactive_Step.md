# Fort-Gym v0.3.0 — Interactive Step Control

### Highlights
- Added `/step` endpoint with DFHack execution, throttling, and persistence.
- SSE `/stream` emits live step updates with reward and observation payloads.
- Artifacts and summaries verified; regression tests passing.

### Verification

```bash
python3 -m pytest -q --maxfail=1
# /step is an admin endpoint:
# - set FORT_GYM_INSECURE_ADMIN=1 for local dev, OR
# - set FORT_GYM_ADMIN_PASSWORD and pass basic auth below.
curl -sD /tmp/step1.h -o /tmp/step1.out -u admin:'<password>' -X POST http://127.0.0.1:8000/step -H 'content-type: application/json' --data-binary '@/tmp/step_req.json'
curl -sD /tmp/step2.h -o /tmp/step2.out -u admin:'<password>' -X POST http://127.0.0.1:8000/step -H 'content-type: application/json' --data-binary '@/tmp/step_req.json'
grep 'HTTP/1.1 429' /tmp/step2.h
```

### Environment
- DFHack 0.47.05-r8 headless, bound to 127.0.0.1:5000
- Fort-Gym API on port 8000

### Live Action Safety
- Manager orders restricted to: bed, door, table, chair, barrel, bin (qty ≤ 5).
- Dig/channel rectangles limited to 30×30 tiles; chop leverages `autochop`.
- All DFHack helpers run via `dfhack-run` with a 2.5s timeout; failures surface as SSE `stderr` events and noop steps.
- `RandomAgent` defaults to the safe action set; `--safe/--no-safe` flag toggles behaviour in CLI demos.

### Live Tests
```bash
DFHACK_LIVE=1 pytest -q -k actions_live
```

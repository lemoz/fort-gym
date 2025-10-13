# Fort-Gym v0.3.0 — Interactive Step Control

### Highlights
- Added `/step` endpoint with DFHack execution, throttling, and persistence.
- SSE `/stream` emits live step updates with reward and observation payloads.
- Artifacts and summaries verified; regression tests passing.

### Verification

```bash
python3 -m pytest -q --maxfail=1
curl -sD /tmp/step1.h -o /tmp/step1.out -X POST http://127.0.0.1:8000/step -H 'content-type: application/json' --data-binary '@/tmp/step_req.json'
curl -sD /tmp/step2.h -o /tmp/step2.out -X POST http://127.0.0.1:8000/step -H 'content-type: application/json' --data-binary '@/tmp/step_req.json'
grep 'HTTP/1.1 429' /tmp/step2.h
```

### Environment
- DFHack 0.47.05-r8 headless, bound to 127.0.0.1:5000
- Fort-Gym API on port 8000 (tmux session `fortgym`)

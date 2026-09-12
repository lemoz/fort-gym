"""Summarize recorded controls usage, not native acceptance or completed products."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

ITEMS = frozenset(('bed', 'door', 'table', 'chair', 'barrel', 'bin', 'brew'))


def count(value: object) -> bool:
    return type(value) is int and value >= 0


def summarize_actions(rows: list[dict]) -> dict:
    """Separate key presses, job requests, acknowledged queues and real ticks.

    Missing native counters remain unknown. The terminal auditor must separately
    bind these rows to original responses and the saved checkpoint.
    """
    routes: Counter = Counter()
    requested_jobs: Counter = Counter()
    queued_jobs: Counter = Counter()
    accepted = keys_requested = keys_sent = unknown_keys = unknown_jobs = 0
    requested_ticks = actual_ticks = timeouts = zero_tick_timeouts = deferrals = 0
    for row in rows:
        action, execution, clock = row['action'], row['execute'], row['tick_advance']
        route, params = action['type'], action['params']
        if type(execution.get('accepted')) is not bool:
            raise ValueError('Action acceptance is unknown')
        if route not in ('KEYSTROKE', 'WORKSHOP_JOB'):
            raise ValueError('Action is outside this controls study')
        requested, advanced = action['advance_ticks'], clock['ticks_advanced']
        if not count(requested) or not count(advanced):
            raise ValueError('Native or requested ticks are invalid')
        native = execution.get('result')
        native = native if isinstance(native, dict) else {}
        routes[route] += 1
        accepted += execution['accepted']
        requested_ticks += requested
        actual_ticks += advanced
        timeouts += clock.get('timeout') is True
        zero_tick_timeouts += clock.get('timeout') is True and advanced == 0
        deferrals += clock.get('deferred') is True
        if route == 'KEYSTROKE':
            keys = params.get('keys')
            if not isinstance(keys, list) or not all(isinstance(key, str) for key in keys):
                raise ValueError('Requested keys are invalid')
            keys_requested += len(keys)
            sent = native.get('keys_sent')
            if count(sent):
                keys_sent += sent
            else:
                unknown_keys += 1
        else:
            item, quantity = params.get('item'), params.get('quantity')
            if not isinstance(item, str) or item not in ITEMS or not count(quantity) or not 1 <= quantity <= 5:
                raise ValueError('Workshop request is invalid')
            requested_jobs[item] += quantity
            queued = native.get('jobs_queued')
            if not count(queued):
                unknown_jobs += 1
            elif queued != (quantity if execution['accepted'] else 0):
                raise ValueError('Queue count contradicts action acceptance')
            else:
                queued_jobs[item] += queued
    return {
        'schema_version': 'fortgym.selected-workshop-action-summary/v1',
        'decisions': len(rows), 'action_routes': dict(routes),
        'accepted_actions': accepted, 'rejected_actions': len(rows)-accepted,
        'keyboard': {'decisions': routes['KEYSTROKE'], 'requested_key_presses': keys_requested,
                     'known_keys_sent': keys_sent, 'records_without_key_count': unknown_keys},
        'workshop': {'decisions': routes['WORKSHOP_JOB'],
                     'requested_jobs_by_item': dict(requested_jobs),
                     'known_jobs_queued_by_item': dict(queued_jobs),
                     'records_without_queue_count': unknown_jobs,
                     'completed_products_measured': False},
        'clock': {'requested_ticks': requested_ticks, 'advanced_ticks': actual_ticks,
                  'timeout_requests': timeouts, 'zero_tick_timeout_requests': zero_tick_timeouts,
                  'deferred_requests': deferrals},
        'native_audit_performed': False,
    }


def read_rows(path: Path, through: int | None) -> list[dict]:
    raw = path.read_bytes()
    complete = [line for line in raw.split(b'\n')[:-1] if line]
    if through is None and raw and not raw.endswith(b'\n'):
        raise ValueError('Trace ends with an incomplete record; select a complete boundary')
    if through is not None:
        if not count(through) or through < 1 or len(complete) < through:
            raise ValueError('Requested decision boundary is not complete')
        complete = complete[:through]
    rows = [json.loads(line) for line in complete]
    if (not rows or any(type(row.get('step')) is not int for row in rows)
            or [row.get('step') for row in rows] != list(range(len(rows)))):
        raise ValueError('Trace is empty or nonconsecutive')
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trace', type=Path, required=True)
    parser.add_argument('--through', type=int, help='Complete decision count, starting at decision one')
    args = parser.parse_args()
    rows = read_rows(args.trace, args.through)
    summary = summarize_actions(rows)
    summary['source_records_sha256'] = hashlib.sha256(
        json.dumps(rows, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    ).hexdigest()
    print(json.dumps(summary, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()

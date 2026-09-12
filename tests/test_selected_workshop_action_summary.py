import json

import pytest

from scripts.summarize_selected_workshop_actions import read_rows, summarize_actions


def key(*, accepted=True, sent=2, requested=2000, advanced=0, timeout=False, deferred=False):
    return {'action': {'type': 'KEYSTROKE', 'params': {'keys': ['q', 'a']}, 'advance_ticks': requested},
            'execute': {'accepted': accepted, 'result': {'keys_sent': sent}},
            'tick_advance': {'ticks_advanced': advanced, 'timeout': timeout, 'deferred': deferred}}


def job(*, accepted=True, queued=5):
    return {'action': {'type': 'WORKSHOP_JOB', 'params': {'item': 'bed', 'quantity': 5},
                       'advance_ticks': 2000},
            'execute': {'accepted': accepted, 'result': {'jobs_queued': queued}},
            'tick_advance': {'ticks_advanced': 0, 'timeout': True}}


def test_queues_are_not_keys_or_finished_products_and_timeouts_are_not_progress():
    data = summarize_actions([key(advanced=2000), job(), job(accepted=False, queued=0)])
    assert data['decisions'] == 3 and data['accepted_actions'] == 2
    assert data['keyboard'] == {'decisions': 1, 'requested_key_presses': 2,
                                'known_keys_sent': 2, 'records_without_key_count': 0}
    assert data['workshop']['requested_jobs_by_item'] == {'bed': 10}
    assert data['workshop']['known_jobs_queued_by_item'] == {'bed': 5}
    assert data['workshop']['records_without_queue_count'] == 0
    assert data['workshop']['completed_products_measured'] is False
    assert data['clock'] == {'requested_ticks': 6000, 'advanced_ticks': 2000,
                             'timeout_requests': 2, 'zero_tick_timeout_requests': 2, 'deferred_requests': 0}
    assert data['native_audit_performed'] is False


@pytest.mark.parametrize('value', [None, True, -1, '5'])
def test_missing_or_invalid_counters_stay_unknown(value):
    data = summarize_actions([key(sent=value), job(queued=value)])
    assert data['keyboard']['records_without_key_count'] == 1
    assert data['keyboard']['known_keys_sent'] == 0
    assert data['workshop']['records_without_queue_count'] == 1
    assert data['workshop']['known_jobs_queued_by_item'] == {}


@pytest.mark.parametrize('value', [None, 0, 1, 'true'])
def test_invalid_acceptance_is_not_coerced(value):
    with pytest.raises(ValueError, match='acceptance'):
        summarize_actions([key(accepted=value)])


@pytest.mark.parametrize('value', [None, True, -1, '2000'])
def test_invalid_native_ticks_are_rejected(value):
    with pytest.raises(ValueError, match='ticks'):
        summarize_actions([key(advanced=value)])


@pytest.mark.parametrize('accepted,queued', [(True, 0), (True, 4), (True, 6), (False, 1)])
def test_contradictory_queue_count_is_rejected(accepted, queued):
    with pytest.raises(ValueError, match='contradicts'):
        summarize_actions([job(accepted=accepted, queued=queued)])


def test_menu_deferral_is_separate_from_a_dispatched_clock_timeout():
    data = summarize_actions([key(deferred=True), key(timeout=True)])
    assert data['clock']['deferred_requests'] == 1
    assert data['clock']['timeout_requests'] == 1
    assert data['clock']['advanced_ticks'] == 0


def test_only_a_complete_consecutive_boundary_is_read(tmp_path):
    trace = tmp_path/'trace.jsonl'
    row = {'step': 0, **key()}
    trace.write_bytes((json.dumps(row)+'\n'+ '{"step":1').encode())
    assert read_rows(trace, 1) == [row]
    with pytest.raises(ValueError, match='incomplete'):
        read_rows(trace, None)
    with pytest.raises(ValueError, match='not complete'):
        read_rows(trace, 2)
    trace.write_text(json.dumps({'step': 1, **key()})+'\n')
    with pytest.raises(ValueError, match='nonconsecutive'):
        read_rows(trace, 1)


def test_later_unselected_record_cannot_change_a_selected_boundary(tmp_path):
    trace = tmp_path/'trace.jsonl'
    row = {'step': 0, **key()}
    trace.write_text(json.dumps(row)+'\nINVALID LATER RECORD\n')
    assert read_rows(trace, 1) == [row]


def test_boolean_step_is_not_an_integer_cursor(tmp_path):
    trace = tmp_path/'trace.jsonl'
    trace.write_text(json.dumps({'step': False, **key()})+'\n')
    with pytest.raises(ValueError, match='nonconsecutive'):
        read_rows(trace, 1)


def test_summary_never_exposes_private_memory_or_native_identifiers():
    row = job()
    row['action']['memory_update'] = 'PRIVATE MEMORY'
    row['execute']['result']['created_job_ids'] = [123, 456]
    row['execute']['result']['workshop_id'] = 789
    row['observation_text'] = 'PRIVATE SCREEN'
    raw = json.dumps(summarize_actions([row]))
    assert 'PRIVATE' not in raw and 'memory' not in raw
    assert 'created_job_ids' not in raw and 'workshop_id' not in raw

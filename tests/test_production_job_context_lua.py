"""Read-only callback context with native doubles, not actual job attribution."""

import subprocess

import pytest

from fort_gym.bench.production_observer_lua import PRODUCTION_OBSERVER_LUA
from tests.test_production_observer_lua import LUA, PRELUDE

FIXTURE = r"""
df.job_type[11]='CustomReaction'
local current={id=100,job_type=11,reaction_name='BREW_DRINK_FROM_PLANT'}
local worker={id=19,job={current_job=current}}
local holder={id=7}
local holder_reads, worker_reads=0,0
dfhack.job={getHolder=function(job)
    assert(job==current);holder_reads=holder_reads+1;return holder
end,getWorker=function(job)
    assert(job==current);worker_reads=worker_reads+1;return worker
end}
local observer=new_production_observer(df,dfhack,eventful,config)
observer.start()
local function fire(value)
    eventful.onReactionComplete[key]({code='BREW_DRINK_FROM_PLANT'}, {}, value, {}, {}, {item(42,5,6)})
end
"""


def run(scenario):
    if LUA is None:
        pytest.skip("Lua interpreter unavailable")
    result = subprocess.run(
        [LUA, "-"],
        input=PRELUDE + PRODUCTION_OBSERVER_LUA + FIXTURE + scenario,
        text=True,
        capture_output=True,
        timeout=5,
    )
    assert result.returncode == 0, result.stderr


def test_context_copies_actual_job_worker_and_holder_without_mutation():
    run("""
fire(worker)
local r=observer.snapshot()
local c=r.events[1].worker_job
assert(c.status=='observed' and c.job_id==100 and c.job_type=='CustomReaction')
assert(c.reaction_name=='BREW_DRINK_FROM_PLANT' and c.building_holder_id==7)
assert(c.assigned_worker_id==19 and r.events[1].worker_id==19)
assert(holder_reads==1 and worker_reads==1 and r.collector_records_complete)
assert(r.job_context_read_failures==0 and not r.native_coverage_validated)
current.id=200;holder.id=8;worker.id=20
assert(observer.snapshot().events[1].worker_job.job_id==100)
assert(observer.snapshot().events[1].worker_job.building_holder_id==7)
c.job_id=300
assert(observer.snapshot().events[1].worker_job.job_id==100)
assert(worker.job.current_job==current and current.id==200)
""")


@pytest.mark.parametrize(
    "setup,status",
    [
        ("worker=nil", "no_worker"),
        ("worker.job=nil", "no_current_job"),
        ("worker.job.current_job=nil", "no_current_job"),
    ],
)
def test_absent_context_remains_explicit_without_losing_outputs(setup, status):
    run(
        setup
        + f"""
fire(worker)
local r=observer.snapshot()
assert(r.events[1].worker_job.status=='{status}')
assert(r.events[1].output_items[1].item_id==42 and r.collector_records_complete)
assert(holder_reads==0 and worker_reads==0)
"""
    )


@pytest.mark.parametrize(
    "setup",
    [
        "current.id=false",
        "current.job_type=-1",
        "df.job_type[11]=''",
        "current.reaction_name=false",
        "current.reaction_name=string.rep('A',129)",
        "current.reaction_name='bad'..string.char(10)",
        "holder.id=false",
        "dfhack.job.getWorker=function() return {id=false} end",
        "dfhack.job.getHolder=function() error('read failed') end",
    ],
)
def test_read_failure_retains_output_but_invalidates_complete_capture(setup):
    run(
        setup
        + """
fire(worker)
local r=observer.snapshot()
assert(#r.events==1 and r.events[1].output_items[1].item_id==42)
assert(r.events[1].worker_job.status=='read_failed')
assert(r.job_context_read_failures==1 and not r.collector_records_complete)
assert(r.read_failures==0 and r.flow_measurement.production=='not_measured')
"""
    )


def test_nil_or_conflicting_native_references_are_retained_not_invented():
    run("""
dfhack.job.getHolder=function() return nil end
dfhack.job.getWorker=function() return {id=55} end
fire(worker)
local c=observer.snapshot().events[1].worker_job
assert(c.status=='observed' and c.building_holder_id==false and c.assigned_worker_id==55)
assert(observer.snapshot().collector_records_complete)
""")

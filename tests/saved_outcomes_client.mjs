import assert from 'node:assert/strict';
import test from 'node:test';
import fs from 'node:fs';
import crypto from 'node:crypto';
import {validateSavedOutcomes, savedOutcome, savedOutcomeSummary, savedOutcomeHistory} from '../web/static/saved-outcomes.mjs';

const index = JSON.parse(fs.readFileSync('web/static/saved-outcomes.json'));
const catalog = JSON.parse(fs.readFileSync('web/static/recordings/catalog.json')).recordings;
const replay = id => JSON.parse(fs.readFileSync('web/static/recordings/'+id+'.json'));
const newest = index.outcomes[0].recording_id;

test('saved outcomes bind original recordings, native clocks, metrics and evidence links', () => {
  for (const value of index.outcomes) {
    const raw = fs.readFileSync('web/static/recordings/'+value.recording_id+'.json');
    assert.equal(crypto.createHash('sha256').update(raw).digest('hex'),value.recording_sha256);
    const recording = JSON.parse(raw);
    assert.equal(savedOutcome(index,recording,catalog),value);
    assert.match(savedOutcomeSummary(value),/standard keyboard input.*elapsed game years/);
    assert.match(savedOutcomeSummary(value),value.functioning_assessment === 'operating_with_adaptive_supply_recovery'
      ? /Operating with adaptive supply recovery/ : /Operating but fragile/);
    assert.match(savedOutcomeHistory(value,recording),/dollar charges were not reported/);
    assert.match(savedOutcomeHistory(value,recording),/not an independent trial/);
    assert.equal(recording.campaign,undefined);
  }
  assert.match(savedOutcomeSummary(index.outcomes[0]),/19 living dwarves · 1 recorded death ·/);
  assert.equal(savedOutcome(index,replay('astra-matched-r1-1-64'),catalog),null);
});

test('the new adaptation assessment does not relabel earlier saved endpoints', () => {
  assert.equal(index.outcomes[0].functioning_assessment,'operating_with_adaptive_supply_recovery');
  assert.match(savedOutcomeSummary(index.outcomes[0]),/Long-term sustainability remains unproven/);
  for (const value of index.outcomes.slice(1)) {
    assert.equal(value.functioning_assessment,'operating_but_fragile');
    assert.match(savedOutcomeSummary(value),/Operating but fragile/);
    assert.doesNotMatch(savedOutcomeSummary(value),/Operating with adaptive supply recovery/);
  }
});

for (const [field,value] of [
  ['recording_sha256','0'.repeat(64)],['source_recording_id','astra-matched-r1-1-64'],
  ['campaign_id','another-campaign'],['source_revision','0'.repeat(40)],['model','another-model'],
  ['reasoning_effort','high'],['control_profile','shortcut'],['saved_decision',644],
  ['saved_elapsed_ticks',403200],['saved_elapsed_ticks',true],['origin_year',29],
  ['origin_year_tick',0],['ticks_per_year',400000],['saved_year',30],['saved_year_tick',0],
  ['total_responses',64],['total_tokens',-1],['total_tokens',true],
  ['reported_model_charge_usd',0],['checkpoint_sha256','invalid'],
  ['native_audit_sha256','0'.repeat(64)],['fresh_reload_verified',false],
  ['human_gameplay_rescue',true],['sustainability_proven',true],
  ['functioning_assessment','self_sufficient'],['private_memory','DO_NOT_EXPORT'],
]) test('rejects relabelled saved evidence: '+field, () => {
  const changed=structuredClone(index); changed.outcomes[0][field]=value;
  assert.throws(()=>savedOutcome(changed,replay(newest),catalog));
});

for (const field of ['result','review']) test('rejects unsafe or incomplete '+field+' links', () => {
  for (const value of [null,{url:'javascript:alert(1)',sha256:'a'.repeat(64)},
    {...index.outcomes[0][field],url:index.outcomes[0][field].url.replace('github.com','github.com.evil.test')},
    {...index.outcomes[0][field],sha256:'wrong'}, {...index.outcomes[0][field],private:'leak'}]) {
    const changed=structuredClone(index); changed.outcomes[0][field]=value;
    assert.throws(()=>savedOutcome(changed,replay(newest),catalog));
  }
});
test('invalid population, duplicate identities, and missing predecessor stay invalid', () => {
  const changed=structuredClone(index); changed.outcomes[0].saved_metrics.population=20;
  assert.throws(()=>savedOutcome(changed,replay(newest),catalog));
  assert.throws(()=>validateSavedOutcomes({...index,outcomes:[index.outcomes[0],index.outcomes[0]]}));
  assert.throws(()=>validateSavedOutcomes({...index,private:'leak'}));
  assert.throws(()=>savedOutcome(index,replay(newest),catalog.filter(row=>row.id!==index.outcomes[0].source_recording_id)));
});
test('an invalid different entry does not invalidate an unrelated verified outcome', () => {
  const changed=structuredClone(index); changed.outcomes[1].saved_decision=-1;
  assert.equal(savedOutcome(changed,replay(newest),catalog),changed.outcomes[0]);
});

class Element {
  constructor(id) { this.id=id; this.listeners={}; this.children=[]; this.dataset={}; this.attributes={}; this.value='1'; this.hidden=false; this.disabled=false; this.textContent=''; }
  setAttribute(key,value) { this.attributes[key]=value; }
  addEventListener(key,fn) { (this.listeners[key] ||= []).push(fn); }
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this.children=items; }
  querySelectorAll() { return this.children.filter(node=>node.dataset.recording); }
  getContext() { return {fillRect(){},fillText(){}}; }
  async emit(type) { for (const fn of this.listeners[type] || []) await fn({target:this}); }
}
const settle=async()=>{for(let n=0;n<10;n++)await new Promise(resolve=>setImmediate(resolve));};

for (const mode of ['valid','unavailable','invalid','delayed']) test('real player preserves replay and evidence state: '+mode,async()=>{
  const originals=Object.fromEntries(['document','fetch','location','setInterval','clearInterval'].map(key=>[key,globalThis[key]]));
  const elements=new Map(), timers=[];
  for(const match of fs.readFileSync('web/landing.html','utf8').matchAll(/id="(watch-[^"]+)"/g))
    elements.set(match[1],new Element(match[1]));
  const get=id=>elements.get('watch-'+id);
  let resolveIndex, live={schema_version:'fortgym.watch-live/v1',status:'not_connected'};
  try {
    globalThis.location={search:'?recording='+newest};
    globalThis.document={hidden:false,getElementById:id=>elements.get(id),createElement:tag=>new Element(tag),addEventListener(){}};
    globalThis.setInterval=(fn,delay)=>{timers.push({fn,delay});return timers.length;};
    globalThis.clearInterval=()=>{};
    globalThis.fetch=async url=>{
      if(url==='/static/saved-outcomes.json') {
        if(mode==='unavailable') throw Error('offline');
        if(mode==='delayed') return new Promise(resolve=>{resolveIndex=resolve;});
        const value=structuredClone(index);
        if(mode==='invalid') value.outcomes[0].recording_sha256='0'.repeat(64);
        return {ok:true,json:async()=>value};
      }
      return {ok:true,json:async()=>url.includes('watch-active') ? live : JSON.parse(fs.readFileSync('web'+url))};
    };
    await import('../web/static/home-watch.mjs?saved-outcome-test='+mode); await settle();
    assert.equal(get('decision').textContent,'Decision 773 / 836');
    assert.equal(get('play').disabled,false);
    if(mode==='delayed') {
      assert.equal(get('outcome').hidden,true);
      await get('runs').children.find(node=>node.dataset.recording==='astra-matched-r1-1-64').emit('click'); await settle();
      resolveIndex({ok:true,json:async()=>index}); await settle();
      assert.equal(get('outcome').hidden,true);
      assert.equal(get('decision').textContent,'Decision 1 / 64');
      await get('runs').children.find(node=>node.dataset.recording===newest).emit('click'); await settle();
    }
    if(mode==='valid'||mode==='delayed') {
      assert.equal(get('outcome').hidden,false);
      assert.equal(get('outcome-status').hidden,true);
      assert.match(get('outcome-summary').textContent,/19 living dwarves.*151 food units and 528 drinks/);
      assert.equal(get('result').href,index.outcomes[0].result.url);
      assert.equal(get('reload').href,index.outcomes[0].review.url);
      assert.equal(get('reload').textContent,'Inspect the gameplay assessment →');
      assert.equal(get('prior').href,'/?recording=astra-keyboard-endurance-v1-709-772#watch-root');
      get('range').value='5'; await get('range').emit('input');
      assert.equal(get('decision').textContent,'Decision 778 / 836');
      assert.equal(get('execution').textContent,'Key command accepted by the harness. Acceptance does not prove the intended outcome.');
      // The previous replay retains its rejected input and its own endpoint links.
      await get('runs').children.find(node=>node.dataset.recording==='astra-keyboard-endurance-v1-645-708').emit('click'); await settle();
      assert.equal(get('result').href,index.outcomes.find(row=>row.recording_id==='astra-keyboard-endurance-v1-645-708').result.url);
      assert.match(get('outcome-summary').textContent,/75 food units and 93 drinks/);
      get('range').value='24'; await get('range').emit('input');
      assert.equal(get('decision').textContent,'Decision 669 / 708');
      assert.equal(get('execution').textContent,'Key command was not accepted.');
      assert.equal(get('outcome').hidden,false);
    } else {
      assert.equal(get('outcome').hidden,true);
      assert.equal(get('outcome-status').hidden,false);
      await get('next').emit('click');
      assert.equal(get('decision').textContent,'Decision 774 / 836');
    }
    live={schema_version:'fortgym.watch-live/v1',status:'running',run_id:'current',model:'gpt-6-astra',
      observed_at_unix:Math.floor(Date.now()/1000),fresh_for_seconds:30,
      frame:{...replay(newest).frames[0],captured_at_unix:Math.floor(Date.now()/1000),action_status:'chosen_not_execution_verified'}};
    await timers.find(timer=>timer.delay===10000).fn(); await get('live').emit('click');
    assert.equal(get('outcome').hidden,true);
    assert.equal(get('outcome-status').hidden,true);
    assert.equal(get('prior').hidden,true);
  } finally { Object.assign(globalThis,originals); }
});

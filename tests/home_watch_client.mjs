import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {glyph, decodeScreen, frameIndex, liveState, validateRecording, initialRecording, recoverySummary, readLiveStatus, campaignSummary, campaignHistory} from '../web/static/home-watch-model.mjs';

const yearTwo = () => JSON.parse(fs.readFileSync('web/static/recordings/astra-year-two-257-416.json'));

test('Year-Two outcome preserves the exact save, usage and qualified claims', () => {
  const data = yearTwo();
  assert.equal(validateRecording(data).frames.length,160);
  assert.match(campaignSummary(data),/1.066 elapsed game years/);
  assert.match(campaignSummary(data),/13 dwarves.*43 raw-food units and 389 drinks/);
  assert.match(campaignHistory(data),/All 448 responses and 11,866,456 tokens remain counted/);
  assert.match(campaignHistory(data),/dollar charges were not reported/);
  for(const [key,value] of [['continued_from_decision',224],['saved_elapsed_ticks',0],
    ['ticks_into_year_two',true],['elapsed_years',2],['total_responses',416],['total_tokens',true],
    ['source_recording_id','../private'],['checkpoint_sha256','invalid'],['fresh_reload_verified',false],
    ['uninterrupted_campaign',true],['human_gameplay_rescue',true],['reported_model_charge_usd',0],
    ['sustainability_proven',true],['repeated_matched_comparison',true],
    ['result_url','javascript:alert(1)'],['reload_url','https://github.com.evil.test/secret']]) {
    const changed=yearTwo(); changed.campaign[key]=value;
    assert.throws(()=>validateRecording(changed),/Invalid campaign outcome/);
  }
  for(const changed of [null,{...data.campaign,saved_metrics:{...data.campaign.saved_metrics,population:99}}])
    assert.throws(()=>validateRecording({...data,campaign:changed}),/Invalid campaign outcome/);
});

const screen = {width:2,height:2,tile_order:'column_major',runs:[[2,219,7,0],[1,1,15,0],[1,32,0,1]]};
const frame = decision => ({decision,screen,action:{intent:'Intent ' + decision,keys:['q'],advance_ticks:0},
  accepted:true,before:{year:30,tick:100},after:{year:30,tick:100,population:7,ticks_advanced:0}});
const record = id => ({schema_version:'fortgym.watch-recording/v1',id,title:id,first_decision:97,last_decision:98,
  saved_through_decision:97,frames:[frame(97),frame(98)]});
const recovered = () => ({...record('b'),saved_through_decision:98,recovery:{
  schema_version:'fortgym.watch-recovery/v1',restored_checkpoint:96,lost_decisions:32,lost_ticks:422,
  total_responses:130,source_recording_id:'a',source_checkpoint_sha256:'a'.repeat(64),
  uninterrupted_campaign:false,actions_replayed:false}});

test('recovery metadata preserves the lost window and cannot claim uninterrupted play', () => {
  assert.equal(validateRecording(recovered()).saved_through_decision,98);
  assert.match(recoverySummary(recovered()),/All 130 model responses remain counted/);
  assert.equal(recoverySummary(record('a')),'');
  for (const [key,value] of [['restored_checkpoint',97],['lost_decisions',0],['lost_ticks',-1],
    ['total_responses',98],['total_responses',true],['uninterrupted_campaign',true],
    ['actions_replayed',true],['source_recording_id','../secret'],['source_recording_id','b'],
    ['source_recording_id',undefined],['source_recording_id',123],['source_checkpoint_sha256','wrong']]) {
    const data=recovered(); data.recovery[key]=value;
    assert.throws(()=>validateRecording(data),/Invalid recovery record/);
  }
  assert.throws(()=>validateRecording({...record('a'),recovery:null}),/Invalid recovery record/);
});

test('CP437 glyphs and column-major RLE retain all native screen codes', () => {
  assert.equal(glyph(1),'☺'); assert.equal(glyph(219),'█'); assert.equal(glyph(127),'⌂');
  assert.equal(glyph(255),' '); assert.equal(glyph(32),' ');
  for (let n = 0; n < 256; n++) assert.equal(glyph(n).length,1);
  assert.deepEqual(decodeScreen(screen),[[219,7,0],[219,7,0],[1,15,0],[32,0,1]]);
  assert.throws(() => decodeScreen({...screen,runs:[[5,219,7,0]]}));
  assert.throws(() => decodeScreen({...screen,tile_order:'row_major'}));
  assert.equal(frameIndex(900,10),9); assert.equal(frameIndex(-1,10),0);
});

test('live status expires and cannot hide future timestamps', () => {
  const live = {schema_version:'fortgym.watch-live/v1',status:'running',observed_at_unix:1000,fresh_for_seconds:30};
  assert.equal(liveState(live,1010),'running');
  assert.equal(liveState(live,1031),'stale');
  assert.throws(() => liveState(live,900));
  assert.equal(validateRecording(record('a')).frames.length,2);
});

test('static relay is a fallback, never a competing live owner', async () => {
  const none={schema_version:'fortgym.watch-live/v1',status:'not_connected'};
  const live={schema_version:'fortgym.watch-live/v1',status:'running',observed_at_unix:Math.floor(Date.now()/1000),fresh_for_seconds:30};
  let paths=[];
  assert.equal(await readLiveStatus(async path=>{paths.push(path);return live;}),live);
  assert.deepEqual(paths,['/public/watch-active']);
  paths=[];
  assert.equal(await readLiveStatus(async path=>{paths.push(path);return path.startsWith('/public/')?none:live;}),live);
  assert.equal(paths.length,2);
  assert.match(paths[1],/^\/static\/live\/watch-active.json\?t=\d+$/);
  for(const value of [null,{status:'running'}, {...live,observed_at_unix:Math.floor(Date.now()/1000)+60}])
    assert.equal(await readLiveStatus(async path=>path.startsWith('/public/')?none:value),none);
  assert.equal(await readLiveStatus(async path=>{if(path.startsWith('/static/'))throw Error('404');return none;}),none);
  await assert.rejects(()=>readLiveStatus(async()=>{throw Error('primary unavailable');}));
});

test('every bundled real recording can be decoded', () => {
  const catalog = JSON.parse(fs.readFileSync('web/static/recordings/catalog.json'));
  for (const entry of catalog.recordings)
    validateRecording(JSON.parse(fs.readFileSync('web/static/recordings/' + entry.id + '.json')));
});

class Element {
    constructor(id) { this.id=id; this.listeners={}; this.children=[]; this.attributes={}; this.dataset={}; this.value='1'; this.disabled=false; this.hidden=false; this.textContent=''; }
    setAttribute(key,value) { this.attributes[key]=value; }
    addEventListener(key,fn) { (this.listeners[key] ||= []).push(fn); }
    append(...items) { this.children.push(...items); }
    replaceChildren(...items) { this.children=items; }
    querySelectorAll() { return this.children.filter(node => node.dataset.recording); }
    getContext() { return {fillRect(){},fillText(){}}; }
    async emit(type, extra={}) { for (const fn of this.listeners[type] || []) await fn({target:this,...extra}); }
}

test('homepage controls, replay switching and live disconnect work in memory', async () => {
  const elements=new Map();
  const html=fs.readFileSync('web/landing.html','utf8');
  for (const match of html.matchAll(/id="(watch-[^"]+)"/g)) elements.set(match[1],new Element(match[1]));
  const element = id => elements.get('watch-'+id);
  const timers=new Map(); let timerId=0;
  const original={document:globalThis.document,fetch:globalThis.fetch,setInterval,clearInterval,now:Date.now};
  let now=1000000;
  Date.now=()=>now;
  globalThis.setInterval=(fn,delay)=>{timers.set(++timerId,{fn,delay});return timerId;};
  globalThis.clearInterval=id=>timers.delete(id);
  globalThis.document={hidden:false,getElementById:id=>elements.get(id),createElement:tag=>new Element(tag),addEventListener(){}};
  let live={schema_version:'fortgym.watch-live/v1',status:'not_connected'};
  const requests=[];
  globalThis.fetch=async url=>{
    requests.push(url);
    const data=url.endsWith('catalog.json') ? {schema_version:'fortgym.watch-catalog/v1',recordings:[{id:'a',title:'A',window:'97–98'},{id:'b',title:'B',window:'97–98'}]}
      : url.includes('watch-active') ? structuredClone(live) : url.includes('/a.json') ? record('a') : recovered();
    return {ok:true,json:async()=>data};
  };
  const settle=async()=>{for(let n=0;n<10;n++) await new Promise(resolve=>setImmediate(resolve));};
  try {
    await import('../web/static/home-watch.mjs?test=controls');
    await settle();
    assert.equal(element('decision').textContent,'Decision 97 / 98');
    assert.equal(element('play').disabled,false);
    await element('next').emit('click');
    assert.match(element('boundary').textContent,/UNSAVED TAIL/);
    await element('play').emit('click');
    assert.equal(element('decision').textContent,'Decision 97 / 98');
    const playback=[...timers.values()].at(-1); playback.fn();
    assert.equal(element('play').textContent,'Play');
    assert.equal(element('decision').textContent,'Decision 98 / 98');
    const buttonB=element('runs').children.find(node=>node.dataset.recording==='b');
    const buttonA=element('runs').children.find(node=>node.dataset.recording==='a');
    const normalFetch=globalThis.fetch;
    globalThis.fetch=async url=>{if(url.includes('/b.json')) throw Error('offline'); return normalFetch(url);};
    await buttonB.emit('click'); await settle();
    assert.equal(element('title').textContent,'a');
    assert.match(element('load-status').textContent,/unavailable/);
    assert.equal(element('play').disabled,false);
    let resolveB;
    globalThis.fetch=async url=>url.includes('/b.json') ? new Promise(resolve=>{resolveB=resolve;}) : normalFetch(url);
    const pendingB=buttonB.emit('click'); await settle();
    await buttonA.emit('click'); await settle();
    resolveB({ok:true,json:async()=>recovered()}); await pendingB; await settle();
    assert.equal(element('title').textContent,'a'); // A late response cannot replace the selected run.
    globalThis.fetch=normalFetch;
    await buttonB.emit('click'); await settle();
    assert.equal(element('title').textContent,'b');
    assert.equal(element('badge').textContent,'RECOVERED RUN');
    assert.equal(element('recovery').hidden,false);
    assert.match(element('recovery').textContent,/Earlier 32 decisions and 422 game ticks/);
    assert.equal(element('prior').href,'/?recording=a#watch-root');
    await buttonA.emit('click'); await settle();
    assert.equal(element('recovery').hidden,true);
    assert.equal(element('prior').hidden,true);
    await element('next').emit('click');
    assert.match(element('boundary').textContent,/UNSAVED TAIL/);
    await buttonB.emit('click'); await settle();
    const poll=[...timers.values()].find(timer=>timer.delay===10000);
    live={schema_version:'fortgym.watch-live/v1',status:'running',run_id:'current',model:'Astra',
      observed_at_unix:1000,fresh_for_seconds:30,frame:{...frame(99),captured_at_unix:999,action_status:'chosen_not_execution_verified'}};
    await poll.fn();
    assert.equal(element('title').textContent,'b'); // A chosen replay isn't hijacked.
    assert.equal(element('live').hidden,false);
    await element('live').emit('click');
    assert.match(element('badge').textContent,/LIVE/);
    assert.equal(element('recovery').hidden,true);
    assert.equal(element('prior').hidden,true);
    assert.match(element('execution').textContent,/does not yet verify/);
    live.frame={...live.frame,decision:100}; await poll.fn();
    assert.equal(element('decision').textContent,'Decision 100');
    await element('prev').emit('click');
    assert.equal(element('decision').textContent,'Decision 99');
    await poll.fn();
    assert.equal(element('decision').textContent,'Decision 99'); // Rewind remains paused.
    now=1031000;
    [...timers.values()].find(timer=>timer.delay===1000).fn();
    assert.equal(element('badge').textContent,'RECOVERED RUN');
    assert.equal(element('recovery').hidden,false);
    assert.equal(element('live').hidden,true);
    assert.match(element('connection').textContent,/expired/);
    assert.ok(requests.every(url=>url.startsWith('/static/recordings/') || url.startsWith('/static/live/watch-active.json?') || url==='/public/watch-active'));
  } finally {
    globalThis.document=original.document;globalThis.fetch=original.fetch;
    globalThis.setInterval=original.setInterval;globalThis.clearInterval=original.clearInterval;Date.now=original.now;
  }
});

test('a recording deep link opens the chosen model without a live feed taking over', async () => {
  const catalog = JSON.parse(fs.readFileSync('web/static/recordings/catalog.json')).recordings;
  for (const item of catalog)
    assert.deepEqual(initialRecording(catalog,'?recording='+item.id),{id:item.id,explicit:true});
  for (const search of ['', '?recording=missing', '?recording=../../private'])
    assert.deepEqual(initialRecording(catalog,search),{id:catalog[0].id,explicit:false});
  const originals = Object.fromEntries(['document','fetch','location','setInterval','clearInterval'].map(key=>[key,globalThis[key]]));
  const elements = new Map();
  for (const match of fs.readFileSync('web/landing.html','utf8').matchAll(/id="(watch-[^"]+)"/g))
    elements.set(match[1],new Element(match[1]));
  const requests=[];
  try {
    globalThis.location={search:'?recording=terra-65-128'};
    globalThis.document={hidden:false,getElementById:id=>elements.get(id),createElement:tag=>new Element(tag),addEventListener(){}};
    globalThis.setInterval=()=>1; globalThis.clearInterval=()=>{};
    globalThis.fetch=async url=>{
      requests.push(url);
      const data=url.includes('watch-active')
        ? {schema_version:'fortgym.watch-live/v1',status:'running',run_id:'live',model:'Live model',
            observed_at_unix:Math.floor(Date.now()/1000),fresh_for_seconds:30,
            frame:{...frame(99),captured_at_unix:Math.floor(Date.now()/1000),action_status:'chosen_not_execution_verified'}}
        : JSON.parse(fs.readFileSync('web'+url));
      return {ok:true,json:async()=>data};
    };
    await import('../web/static/home-watch.mjs?test=deep-link');
    for(let n=0;n<10;n++) await new Promise(resolve=>setImmediate(resolve));
    assert.equal(elements.get('watch-title').textContent,'Terra · keyboard');
    assert.equal(elements.get('watch-decision').textContent,'Decision 65 / 128');
    assert.equal(elements.get('watch-badge').textContent,'RECORDED RUN');
    assert.equal(elements.get('watch-live').hidden,false);
    assert.ok(requests.includes('/static/recordings/terra-65-128.json'));
    assert.ok(!requests.includes('/static/recordings/astra-97-256.json'));
  } finally { Object.assign(globalThis,originals); }
});

test('Year-Two replay displays its endpoint and hides it for other recordings', async () => {
  const originals = Object.fromEntries(['document','fetch','location','setInterval','clearInterval'].map(key=>[key,globalThis[key]]));
  const elements = new Map();
  for(const match of fs.readFileSync('web/landing.html','utf8').matchAll(/id="(watch-[^"]+)"/g))
    elements.set(match[1],new Element(match[1]));
  const get = id => elements.get('watch-'+id);
  const settle=async()=>{for(let n=0;n<10;n++)await new Promise(resolve=>setImmediate(resolve));};
  try {
    globalThis.location={search:'?recording=astra-year-two-257-416'};
    globalThis.document={hidden:false,getElementById:id=>elements.get(id),createElement:tag=>new Element(tag),addEventListener(){}};
    globalThis.setInterval=()=>1; globalThis.clearInterval=()=>{};
    globalThis.fetch=async url=>({ok:true,json:async()=>url.includes('watch-active')
      ? {schema_version:'fortgym.watch-live/v1',status:'not_connected'}
      : JSON.parse(fs.readFileSync('web'+url))});
    await import('../web/static/home-watch.mjs?test=year-two'); await settle();
    assert.equal(get('decision').textContent,'Decision 257 / 416');
    assert.equal(get('outcome').hidden,false);
    assert.match(get('outcome-summary').textContent,/Saved checkpoint 416 was verified/);
    assert.match(get('recovery').textContent,/Earlier save loss: 32 decisions/);
    assert.equal(get('result').href,yearTwo().campaign.result_url);
    assert.equal(get('reload').href,yearTwo().campaign.reload_url);
    get('range').value='159'; await get('range').emit('input');
    assert.equal(get('decision').textContent,'Decision 416 / 416');
    assert.equal(get('population').textContent,'13');
    assert.match(get('boundary').textContent,/saved checkpoint 416/);
    await get('prev').emit('click');
    assert.equal(get('decision').textContent,'Decision 415 / 416');
    await get('runs').children.find(node=>node.dataset.recording==='astra-recovery-225-256').emit('click');
    await settle();
    assert.equal(get('outcome').hidden,true);
    assert.equal(get('prior').href,'/?recording=astra-97-256#watch-root');
    assert.match(get('recovery').textContent,/All 288 model responses/);
  } finally { Object.assign(globalThis,originals); }
});

for (const model of ['astra', 'terra']) test(model+' matched first run scrubs all audited frames', async () => {
  const id=model+'-matched-r1-1-64';
  const recording=JSON.parse(fs.readFileSync('web/static/recordings/'+id+'.json'));
  const originals=Object.fromEntries(['document','fetch','location','setInterval','clearInterval'].map(key=>[key,globalThis[key]]));
  const elements=new Map();
  for(const match of fs.readFileSync('web/landing.html','utf8').matchAll(/id="(watch-[^"]+)"/g))
    elements.set(match[1],new Element(match[1]));
  const get=id=>elements.get('watch-'+id);
  try {
    globalThis.location={search:'?recording='+id};
    globalThis.document={hidden:false,getElementById:id=>elements.get(id),createElement:tag=>new Element(tag),addEventListener(){}};
    globalThis.setInterval=()=>1;globalThis.clearInterval=()=>{};
    globalThis.fetch=async url=>({ok:true,json:async()=>url.includes('watch-active')
      ? {schema_version:'fortgym.watch-live/v1',status:'not_connected'}
      : JSON.parse(fs.readFileSync('web'+url))});
    await import('../web/static/home-watch.mjs?test=matched-first-'+model);
    for(let n=0;n<10;n++) await new Promise(resolve=>setImmediate(resolve));
    assert.equal(get('title').textContent,recording.title);
    assert.equal(get('decision').textContent,'Decision 1 / 64');
    assert.equal(get('outcome').hidden,true);
    for(const index of [15,31,63]) {
      get('range').value=String(index);await get('range').emit('input');
      assert.equal(get('decision').textContent,'Decision '+(index+1)+' / 64');
      assert.equal(get('intent').textContent,recording.frames[index].action.intent);
      assert.equal(get('population').textContent,'7');
      assert.deepEqual(get('keys').children.map(key=>key.textContent),
        recording.frames[index].action.keys.map(key=>key===' '?'SPACE':key));
      assert.match(get('boundary').textContent,/saved checkpoint 64/);
    }
    assert.equal(get('next').disabled,true);
    await get('prev').emit('click');
    assert.equal(get('decision').textContent,'Decision 63 / 64');
  } finally {Object.assign(globalThis,originals);}
});

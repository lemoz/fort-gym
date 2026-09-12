import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {validateComparison, renderComparison, bindComparison, comparisonPath} from '../web/static/displayed-key-comparison.mjs';

const source = JSON.parse(fs.readFileSync('web/static/displayed-key-comparison.json'));
const continued = JSON.parse(fs.readFileSync('web/static/displayed-key-comparison-128.json'));
function document() {
  const element = tag => ({tag,children:[],dataset:{},textContent:'',attributes:{},
    append(...items){this.children.push(...items);},
    replaceChildren(...items){this.children=items;},setAttribute(k,v){this.attributes[k]=v;}});
  const nodes = Object.fromEntries(['matched-table','matched-summary','matched-plan','matched-download'].map(id=>[id,element('div')]));
  return {nodes,createElement:element,getElementById:id=>nodes[id]};
}
const text = node => [node.textContent,...node.children.map(text)].join(' ');
test('actual published result retains all six attempts without replacing blanks with zero',async()=>{
  assert.equal(validateComparison(source).recorded_attempts,6);
  const doc=document();
  await renderComparison(doc,async url=>{
    assert.equal(url,'/static/displayed-key-comparison.json'); return {ok:true,json:async()=>source};
  });
  assert.equal(doc.nodes['matched-summary'].textContent,'6 of 6 reviewed results published · 64-decision budget');
  const table=doc.nodes['matched-table'].children[0].children[0], rows=table.children[2].children;
  assert.equal(rows.length,6);
  assert.match(text(rows[0]),/Sol · 1 Saved 64 2,900 7 \/ 0 0 \/ 0 \/ 0 50 \/ 60 1,258,321/);
  assert.match(text(rows[1]),/Terra · 1 Saved 64 4,200 7 \/ 0 0 \/ 0 \/ 0 51 \/ 60 1,589,877/);
  assert.match(text(rows[2]),/Astra · 1 Saved 64 23,000 7 \/ 0 7 \/ 2 \/ 1 50 \/ 55 1,671,491/);
  assert.match(text(rows[3]),/Terra · 2 Saved 64 0 7 \/ 0 0 \/ 0 \/ 0 50 \/ 60 1,186,821/);
  assert.match(text(rows[4]),/Sol · 2 Saved 64 10,400 7 \/ 0 0 \/ 0 \/ 0 50 \/ 60 1,221,506/);
  assert.match(text(rows[5]),/Astra · 2 Saved 64 9,200 7 \/ 0 0 \/ 3 \/ 0 50 \/ 60 1,549,386/);
  assert.equal(rows[0].children.at(-1).children[1].href,'/?recording=sol-matched-r1-1-64#watch-root');
  assert.equal(rows[1].children.at(-1).children[1].href,'/?recording=terra-matched-r1-1-64#watch-root');
  assert.equal(rows[2].children.at(-1).children[1].href,'/?recording=astra-matched-r1-1-64#watch-root');
  assert.equal(rows[3].children.at(-1).children[1].href,'/?recording=terra-matched-r2-1-64#watch-root');
  assert.equal(rows[4].children.at(-1).children[1].href,'/?recording=sol-matched-r2-1-64#watch-root');
  assert.equal(rows[5].children.at(-1).children[1].href,'/?recording=astra-matched-r2-1-64#watch-root');
  assert.equal(doc.nodes['matched-plan'].href,source.plan_url);
});
for(const mutate of [
  data=>data.trials.push(data.trials[0]), data=>data.trials[1]=data.trials[0],
  data=>data.recorded_attempts=2, data=>data.strong_ranking_supported=true,
  data=>data.trials[0].evidence_url='javascript:alert(1)', data=>data.plan_url='https://evil.example/source.json',
  data=>data.trials[0].result.responses=63, data=>data.trials[0].result.vm_teardown_verified=false,
  data=>data.trials[0].result.checkpoint.metrics.population=-1,
  data=>data.trials[0].result.checkpoint.saved_elapsed_ticks=null,
  data=>data.trials[0].result.returned_tokens=null, data=>data.comparison_boundary=128,
]) test('invalid or mismatched reports are not rendered: '+mutate,()=>{
  const data=structuredClone(source); mutate(data); assert.throws(()=>validateComparison(data));
});
for(const status of ['budget_limited_pause','infrastructure_failure','gameplay_collapse'])
  test('partial outcomes preserve unknown measurements: '+status,async()=>{
    const data=structuredClone(source), result=data.trials[0].result;
    Object.assign(result,{status,responses:10,checkpoint:null,returned_tokens:null});
    const doc=document(); await renderComparison(doc,async()=>({ok:true,json:async()=>data}));
    assert.match(text(doc.nodes['matched-table']),/10 — — — — —/);
    const first=doc.nodes['matched-table'].children[0].children[0].children[2].children[0];
    assert.doesNotMatch(text(first),/Saved 64/);
  });
test('unavailable data leaves an explicit error instead of fabricated results',async()=>{
  const doc=document(); await renderComparison(doc,async()=>{throw Error('offline');});
  assert.equal(doc.nodes['matched-table'].children.length,0);
  assert.match(doc.nodes['matched-summary'].textContent,/temporarily unavailable/);
});

test('128 budget shows an infrastructure failure at its original 64-response save',async()=>{
  const doc=document();
  await renderComparison(doc,async url=>{
    assert.equal(url,'/static/displayed-key-comparison-128.json');
    return {ok:true,json:async()=>continued};
  },128);
  assert.equal(doc.nodes['matched-summary'].textContent,'3 of 6 reviewed results published · 128-decision budget');
  assert.equal(doc.nodes['matched-download'].href,'/static/displayed-key-comparison-128.json');
  const rows=doc.nodes['matched-table'].children[0].children[0].children[2].children;
  assert.match(text(rows[0]),/Sol · 1 Infrastructure failure 64 2,900 7 \/ 0/);
  assert.doesNotMatch(text(rows[0]),/Saved 128|Replay/);
  assert.match(text(rows[1]),/Terra · 1 Saved 128 120,200 15 \/ 0/);
  assert.ok(rows[1].children.at(-1).children.some(link=>link.href==='/?recording=terra-matched-r1-65-128#watch-root'));
  assert.match(text(rows[2]),/Astra · 1 Saved 128 55,700 7 \/ 0 8 \/ 3 \/ 2 61 \/ 83 4,123,021/);
  assert.ok(rows[2].children.at(-1).children.some(link=>link.href==='/?recording=astra-matched-r1-65-128#watch-root'));
  for(const row of rows.slice(3)) {
    assert.match(text(row),/No published result/);
    assert.equal(row.children[2].textContent,'—');
  }
});

test('undeclared budgets and cross-budget payloads cannot be rendered',()=>{
  for(const value of [0,65,127,256,'64',true,null]) assert.throws(()=>comparisonPath(value));
  assert.throws(()=>validateComparison(source,128));
  assert.throws(()=>validateComparison(continued,64));
  const bad=structuredClone(continued);
  bad.trials[0].result.checkpoint.next_step=65;
  assert.throws(()=>validateComparison(bad,128));
});

test('unknown response counts stay unknown for an infrastructure failure',async()=>{
  const data=structuredClone(continued), result=data.trials[0].result;
  Object.assign(result,{responses:null,returned_tokens:null,checkpoint:null});
  const doc=document();
  await renderComparison(doc,async()=>({ok:true,json:async()=>data}),128);
  assert.match(text(doc.nodes['matched-table']),/Infrastructure failure — — — — — —/);
});

test('budget control changes the report and download without duplicate handlers',async()=>{
  const doc=document(), handlers=[], calls=[];
  doc.nodes['matched-boundary']={value:'64',dataset:{},addEventListener(event,fn){assert.equal(event,'change');handlers.push(fn);}};
  const request=async url=>{calls.push(url);return {ok:true,json:async()=>url.includes('-128')?continued:source};};
  await bindComparison(doc,request);
  await bindComparison(doc,request);
  assert.equal(handlers.length,1);
  doc.nodes['matched-boundary'].value='128'; await handlers[0]();
  assert.equal(calls.at(-1),'/static/displayed-key-comparison-128.json');
  assert.match(doc.nodes['matched-summary'].textContent,/128-decision budget/);
  doc.nodes['matched-boundary'].value='64'; await handlers[0]();
  assert.equal(doc.nodes['matched-download'].href,'/static/displayed-key-comparison.json');
  assert.match(doc.nodes['matched-summary'].textContent,/6 of 6.*64-decision budget/);
});

for(const oldFails of [false,true]) test('a stale budget request cannot replace newer results: '+oldFails,async()=>{
  const doc=document(); let resolveOld,rejectOld,oldSignal;
  const older=renderComparison(doc,(_url,options)=>{
    oldSignal=options.signal; return new Promise((resolve,reject)=>{resolveOld=resolve;rejectOld=reject;});
  });
  await renderComparison(doc,async()=>({ok:true,json:async()=>continued}),128);
  assert.equal(oldSignal.aborted,true);
  if(oldFails) rejectOld(Error('old request failed'));
  else resolveOld({ok:true,json:async()=>source});
  await older;
  assert.match(doc.nodes['matched-summary'].textContent,/3 of 6.*128-decision budget/);
  assert.equal(doc.nodes['matched-download'].href,'/static/displayed-key-comparison-128.json');
  assert.equal(doc.nodes['matched-table'].attributes['aria-busy'],'false');
});

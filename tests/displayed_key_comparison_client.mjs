import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {validateComparison, renderComparison} from '../web/static/displayed-key-comparison.mjs';

const source = JSON.parse(fs.readFileSync('web/static/displayed-key-comparison.json'));
function document() {
  const element = tag => ({tag,children:[],dataset:{},textContent:'',attributes:{},
    append(...items){this.children.push(...items);},
    replaceChildren(...items){this.children=items;},setAttribute(k,v){this.attributes[k]=v;}});
  const nodes = Object.fromEntries(['matched-table','matched-summary','matched-plan'].map(id=>[id,element('div')]));
  return {nodes,createElement:element,getElementById:id=>nodes[id]};
}
const text = node => [node.textContent,...node.children.map(text)].join(' ');
test('actual published result retains all six attempts without replacing blanks with zero',async()=>{
  assert.equal(validateComparison(source).recorded_attempts,1);
  const doc=document();
  await renderComparison(doc,async url=>{
    assert.equal(url,'/static/displayed-key-comparison.json'); return {ok:true,json:async()=>source};
  });
  assert.equal(doc.nodes['matched-summary'].textContent,'1 of 6 reviewed results published · first 64 decisions');
  const table=doc.nodes['matched-table'].children[0].children[0], rows=table.children[2].children;
  assert.equal(rows.length,6);
  assert.match(text(rows[0]),/Sol · 1 Saved 64 2,900 7 \/ 0 0 \/ 0 \/ 0 50 \/ 60 1,258,321/);
  for(const row of rows.slice(1)) { assert.match(text(row),/No published result/); assert.equal(row.children[2].textContent,'—'); }
  assert.equal(rows[0].children.at(-1).children[1].href,'/?recording=sol-matched-r1-1-64#watch-root');
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
    assert.doesNotMatch(text(doc.nodes['matched-table']),/Saved 64/);
  });
test('unavailable data leaves an explicit error instead of fabricated results',async()=>{
  const doc=document(); await renderComparison(doc,async()=>{throw Error('offline');});
  assert.equal(doc.nodes['matched-table'].children.length,0);
  assert.match(doc.nodes['matched-summary'].textContent,/temporarily unavailable/);
});

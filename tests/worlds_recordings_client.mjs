import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {loadRecordingPreviews} from '../web/static/worlds-recordings.mjs';
import {renderCapturedScreen} from '../web/static/home-watch-model.mjs';

const html = fs.readFileSync('web/worlds.html','utf8');
const previews = JSON.parse(fs.readFileSync('web/static/recordings/previews.json'));
function gallery() {
  const cards = previews.recordings.map(row => {
    const label={textContent:''}, calls=[];
    const canvas={getContext:()=>({fillRect:(...args)=>calls.push(args),fillText(){}}),setAttribute(){}};
    return {dataset:{recordingPreview:row.id},label,calls,
      querySelector:selector=>selector==='canvas'?canvas:label};
  });
  return {cards,querySelectorAll:()=>cards};
}
test('gallery renders all real captured previews with the shared column-major renderer', async () => {
  const doc = gallery(), requests=[];
  await loadRecordingPreviews(doc,async url=>{
    requests.push(url); return {ok:true,json:async()=>previews};
  });
  assert.deepEqual(requests,['/static/recordings/previews.json']);
  doc.cards.forEach((card,index)=>{
    assert.equal(card.calls.length,4800);
    assert.match(card.label.textContent,new RegExp('decision '+previews.recordings[index].decision));
    assert.deepEqual(card.calls.slice(0,2),[[0,0,10,16],[0,16,10,16]]);
  });
});
test('one broken preview does not blank other cards, and fetch failure leaves replay links available', async () => {
  const doc=gallery(), broken=structuredClone(previews);
  broken.recordings[0].screen.runs=[];
  await loadRecordingPreviews(doc,async()=>({ok:true,json:async()=>broken}));
  assert.match(doc.cards[0].label.textContent,/Preview unavailable/);
  assert.match(doc.cards[1].label.textContent,/Captured screen/);
  await loadRecordingPreviews(doc,async()=>{throw Error('offline');});
  for (const card of doc.cards) {
    assert.match(card.label.textContent,/open the replay below/);
    assert.ok(html.includes('href="/?recording='+card.dataset.recordingPreview+'#watch-root"'));
  }
  assert.throws(()=>renderCapturedScreen({getContext:()=>null},previews.recordings[0].screen,97));
});
for (const failure of [false,true]) {
  test('empty or unavailable legacy registry cannot replace the recent recordings: '+failure, async () => {
    const nodes=new Map();
    for (const match of html.matchAll(/id="([^"]+)"/g))
      nodes.set(match[1],{textContent:'',innerHTML:'',hidden:false,value:'',addEventListener(){}});
    nodes.get('worlds-summary').textContent='3 recordings · 288 captured decisions · Astra, Sol and Terra';
    const FL={initShell(){},fetchJson:async()=>{
      if (failure) throw Error('registry offline');
      return {items:[],total:0,offset:0};
    }};
    const context={window:{FortLabs:FL,location:{search:''},addEventListener(){}},
      document:{getElementById:id=>nodes.get(id)},URLSearchParams};
    const script=[...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].at(-1)[1];
    vm.runInNewContext(script,context);
    for(let n=0;n<10;n++) await new Promise(resolve=>setImmediate(resolve));
    assert.match(nodes.get('worlds-summary').textContent,/3 recordings/);
    assert.equal(nodes.get('featured-world').hidden,true);
    assert.match(nodes.get('world-grid').innerHTML,/recordings above/);
    assert.equal(nodes.get('recent-recordings').innerHTML,''); // Registry code did not touch this node.
  });
}

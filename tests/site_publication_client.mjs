import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {renderPublishedRecordings, validateCatalog} from '../web/static/published-recordings.mjs';

const catalog=JSON.parse(fs.readFileSync('web/static/recordings/catalog.json'));
const previews=JSON.parse(fs.readFileSync('web/static/recordings/previews.json'));
const manifest=JSON.parse(fs.readFileSync('web/static/findings-v1.json'));
class Element {
  constructor(tag='div') { this.tag=tag; this.children=[]; this.textContent=''; this.innerHTML=''; this.attributes={}; this.fills=0; }
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this.children=items; }
  setAttribute(key,value) { this.attributes[key]=value; }
  getContext() { return {fillRect:()=>this.fills++,fillText(){}}; }
}
function page(name) {
  const html=fs.readFileSync('web/'+name+'.html','utf8'), nodes=new Map();
  for(const match of html.matchAll(/id="([^"]+)"/g))nodes.set(match[1],new Element());
  const list=new Element(); nodes.set('published-list',list);
  const doc={createElement:tag=>new Element(tag),getElementById:id=>nodes.get(id),
    querySelectorAll:()=>[list]};
  return {html,nodes,doc,list};
}
const all = element => [element,...element.children.flatMap(all)];
const text = element => all(element).map(node=>node.textContent).join(' ');
const settle=async()=>{for(let n=0;n<10;n++)await new Promise(resolve=>setImmediate(resolve));};

test('published metadata is bounded and matches every immutable recording',()=>{
  assert.equal(validateCatalog(catalog).length,8);
  for(const row of catalog.recordings) {
    const rec=JSON.parse(fs.readFileSync('web/static/recordings/'+row.id+'.json'));
    for(const key of ['model','control_profile','first_decision','last_decision','saved_through_decision','recording_status'])
      assert.equal(row[key],rec[key]);
    assert.equal(row.frame_count,rec.frames.length);
  }
  for(const mutation of [
    row=>{row.id='../private';},row=>{row.frame_count=0;},
    row=>{row.saved_through_decision=row.last_decision+1;},row=>{row.last_decision='256';},
    row=>{row.recovery.total_responses=256;},row=>{row.recovery.uninterrupted_campaign=true;}
  ]) {
    const bad=structuredClone(catalog);mutation(bad.recordings.find(row=>row.recovery));
    assert.throws(()=>validateCatalog(bad));
  }
});
for(const name of ['landing','results']) {
  test(name+' shows actual recordings independently of legacy APIs',async()=>{
    const {doc,list,nodes}=page(name),requests=[];
    await renderPublishedRecordings(doc,async url=>{
      requests.push(url);return {ok:true,json:async()=>url.endsWith('catalog.json')?catalog:previews};
    });
    assert.deepEqual(requests,['/static/recordings/catalog.json','/static/recordings/previews.json']);
    assert.equal(list.children.length,8);
    for(const row of catalog.recordings)assert.ok(all(list).some(el=>el.href==='/?recording='+row.id+'#watch-root'));
    assert.equal(all(list).filter(el=>el.tag==='canvas').reduce((sum,el)=>sum+el.fills,0),38400);
    assert.match(text(list),/unsaved tail included/);
    assert.doesNotMatch(text(list),/Loading/);
    if(name==='landing') {
      assert.equal(nodes.get('latest-model').textContent,'gpt-6-astra · matched trial 1');
      assert.equal(nodes.get('latest-save').textContent,'64');
      assert.equal(nodes.get('latest-ranking').textContent,'Not compared');
      assert.match(nodes.get('story-source').textContent,/gpt-5.6-terra/);
      assert.match(nodes.get('reason-source').textContent,/gpt-5.6-sol/);
    }
  });
}
test('catalog and preview failure states retain routes and never strand Latest on Loading',async()=>{
  const {doc,list,nodes}=page('landing');
  await renderPublishedRecordings(doc,async()=>{throw Error('offline');});
  assert.equal(nodes.get('latest-model').textContent,'Recordings unavailable');
  assert.ok(all(list).some(el=>el.href==='/worlds'));
  await renderPublishedRecordings(doc,async url=>{
    if(url.endsWith('previews.json'))throw Error('offline');
    return {ok:true,json:async()=>catalog};
  });
  assert.equal(list.children.length,8);
  assert.match(text(list),/Preview unavailable/);
  assert.ok(all(list).some(el=>el.href==='/?recording=terra-65-128#watch-root'));
});
function runInline({html,nodes},fetchJson) {
  const FL={initShell(){},fetchJson,escapeHtml:value=>String(value??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;'),
    formatNumber:value=>String(value),renderUnavailable(){},renderScreenText(){},
    loadRunFrame:async()=>({status:'not_reported'})};
  const script=[...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].at(-1)[1];
  vm.runInNewContext(script,{window:{FortLabs:FL},document:{getElementById:id=>nodes.get(id)}});
}
for(const available of [false,true]) {
  test('historical findings only link replay records that resolve: '+available,async()=>{
    const view=page('findings');
    runInline(view,async url=>{
      if(url==='/static/findings-v1.json')return manifest;
      if(available && url.endsWith(manifest.evidence_runs[0].token))
        return {model:'Historical model',score:1,step:100};
      throw Error('404');
    });
    await settle();
    const finding=view.nodes.get('finding-list').innerHTML;
    const evidence=view.nodes.get('evidence-grid').innerHTML;
    const first=manifest.evidence_runs[0].token;
    for(const entry of manifest.evidence_runs) {
      if(available && entry.token===first) {
        assert.ok(evidence.includes('href="/r/'+first+'"'));
      } else {
        assert.ok(!evidence.includes('href="/r/'+entry.token+'"'));
        assert.ok(!finding.includes('href="/r/'+entry.token+'"'));
      }
    }
    assert.match(evidence,/Historical replay unavailable/);
    assert.match(evidence,/Read the historical report/);
    assert.match(view.nodes.get('findings-load-status').textContent,/Historical findings loaded/);
    if(!available)assert.match(view.nodes.get('lead-run-link').href,/github.com\/lemoz\/fort-gym\/blob\//);
  });
}
test('historical result outages or empty cohorts cannot take over current recordings',async()=>{
  for(const failure of [false,true]) {
    const view=page('results');
    runInline(view,async()=>{if(failure)throw Error('offline');return {comparison_groups:[],candidate_run_count:0,eligible_run_count:0};});
    await settle();
    assert.match(view.nodes.get('cohort-groups').innerHTML,failure?/unavailable/:/historical field/);
    assert.equal(view.nodes.get('published-list').innerHTML,'');
  }
});

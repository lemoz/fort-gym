// In-memory DOM unit test only; no browser interaction or visual acceptance.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.events = {}; this.hidden = true; }
  set textContent(value) { this.text = String(value); this.children = []; }
  get textContent() { return (this.text || '') + this.children.map(node => node.textContent).join(' '); }
  setAttribute(key, value) { this[key] = value; }
  appendChild(value) { this.children.push(value); }
  replaceChildren(...values) { this.text = ''; this.children = values; }
  addEventListener(key, value) { this.events[key] = value; }
}
const data = JSON.parse(fs.readFileSync(0, 'utf8')), nodes = {};
let fail = false;
vm.runInNewContext(fs.readFileSync(process.argv[2], 'utf8'), {
  document: {getElementById: id => nodes[id] ||= new Element('div'), createElement: tag => new Element(tag)},
  fetch: async url => { assert.equal(url, '/public/keyboard-binding-campaign'); return {ok: !fail, json: async () => data}; },
  AbortController, setTimeout, clearTimeout,
});
const settle = () => new Promise(resolve => setTimeout(resolve, 0));
function all(node, tag) { return (node.tag === tag ? [node] : []).concat(node.children.flatMap(child => all(child, tag))); }
(async () => {
  await settle();
  const content = nodes['binding-results-content'], refresh = nodes['refresh-binding-results'];
  assert.equal(content.hidden, false);
  const history = all(content, 'details').find(node => node.children[0]?.textContent === 'Save and reload history');
  const labels = all(history, 'p').map(node => node.textContent).filter(text => /^Decision [0-9]+: save verified/.test(text));
  assert.equal(labels.length, data.checkpoints.length);
  assert.match(labels[0], /separate fresh reload verified/);
  assert.match(labels[2], /continued-play reload verified/);
  assert.match(labels.at(-1), /following reload not yet verified/);
  assert.match(history.textContent, /SSH warning/);
  assert.equal(all(content, 'tbody')[0].children.length, data.responses);
  if (data.status === 'paused') {
    assert.equal(labels.filter(text => text.startsWith('Decision 128:')).length, 2);
    assert.match(history.textContent, /Pause checkpoint: no additional model decisions/);
  } else {
    assert.equal(labels.length, 8);
    assert.match(labels.at(-1), /Decision 256:/);
  }
  const rendered = content.textContent;
  fail = true;
  await refresh.events.click();
  assert.equal(content.textContent, rendered);
  assert.match(nodes['binding-results-status'].textContent, /last loaded recorded result remains/);
  fail = false;
  data.checkpoints[2].continuation_reload_url = 'javascript:alert(1)';
  data.checkpoints[2].reload_note = '<img src=x onerror=alert(1)>';
  await refresh.events.click();
  assert.equal(all(content, 'img').length, 0);
  assert.ok(content.textContent.includes('<img src=x onerror=alert(1)>'));
  assert.equal(all(content, 'a').find(node => node.textContent === 'Continued-play reload evidence').href, undefined);
})().catch(error => { console.error(error); process.exitCode = 1; });

// Lightweight DOM regression, not a browser screenshot or layout acceptance.
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
let fail = true;
vm.runInNewContext(fs.readFileSync(process.argv[2], 'utf8'), {
  document: {getElementById: id => nodes[id] ||= new Element('div'), createElement: tag => new Element(tag)},
  fetch: async url => { assert.equal(url, '/public/keyboard-binding-results'); return {ok: !fail, json: async () => data}; },
  AbortController, setTimeout, clearTimeout,
});
const settle = () => new Promise(resolve => setTimeout(resolve, 0));
function all(node, tag) { return (node.tag === tag ? [node] : []).concat(node.children.flatMap(child => all(child, tag))); }
(async () => {
  await settle();
  const content = nodes['binding-results-content'], status = nodes['binding-results-status'], refresh = nodes['refresh-binding-results'];
  assert.equal(content.hidden, true);
  assert.match(status.textContent, /could not be loaded/);
  assert.equal(refresh.disabled, false);
  fail = false;
  await refresh.events.click();
  assert.equal(content.hidden, false);
  assert.match(status.textContent, /Recorded result: 32 decisions complete and audited/);
  for (const text of ['785,690', '15,500', '2 / 0 / 1', '50 / 60', 'Unreported, not $0', 'blocking_native_menu', 'not proof that it succeeded']) {
    assert.ok(content.textContent.includes(text), text);
  }
  assert.equal(all(content, 'tbody')[0].children.length, 32);
  assert.equal(all(content, 'a').length, 3);
  assert.ok(all(content, 'a').every(link => link.href.startsWith('https://github.com/lemoz/fort-gym/blob/')));
  const last = all(content, 'tbody')[0].children.at(-1).textContent;
  assert.match(last, /32\./); assert.match(last, /15,500/); assert.match(last, /2 \/ 0 \/ 1/);
  const loadedText = content.textContent;
  fail = true;
  await refresh.events.click();
  assert.equal(content.textContent, loadedText);
  assert.match(status.textContent, /last loaded recorded result remains/);
  fail = false;
  data.result.saved_metrics.food_stock = null;
  data.result.timeline[0].model_intent = '<script>not executable</script>';
  data.result_url = 'javascript:alert(1)';
  await refresh.events.click();
  assert.match(content.textContent, /Unknown \/ 60/);
  assert.match(content.textContent, /<script>not executable<\/script>/);
  assert.equal(all(content, 'script').length, 0);
  assert.equal(all(content, 'a')[0].href, undefined);
  data.included_in_historical_cohort = true;
  await refresh.events.click();
  assert.match(status.textContent, /Refresh failed/);
})().catch(error => { console.error(error); process.exitCode = 1; });

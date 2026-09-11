// In-memory DOM unit test, not browser or layout acceptance.
const assert = require('node:assert/strict'), fs = require('node:fs'), vm = require('node:vm');
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.events = {}; this.hidden = true; }
  set textContent(value) { this.text = String(value); this.children = []; }
  get textContent() { return (this.text || '') + this.children.map(node => node.textContent).join(' '); }
  setAttribute(key, value) { this[key] = value; }
  appendChild(value) { this.children.push(value); }
  replaceChildren(...values) { this.text = ''; this.children = values; }
  addEventListener(key, value) { this.events[key] = value; }
}
const {data, mode} = JSON.parse(fs.readFileSync(0, 'utf8')), nodes = {};
vm.runInNewContext(fs.readFileSync(process.argv[2], 'utf8'), {
  document: {getElementById: id => nodes[id] ||= new Element('div'), createElement: tag => new Element(tag)},
  fetch: async () => ({ok: true, json: async () => data}), AbortController, setTimeout, clearTimeout,
});
const settle = () => new Promise(resolve => setTimeout(resolve, 0));
(async () => {
  await settle();
  const content = nodes['binding-results-content'], status = nodes['binding-results-status'];
  const refresh = nodes['refresh-binding-results'];
  assert.equal(content.hidden, false);
  assert.match(content.textContent, /latest-save breakdown does not describe earlier rows/);
  if (mode === 'trader') assert.match(content.textContent, /438 raw units; 395 trader-flagged; 43 without the trader flag/);
  if (mode === 'recorded') assert.match(content.textContent, /58 raw units; 0 trader-flagged; 58 without the trader flag/);
  if (mode === 'unavailable') assert.match(content.textContent, /Food trader breakdown: Unknown \(not recorded\)/);
  if (mode === 'incomplete') assert.match(content.textContent, /Food trader breakdown: Unknown \(incomplete measurement\)/);
  if (mode === 'legacy') {
    assert.match(content.textContent, /Trader breakdown unavailable for this record/);
    return;
  }
  assert.match(content.textContent, /Without the trader flag does not mean fortress-owned or reachable/);
  assert.match(content.textContent, /Trader share of drinks: Unknown \(not recorded\)/);
  const expected = content.textContent, valid = JSON.parse(JSON.stringify(data.stock_context));
  for (const mutate of [
    c => c.responses--,
    c => c.checkpoint_sha256 = '0'.repeat(64),
    c => c.ownership_and_accessibility_verified = true,
    c => c.production_or_sustainability_verified = true,
    c => c.drink.trader_flagged_units = 0,
    c => c.food.trader_flagged_units = -1,
    c => c.food.raw_units = 999,
    c => c.food.measurement_status = '<img src=x onerror=alert(1)>',
  ]) {
    data.stock_context = JSON.parse(JSON.stringify(valid));
    mutate(data.stock_context);
    await refresh.events.click();
    assert.match(status.textContent, /Refresh failed/);
    assert.equal(content.textContent, expected);
  }
})().catch(error => { console.error(error); process.exitCode = 1; });

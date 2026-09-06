// In-memory DOM/transport test doubles, not browser QA or live campaign evidence.
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const helpers = require(process.argv[2]);
for (const value of [null, undefined, false, true, '', ' ', [], {}, -1, NaN, Infinity]) {
  assert.equal(helpers.money(value), 'Unknown');
}
assert.equal(helpers.money('0.003462525'), '$0.003463');
assert.equal(helpers.money('3E-13'), '< $0.000001');
const localCost = charge => helpers.modelCost({cost_basis:'self_hosted_no_metered_provider', metered_provider_charge_usd:charge});
assert.equal(localCost('0'), '$0 model API · self-hosted');
assert.equal(localCost('0.000e-3'), '$0 model API · self-hosted');
for (const value of [null, undefined, false, true, 0, '', ' ', [], {}, '-1', '0.01', '1e-999', 'NaN']) {
  assert.equal(localCost(value), 'Model API charge unknown · self-hosted');
}
assert.equal(helpers.modelCost({reported_model_cost_usd:'0.25'}), '$0.250000');
assert.equal(helpers.number(null), 'Unknown');
assert.equal(helpers.number(0), '0');
assert.match(helpers.duration(403200), /1.000 years/);
assert.match(helpers.stateLabel({freshness: 'stale', lifecycle: 'running'}), /unknown/);
const separateCondition = {
  condition_id: 'local-native-qwen35-year-two-v1',
  code_revision: 'fad9d80c0a2e7aace8380b47b009db5edaf6bd2e',
  configuration_sha256: 'bd658141891e31d3e4f014ca92e484779a5330d74a75d9163ea97289d3819018'
};
assert.equal(helpers.configurationUrl(separateCondition),
  'https://github.com/lemoz/fort-gym/blob/d3a8bd8d5d4588d2c26b0d0201585577bf361edd/experiments/campaigns/local_native_qwen35_year_two_v1.json');
assert.equal(helpers.configurationUrl({...separateCondition, configuration_sha256: 'a'.repeat(64)}), null);
assert.equal(helpers.configurationUrl({...separateCondition, configuration_sha256: undefined}), null);
assert.equal(helpers.configurationUrl({...separateCondition, code_revision: 'javascript:alert(1)'}), null);
assert.equal(helpers.configurationUrl({...separateCondition, condition_id: 'unpublished-condition'}), null);
assert.equal(helpers.stateLabel({lifecycle: 'finished', segment_status: 'inference_output_limited_pause', failure_kind: 'none'}),
  'Paused at the model output limit');
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.events = {}; }
  set textContent(value) { this.text = String(value); }
  get textContent() { return (this.text || '') + this.children.map(x => x.textContent).join(' '); }
  append(value) { this.children.push(value); }
  replaceChildren() { this.children = []; }
  addEventListener(event, callback) { this.events[event] = callback; }
}
const elements = {}, events = {};
const document = {
  hidden: false,
  getElementById(id) { return elements[id] ||= new Element('div'); },
  createElement(tag) { return new Element(tag); },
  addEventListener(event, callback) { events[event] = callback; }
};
const data = JSON.parse(process.argv[3]);
const first = data.campaigns[0];
first.model = '<img src=x onerror=alert(1)>';
first.lifecycle = 'running'; first.freshness = 'stale';
first.elapsed_ticks = 403200; first.current_metrics.population = 0;
first.code_revision = 'javascript:alert(1)';
first.usage = {...first.usage, cost_basis:'self_hosted_no_metered_provider', metered_provider_charge_usd:'0', reported_model_cost_usd:null};
first.committed_steps = 18;
first.actions = {accepted:16, rejected:2, unknown:0, changed_command_after_rejection:0,
  path_cache_stale_rejections:2,
  by_type:{LABOR:{accepted:16, rejected:0, unknown:0}, BUILD:{accepted:0, rejected:2, unknown:0}}};
data.campaigns.push({...first, model:'second-model', campaign_id:'second',
  condition_id:'local-native-packed-comparison-v1', code_revision:'a'.repeat(40)});
data.campaigns.push({...first, model:'repair-model', campaign_id:'repair',
  condition_id:'local-native-harness-repair-v1', code_revision:'b'.repeat(40)});
data.campaigns.push({...first, model:'reference-model', campaign_id:'reference',
  condition_id:'local-native-designation-reference-v1', code_revision:'c'.repeat(40)});
let fail = false, malformed = false, requests = 0;
const fetch = async url => {
  assert.equal(url, '/public/campaign-feed'); requests++;
  return {ok: !fail, json: async () => malformed ? {...data, campaigns:[null]} : data};
};
vm.runInNewContext(fs.readFileSync(process.argv[2], 'utf8'), {
  document, fetch, setTimeout: () => 1, clearTimeout: () => {}
});
(async () => {
  await new Promise(setImmediate);
  assert.equal(elements['campaign-feed-content'].hidden, false);
  assert.equal(elements['campaign-feed-rows'].children.length, 4);
  let row = elements['campaign-feed-rows'].children[0];
  assert.equal(row.children[0].text, '<img src=x onerror=alert(1)>');
  assert.match(row.children[1].textContent, /current state unknown/);
  assert.match(row.children[2].textContent, /1.000 years/);
  assert.equal(row.children[3].textContent, '0');
  assert.match(row.children[6].textContent, /\$0 model API/);
  assert.match(row.children[6].textContent, /Operating costs unknown/);
  row.children[0].children[1].events.click();
  assert.match(elements['campaign-profile-detail'].textContent, /not assessed/);
  assert.match(elements['campaign-profile-detail'].textContent, /do not mean zero operating cost/);
  assert.match(elements['campaign-profile-detail'].textContent, /16 accepted commands; 2 rejected/);
  assert.match(elements['campaign-profile-detail'].textContent, /can be no-ops or queued work/);
  assert.match(elements['campaign-profile-detail'].textContent, /2 commands were blocked because the native pathfinding cache was not ready/);
  assert.doesNotMatch(elements['campaign-profile-detail'].textContent, /Exact reported cost:/);
  assert.equal(elements['campaign-profile-detail'].children.some(child => child.href?.startsWith('javascript:')), false);
  elements['campaign-condition-filter'].value = 'local-native-packed-comparison-v1';
  elements['campaign-condition-filter'].events.change();
  assert.equal(elements['campaign-feed-rows'].children.length, 1);
  assert.equal(elements['campaign-feed-rows'].children[0].children[0].text, 'second-model');
  elements['campaign-feed-rows'].children[0].children[0].children[1].events.click();
  assert.equal(elements['campaign-profile-detail'].children.find(child => child.href?.startsWith('https://github.com/')).href,
    `https://github.com/lemoz/fort-gym/blob/${'a'.repeat(40)}/experiments/campaigns/local_native_packed_comparison_v1.json`);
  elements['campaign-condition-filter'].value = 'local-native-harness-repair-v1';
  elements['campaign-condition-filter'].events.change();
  assert.equal(elements['campaign-feed-rows'].children.length, 1);
  elements['campaign-feed-rows'].children[0].children[0].children[1].events.click();
  assert.equal(elements['campaign-profile-detail'].children.find(child => child.href?.startsWith('https://github.com/')).href,
    `https://github.com/lemoz/fort-gym/blob/${'b'.repeat(40)}/experiments/campaigns/local_native_harness_repair_v1.json`);
  elements['campaign-condition-filter'].value = 'local-native-designation-reference-v1';
  elements['campaign-condition-filter'].events.change();
  assert.equal(elements['campaign-feed-rows'].children.length, 1);
  elements['campaign-feed-rows'].children[0].children[0].children[1].events.click();
  assert.equal(elements['campaign-profile-detail'].children.find(child => child.href?.startsWith('https://github.com/')).href,
    `https://github.com/lemoz/fort-gym/blob/${'c'.repeat(40)}/experiments/campaigns/local_native_designation_reference_v1.json`);
  elements['campaign-condition-filter'].value = 'local-native-packed-comparison-v1';
  elements['campaign-condition-filter'].events.change();
  elements['campaign-feed-rows'].children[0].children[0].children[1].events.click();
  fail = true;
  await elements['refresh-campaign-feed'].events.click();
  assert.match(elements['campaign-feed-status'].textContent, /current state is unknown/);
  assert.match(elements['campaign-feed-rows'].textContent, /Update unavailable/);
  assert.equal(elements['refresh-campaign-feed'].disabled, false);
  fail = false; malformed = true;
  await elements['refresh-campaign-feed'].events.click();
  assert.match(elements['campaign-feed-status'].textContent, /could not be loaded/);
  malformed = false;
  await events.visibilitychange();
  await new Promise(setImmediate);
  assert.equal(requests, 4);
  data.configured = false;
  data.campaigns[1].publication = 'versioned_snapshot';
  await elements['refresh-campaign-feed'].events.click();
  assert.equal(elements['campaign-feed-content'].hidden, false);
  assert.match(elements['campaign-feed-status'].textContent, /published terminal snapshots/);
  assert.match(elements['campaign-feed-status'].textContent, /Live campaign tracking is not connected/);
  assert.match(elements['campaign-profile-detail'].textContent, /recorded evidence, not a live worker/);
})().catch(error => { console.error(error); process.exitCode = 1; });

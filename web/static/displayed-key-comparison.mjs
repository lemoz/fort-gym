const SCHEMA = 'fortgym.public-displayed-key-comparison/v1';
const MODELS = {'gpt-5.6-sol': 'Sol', 'gpt-5.6-terra': 'Terra', 'gpt-6-astra': 'Astra'};
const STATUS = {saved: 'Saved', budget_limited_pause: 'Budget pause', infrastructure_failure: 'Infrastructure failure', gameplay_collapse: 'Gameplay collapse'};
const REPLAYS = {64: {
  'bindings-comparison-20260911-sol-r1': 'sol-matched-r1-1-64',
  'bindings-comparison-20260911-terra-r1': 'terra-matched-r1-1-64',
  'bindings-comparison-20260911-astra-r1': 'astra-matched-r1-1-64',
  'bindings-comparison-20260911-terra-r2': 'terra-matched-r2-1-64',
  'bindings-comparison-20260911-sol-r2': 'sol-matched-r2-1-64',
  'bindings-comparison-20260911-astra-r2': 'astra-matched-r2-1-64',
}, 128: {
  'bindings-comparison-20260911-terra-r1': 'terra-matched-r1-65-128',
  'bindings-comparison-20260911-astra-r1': 'astra-matched-r1-65-128',
  'bindings-comparison-20260911-terra-r2': 'terra-matched-r2-65-128',
}};
const activeRequests = new WeakMap();
const evidenceUrl = value => typeof value === 'string' && /^https:\/\/github\.com\/lemoz\/fort-gym\/blob\/[a-f0-9]{40}\/experiments\/[a-zA-Z0-9_./-]+\.json$/.test(value);
const number = value => value === null || (Number.isSafeInteger(value) && value >= 0);
const format = value => value === null || value === undefined ? '—' : value.toLocaleString('en-US');

export function comparisonPath(boundary) {
  if (![64,128].includes(boundary)) throw Error('Undeclared comparison boundary');
  return boundary === 64 ? '/static/displayed-key-comparison.json' : '/static/displayed-key-comparison-128.json';
}
export function validateComparison(data, boundary = 64) {
  comparisonPath(boundary);
  if (data?.schema_version !== SCHEMA || data.cohort_id !== 'bindings-comparison-20260911' ||
      data.comparison_boundary !== boundary || data.declared_attempts !== 6 || data.strong_ranking_supported !== false ||
      data.live_status_included !== false || !evidenceUrl(data.plan_url) ||
      !Array.isArray(data.trials) || data.trials.length !== 6) throw Error('Invalid experiment report');
  const identities = new Set();
  let recorded = 0;
  for (const row of data.trials) {
    if (!Object.hasOwn(MODELS,row.model) || ![1,2].includes(row.replicate) || row.reasoning_effort !== 'medium' ||
        row.campaign_id !== 'bindings-comparison-20260911-'+MODELS[row.model].toLowerCase()+'-r'+row.replicate ||
        identities.has(row.campaign_id)) throw Error('Invalid trial identity');
    identities.add(row.campaign_id);
    if (row.publication_state === 'no_published_result') {
      if (row.result !== null || row.evidence_url !== null) throw Error('Unpublished result has values');
      continue;
    }
    const result = row.result;
    if (row.publication_state !== 'recorded' || !result || !Object.hasOwn(STATUS,result.status) ||
        !evidenceUrl(row.evidence_url) || result.response_limit !== boundary || !number(result.responses) ||
        result.responses > boundary || !number(result.returned_tokens) ||
        !(result.reported_charge_usd === null || (Number.isFinite(result.reported_charge_usd) && result.reported_charge_usd >= 0)))
      throw Error('Invalid published result');
    if (result.checkpoint !== null) {
      const checkpoint = result.checkpoint;
      if (!checkpoint || !Number.isSafeInteger(checkpoint.next_step) || checkpoint.next_step < 0 ||
          result.responses === null || checkpoint.next_step > result.responses ||
          !number(checkpoint.saved_elapsed_ticks) || !checkpoint.metrics ||
          !Object.values(checkpoint.metrics).every(number)) throw Error('Invalid saved metrics');
    }
    if (result.status === 'saved' && (result.responses !== boundary || result.checkpoint?.next_step !== boundary ||
        result.checkpoint.saved_elapsed_ticks === null || result.returned_tokens === null ||
        result.native_teardown_verified !== true || result.vm_teardown_verified !== true)) throw Error('Incomplete saved result');
    if (Object.hasOwn(result,'storage_amendment')) {
      const note = result.storage_amendment;
      if (!note || note.schema_version !== 'fortgym.public-comparison-storage-note/v1' ||
          row.campaign_id !== 'bindings-comparison-20260911-astra-r2' || boundary !== 128 ||
          note.first_step !== 64 || note.target_next_step !== boundary ||
          note.disk_gib_before !== 32 || note.disk_gib_after !== 40 || note.other_conditions_unchanged !== true ||
          note.declaration_sha256 !== 'eeb3fa8b08234819247b4dec7ecf50fda9f137fd57cabe07d1426d968d15116e')
        throw Error('Invalid storage amendment');
    }
    recorded++;
  }
  if (recorded !== data.recorded_attempts) throw Error('Published count differs');
  return data;
}

function node(doc,tag,text) {
  const element = doc.createElement(tag);
  if (text !== undefined) element.textContent = text;
  return element;
}
export async function renderComparison(doc = document, request = fetch, boundary = 64) {
  const root = doc.getElementById('matched-table'), summary = doc.getElementById('matched-summary');
  if (!root || !summary) return;
  const path = comparisonPath(boundary);
  activeRequests.get(doc)?.abort();
  const controller = new AbortController(), timer = setTimeout(() => controller.abort(),10000);
  activeRequests.set(doc,controller);
  const current = () => activeRequests.get(doc) === controller;
  root.setAttribute('aria-busy','true');
  summary.textContent='Loading results for the '+boundary+'-decision budget…';
  const download = doc.getElementById('matched-download');
  if (download) download.href=path;
  try {
    const response = await request(path,{cache:'no-store',signal:controller.signal});
    if (!response.ok) throw Error('Report unavailable');
    const data = validateComparison(await response.json(),boundary);
    if (!current()) return;
    const table = node(doc,'table'); table.className = 'comparison-table';
    table.append(node(doc,'caption','Last verified saved state at the '+boundary+'-decision budget. Listed in declared attempt order, not rank.'));
    const head = node(doc,'thead'), headings = node(doc,'tr');
    for (const label of ['Model / attempt','Result','Decisions','Saved game ticks','Living / deaths','Beds / workshops / farms','Food / drinks','Returned tokens','Evidence']) {
      const cell = node(doc,'th',label); cell.setAttribute('scope','col'); headings.append(cell);
    }
    head.append(headings); table.append(head);
    const body = node(doc,'tbody');
    for (const row of data.trials) {
      const tr = node(doc,'tr'), result = row.result, checkpoint = result?.checkpoint, metrics = checkpoint?.metrics;
      tr.dataset.result = result?.status || 'unpublished';
      const name = node(doc,'th',MODELS[row.model]+' · '+row.replicate); name.setAttribute('scope','row'); tr.append(name);
      if (result?.storage_amendment) {
        const note = node(doc,'span','Storage: 32 → 40 GiB from decision 65');
        note.className='comparison-amendment'; name.append(note);
      }
      for (const value of [result ? STATUS[result.status] : 'No published result',
        result ? format(result.responses) : '—',format(checkpoint?.saved_elapsed_ticks),
        metrics ? format(metrics.population)+' / '+format(metrics.recorded_dead_citizens) : '—',
        metrics ? [metrics.completed_beds,metrics.completed_workshops,metrics.completed_farms].map(format).join(' / ') : '—',
        metrics ? format(metrics.food_stock)+' / '+format(metrics.drink_stock) : '—',format(result?.returned_tokens)]) tr.append(node(doc,'td',value));
      const links = node(doc,'td');
      if (row.evidence_url) { const link = node(doc,'a','Result'); link.href=row.evidence_url; links.append(link); }
      const replay = REPLAYS[boundary][row.campaign_id];
      if (result && replay) { const link = node(doc,'a','Replay'); link.href='/?recording='+replay+'#watch-root'; links.append(link); }
      if (!row.evidence_url) links.textContent='—';
      tr.append(links); body.append(tr);
    }
    table.append(body);
    const scroll = node(doc,'div'); scroll.className='comparison-scroll'; scroll.tabIndex=0;
    scroll.setAttribute('role','region'); scroll.setAttribute('aria-label','Matched experiment results, scroll horizontally for all measurements');
    scroll.append(table); root.replaceChildren(scroll);
    if (data.trials.some(row => row.result?.storage_amendment)) {
      const note = node(doc,'p','Astra attempt 2 had more disk capacity for decisions 65–128. Model, prompt, game controls, CPU and RAM were unchanged. Earlier infrastructure failures remain in the comparison.');
      note.className='comparison-amendment-note'; root.append(note);
    }
    summary.textContent=data.recorded_attempts+' of 6 reviewed results published · '+boundary+'-decision budget';
    doc.getElementById('matched-plan').href=data.plan_url;
  } catch (_) {
    if (!current()) return;
    root.replaceChildren(); summary.textContent='Experiment results are temporarily unavailable. The plan and recordings remain available below.';
  } finally {
    clearTimeout(timer);
    if (current()) root.setAttribute('aria-busy','false');
  }
}
export function bindComparison(doc = document, request = fetch) {
  const selector = doc.getElementById('matched-boundary');
  if (selector && selector.dataset.comparisonBound !== 'true') {
    selector.dataset.comparisonBound='true';
    selector.addEventListener('change',() => renderComparison(doc,request,Number(selector.value)));
  }
  return renderComparison(doc,request,selector ? Number(selector.value) : 64);
}
if (typeof document !== 'undefined' && document.getElementById('matched-table')) bindComparison();

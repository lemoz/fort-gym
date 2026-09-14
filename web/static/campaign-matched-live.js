/* Host receipts are provisional; the recorded table owns saved-result proof. */
(() => {
  'use strict';
  const status = document.getElementById('matched-live-status');
  const content = document.getElementById('matched-live-content');
  const refresh = document.getElementById('refresh-matched-live');
  if (!status || !content || !refresh) return;
  let latest = null;
  const number = n => Number.isSafeInteger(n) && n >= 0 ? n.toLocaleString('en-US') : 'Unknown';
  const el = (tag, text, className) => {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
  };
  function state(data) {
    if (data.status === 'not_connected') return data.status;
    return Date.now() / 1000 - data.observed_at_unix > 30 ? 'stale' : data.status;
  }
  function render(data) {
    if (data.schema_version !== 'fortgym.public-matched-live/v1' ||
        !['not_connected', 'controller_running', 'controller_stopped', 'stale'].includes(data.status)) throw new Error('Invalid live feed');
    if (data.status !== 'not_connected' &&
        (data.new_save_verified !== false || data.reported_charge_usd !== null ||
         data.fresh_for_seconds !== 30 || !Number.isSafeInteger(data.observed_at_unix) ||
         data.observed_at_unix > Date.now() / 1000 + 5 ||
         !['responses', 'returned_tokens', 'unsettled_claims', 'response_limit'].every(k => Number.isSafeInteger(data[k]) && data[k] >= 0))) throw new Error('Invalid live counters');
    const current = state(data);
    status.className = current === 'stale' ? 'campaign-error' : '';
    if (current === 'not_connected') {
      status.textContent = 'No live matched-trial observer is connected. Recorded results remain below.';
      content.hidden = true;
      return;
    }
    status.textContent = current === 'stale'
      ? 'Live observation is stale. Current controller and game status are unknown.'
      : current === 'controller_running'
        ? 'Run controller active. These observations are not a verified save.'
        : 'Run controller ended. See recorded results for the independent final audit.';
    const output = el('div'), facts = el('dl', undefined, 'campaign-save-facts');
    const add = (key, value) => {
      const group = el('div'); group.appendChild(el('dt', key)); group.appendChild(el('dd', value)); facts.appendChild(group);
    };
    add('Model / attempt', `${data.model} · ${number(data.replicate)} · ${data.reasoning_effort}`);
    add('Returned responses', `${number(data.responses)} / ${number(data.response_limit)}`);
    add('Returned tokens', number(data.returned_tokens));
    add('Unsettled dispatch claims', number(data.unsettled_claims));
    add('Observed elapsed ticks (lower bound)', number(data.observed_elapsed_ticks_lower_bound));
    add('VM data disk', `${number(data.data_disk_gib)} GiB`);
    output.appendChild(facts);
    output.appendChild(el('p', 'Independent start from the shared seed. No new save is verified by this feed. Game time comes from feedback in subsequent requests; the latest action may not be included.', 'campaign-note'));
    output.appendChild(el('p', 'Model charge is unreported, not $0. Unsettled claims may have used additional tokens. A running controller does not establish game health.', 'campaign-note'));
    if (data.teardown_reported !== null) output.appendChild(el('p', data.teardown_reported
      ? 'Controller reports VM teardown; independent verification is separate.'
      : 'Controller did not report a stopped VM.', 'campaign-note'));
    output.appendChild(el('p', `Last observed: ${new Date(data.observed_at_unix * 1000).toISOString()}. Trial: ${data.campaign_id}.`, 'campaign-note'));
    content.replaceChildren(output); content.hidden = false;
  }
  async function load() {
    if (refresh.disabled) return;
    refresh.disabled = true;
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 5000);
    try {
      const response = await fetch('/public/keyboard-cohort-active', {cache: 'no-store', signal: controller.signal});
      if (!response.ok) throw new Error('Unavailable');
      const value = await response.json(); render(value); latest = value;
    } catch (_) {
      if (latest) {
        render(latest);
        if (state(latest) !== 'stale') status.textContent = 'Refresh failed. Showing the last observation; it will expire after 30 seconds.';
      } else {
        status.textContent = 'Current trial status unavailable. No inference about the game can be made.';
        content.hidden = true;
      }
      status.className = 'campaign-error';
    } finally { clearTimeout(timer); refresh.disabled = false; }
  }
  refresh.addEventListener('click', load);
  setInterval(() => { if (latest && state(latest) === 'stale') render(latest); }, 1000);
  setInterval(() => { if (!document.hidden) load(); }, 15000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) load(); });
  load();
})();

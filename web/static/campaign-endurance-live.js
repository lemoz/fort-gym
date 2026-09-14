/* Saved baseline and provisional new work are intentionally separate. */
(() => {
  'use strict';
  const status = document.getElementById('endurance-live-status');
  const content = document.getElementById('endurance-live-content');
  const refresh = document.getElementById('refresh-endurance-live');
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
    if (data.schema_version !== 'fortgym.public-matched-endurance-live/v1' ||
        !['not_connected', 'controller_running', 'controller_stopped', 'stale'].includes(data.status)) throw new Error('Invalid continuation feed');
    if (data.status !== 'not_connected') {
      const counts = ['responses', 'returned_tokens', 'unsettled_claims', 'response_limit',
        'saved_elapsed_ticks_before_window', 'returned_tokens_before_window',
        'campaign_elapsed_ticks_lower_bound', 'campaign_returned_responses', 'campaign_returned_tokens'];
      if (data.new_save_verified !== false || data.source_checkpoint_verified !== true ||
          data.origin_kind !== 'saved_campaign_checkpoint' || data.reported_charge_usd !== null ||
          data.fresh_for_seconds !== 30 || data.start_decision !== 64 || data.end_decision !== 128 ||
          !Number.isSafeInteger(data.observed_at_unix) || data.observed_at_unix > Date.now() / 1000 + 5 ||
          !counts.every(k => Number.isSafeInteger(data[k]) && data[k] >= 0) ||
          data.responses + data.unsettled_claims > 64 || data.response_limit !== 64 ||
          (data.new_elapsed_ticks_lower_bound !== null && (!Number.isSafeInteger(data.new_elapsed_ticks_lower_bound) || data.new_elapsed_ticks_lower_bound < 0)) ||
          data.campaign_returned_responses !== 64 + data.responses ||
          data.campaign_returned_tokens !== data.returned_tokens_before_window + data.returned_tokens ||
          data.campaign_elapsed_ticks_lower_bound !== data.saved_elapsed_ticks_before_window + (data.new_elapsed_ticks_lower_bound || 0)) throw new Error('Invalid continuation counters');
    }
    const current = state(data);
    status.className = current === 'stale' ? 'campaign-error' : '';
    if (current === 'not_connected') {
      status.textContent = 'No 64-to-128 gameplay observer is connected. Verified saved results remain below.';
      content.hidden = true;
      return;
    }
    status.textContent = current === 'stale'
      ? 'Continuation observation is stale. Current game status is unknown.'
      : current === 'controller_running'
        ? '64-to-128 continuation active. New progress is not yet a verified save.'
        : 'Continuation controller ended. Its final save requires an independent audit.';
    const output = el('div'), facts = el('dl', undefined, 'campaign-save-facts');
    const add = (key, value) => {
      const group = el('div'); group.appendChild(el('dt', key)); group.appendChild(el('dd', value)); facts.appendChild(group);
    };
    add('Model / attempt', `${data.model} · ${number(data.replicate)} · ${data.reasoning_effort}`);
    add('Saved starting decision', number(data.start_decision));
    add('Saved elapsed ticks before this window', number(data.saved_elapsed_ticks_before_window));
    add('New returned responses', `${number(data.responses)} / ${number(data.response_limit)}`);
    add('New observed ticks (lower bound)', number(data.new_elapsed_ticks_lower_bound));
    add('Campaign ticks (saved + observed lower bound)', number(data.campaign_elapsed_ticks_lower_bound));
    add('New returned tokens', number(data.returned_tokens));
    add('Campaign returned tokens', number(data.campaign_returned_tokens));
    add('Unsettled dispatch claims', number(data.unsettled_claims));
    output.appendChild(facts);
    output.appendChild(el('p', 'Resumes this attempt’s own save and model memory. The starting checkpoint is verified; this live feed does not verify a new save. New game time comes from later feedback and can omit the latest action.', 'campaign-note'));
    output.appendChild(el('p', 'Model charge is unreported, not $0. Unsettled claims can include additional usage. Loading the save can change the open UI menu; no human gameplay navigation is added.', 'campaign-note'));
    if (/^https:\/\/github\.com\/lemoz\/fort-gym\/blob\/[a-f0-9]{40}\//.test(data.source_result_url || '')) {
      const link = el('a', 'Read this attempt’s saved starting result'); link.href = data.source_result_url; output.appendChild(link);
    }
    if (data.teardown_reported !== null) output.appendChild(el('p', data.teardown_reported
      ? 'Controller reports VM teardown; independent verification is separate.'
      : 'Controller did not report a stopped VM.', 'campaign-note'));
    output.appendChild(el('p', `Last observed: ${new Date(data.observed_at_unix * 1000).toISOString()}.`, 'campaign-note'));
    content.replaceChildren(output); content.hidden = false;
  }
  async function load() {
    if (refresh.disabled) return;
    refresh.disabled = true;
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 5000);
    try {
      const response = await fetch('/public/keyboard-cohort-endurance-active', {cache: 'no-store', signal: controller.signal});
      if (!response.ok) throw new Error('Unavailable');
      const value = await response.json(); render(value); latest = value;
    } catch (_) {
      if (latest) {
        render(latest);
        if (state(latest) !== 'stale') status.textContent = 'Refresh failed. Showing the last observation; it will expire after 30 seconds.';
      } else {
        status.textContent = 'Continuation status unavailable. Verified saved results remain below.'; content.hidden = true;
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

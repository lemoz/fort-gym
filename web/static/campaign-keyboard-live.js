(function () {
  'use strict';
  const schema = 'fortgym.public-keyboard-live/v1';
  const count = value => Number.isSafeInteger(value) && value >= 0 ? value.toLocaleString('en-US') : 'Unknown';
  function state(data, now = Date.now() / 1000) {
    if (!data || data.schema_version !== schema) throw new Error('Unsupported live status');
    if (data.status === 'not_connected') return 'not_connected';
    if (!['running', 'stopped', 'stale'].includes(data.status)
        || !Number.isSafeInteger(data.observed_at_unix) || data.observed_at_unix > now + 5
        || data.fresh_for_seconds !== 30 || data.new_save_verified !== false
        || data.reported_charge_usd !== null) throw new Error('Invalid live status');
    const saved = data.latest_verified_save;
    if (saved !== undefined) {
      if (!saved || !['checkpoint_cursor', 'elapsed_ticks', 'window_responses', 'campaign_tokens'].every(k => Number.isSafeInteger(saved[k]) && saved[k] >= 0)
          || !['report_sha256', 'checkpoint_sha256'].every(k => typeof saved[k] === 'string' && /^[a-f0-9]{64}$/.test(saved[k]))
          || saved.evidence_basis !== 'audited_save_metadata_and_next_worker_reload'
          || saved.full_inventory_and_trace_audit_complete !== false
          || saved.window_responses < 1 || saved.window_responses >= data.new_responses
          || saved.checkpoint_cursor !== data.saved_checkpoint_cursor + saved.window_responses
          || saved.elapsed_ticks < data.saved_elapsed_ticks
          || saved.campaign_tokens < data.campaign_tokens - data.new_tokens || saved.campaign_tokens > data.campaign_tokens
          || (data.ticks_since_verified_save_lower_bound !== null
            && (!Number.isSafeInteger(data.ticks_since_verified_save_lower_bound)
              || data.ticks_since_verified_save_lower_bound < 0
              || data.unsaved_ticks_lower_bound === null
              || data.ticks_since_verified_save_lower_bound > data.unsaved_ticks_lower_bound))) throw new Error('Invalid saved boundary');
    } else if (data.ticks_since_verified_save_lower_bound !== undefined) throw new Error('Missing saved boundary');
    return now - data.observed_at_unix > 30 ? 'stale' : data.status;
  }
  if (typeof module !== 'undefined') module.exports = { state, count };
  if (typeof document === 'undefined') return;
  const status = document.getElementById('keyboard-live-status');
  const content = document.getElementById('keyboard-live-content');
  const button = document.getElementById('refresh-keyboard-live');
  if (!status || !content || !button) return;
  let latest = null, renderedState = null, busy = false;
  function node(tag, text, parent) {
    const element = document.createElement(tag);
    element.textContent = text;
    parent.append(element);
    return element;
  }
  function render(data) {
    const current = state(data);
    renderedState = current;
    status.textContent = {
      not_connected: 'No live run connected. Recorded results remain below.',
      running: `${data.model} · ${data.reasoning_effort} · running`,
      stopped: 'Run controller stopped. Final outcome needs verification.',
      stale: 'Live feed is stale. Check recorded results below for any verified outcome.',
    }[current];
    status.className = current === 'stale' ? 'campaign-stale' : '';
    content.replaceChildren();
    content.hidden = current === 'not_connected';
    if (content.hidden) return;
    const facts = document.createElement('dl');
    facts.className = 'campaign-save-facts';
    content.append(facts);
    for (const [label, value] of [
      ['Saved when this window started', `${count(data.saved_elapsed_ticks)} ticks`],
      ['Responses this window', `${count(data.new_responses)} / ${count(data.window_response_limit)}`],
      ['New tokens', count(data.new_tokens)],
      ['Time reported this window', data.unsaved_ticks_lower_bound === null ? 'Unknown' : `At least ${count(data.unsaved_ticks_lower_bound)} ticks`],
      ...(data.latest_verified_save ? [
        ['Latest verified save and reload', `Checkpoint ${count(data.latest_verified_save.checkpoint_cursor)} · ${count(data.latest_verified_save.elapsed_ticks)} ticks`],
        ['Time reported since that save', data.ticks_since_verified_save_lower_bound === null ? 'Unknown' : `At least ${count(data.ticks_since_verified_save_lower_bound)} ticks`],
      ] : []),
    ]) {
      const item = document.createElement('div');
      facts.append(item); node('dt', label, item); node('dd', value, item);
    }
    node('p', data.latest_verified_save
      ? `This window started from checkpoint ${count(data.saved_checkpoint_cursor)}. Save metadata and the next worker’s reload are verified through checkpoint ${count(data.latest_verified_save.checkpoint_cursor)}. The full save-file and gameplay-trace audit is still pending. Later reported time is not yet verified as saved.`
      : `At the last live observation, this window’s starting save was checkpoint ${count(data.saved_checkpoint_cursor)}. Reported time comes from the model’s subsequent feedback, not a newly verified save. Check the recorded results below for later verification.`, content);
    node('p', `${count(data.campaign_responses)} campaign responses and ${count(data.campaign_tokens)} campaign tokens so far; ${count(data.all_attempt_tokens)} tokens including historical failed deliveries. Charges are unreported, not zero.`, content);
    node('p', `Last host observation: ${new Date(data.observed_at_unix * 1000).toISOString()}. Refreshes while this page is visible.`, content).className = 'campaign-note';
  }
  async function refresh() {
    if (busy || document.hidden) return;
    busy = true; button.disabled = true;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 5000);
    try {
      const response = await fetch('/public/keyboard-active', { cache: 'no-store', signal: controller.signal });
      if (!response.ok) throw new Error('Unavailable');
      const value = await response.json();
      render(value); latest = value;
    } catch (_) {
      latest = null; content.hidden = true; content.replaceChildren();
      status.className = 'campaign-stale';
      status.textContent = 'Live status unavailable. Recorded results remain below.';
    } finally {
      clearTimeout(timer); busy = false; button.disabled = false;
    }
  }
  button.addEventListener('click', refresh);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
  setInterval(() => {
    if (!document.hidden && latest && state(latest) !== renderedState) render(latest);
  }, 1000);
  setInterval(refresh, 15000);
  refresh();
}());

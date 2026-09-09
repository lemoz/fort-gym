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
      stale: 'Live status is stale. The run may still be active.',
    }[current];
    status.className = current === 'stale' ? 'campaign-stale' : '';
    content.replaceChildren();
    content.hidden = current === 'not_connected';
    if (content.hidden) return;
    const facts = document.createElement('dl');
    facts.className = 'campaign-save-facts';
    content.append(facts);
    for (const [label, value] of [
      ['Saved game time', `${count(data.saved_elapsed_ticks)} ticks`],
      ['Responses this window', `${count(data.new_responses)} / ${count(data.window_response_limit)}`],
      ['New tokens', count(data.new_tokens)],
      ['Unsaved time observed', data.unsaved_ticks_lower_bound === null ? 'Unknown' : `At least ${count(data.unsaved_ticks_lower_bound)} ticks`],
    ]) {
      const item = document.createElement('div');
      facts.append(item); node('dt', label, item); node('dd', value, item);
    }
    node('p', `Last verified save: checkpoint ${count(data.saved_checkpoint_cursor)}. In-progress time comes from the model’s subsequent feedback, not a newly verified save.`, content);
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

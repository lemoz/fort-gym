/* Audited saved windows, never a replacement for historical initial results. */
(() => {
  'use strict';
  const status = document.getElementById('continuation-records-status');
  const content = document.getElementById('continuation-records-content');
  const refresh = document.getElementById('refresh-continuation-records');
  if (!status || !content || !refresh) return;
  const number = value => Number.isSafeInteger(value) && value >= 0 ? value.toLocaleString('en-US') : 'Unknown';
  const el = (tag, text, className) => {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
  };
  const label = row => `${row.model} · attempt ${row.replicate}`;
  function link(text, url) {
    const node = el('a', text);
    if (/^https:\/\/github\.com\/lemoz\/fort-gym\/blob\/[a-f0-9]{40}\//.test(url || '')) node.href = url;
    return node;
  }
  function table(caption, headings) {
    const region = el('div', undefined, 'campaign-table-scroll');
    region.setAttribute('role', 'region'); region.setAttribute('aria-label', caption); region.setAttribute('tabindex', '0');
    const node = el('table', undefined, 'campaign-table'), head = el('thead'), tr = el('tr'), body = el('tbody');
    node.appendChild(el('caption', caption));
    headings.forEach(text => { const th = el('th', text); th.setAttribute('scope', 'col'); tr.appendChild(th); });
    head.appendChild(tr); node.appendChild(head); node.appendChild(body); region.appendChild(node);
    return {region, body};
  }
  function details(row) {
    const result = row.result, node = el('details', undefined, 'campaign-details');
    node.appendChild(el('summary', `${label(row)}: continuation decisions and saved evidence`));
    node.appendChild(el('p', `Resumed after ${number(result.start_decision)} saved responses from this attempt's own fortress and model memory. ${number(result.new_responses)} new responses; ${number(result.next_decision)} total responses now saved. Stop reason: ${result.stop_reason}.`, 'campaign-note'));
    node.appendChild(el('p', `Starting save freshly loaded: ${result.source_checkpoint_fresh_load_verified ? 'verified' : 'not verified'}. New checkpoint: ${result.checkpoint_verified ? 'verified' : 'not verified'}. Separate fresh reload of the new final save: ${result.final_fresh_reload_verified ? 'verified' : 'not yet verified'}.`, 'campaign-note'));
    const usage = result.usage;
    node.appendChild(el('p', `Returned tokens: ${number(usage.returned_tokens_before_window)} before this window + ${number(usage.new_returned_tokens)} new = ${number(usage.campaign_returned_tokens)} cumulative. Model charge: unreported, not $0.`, 'campaign-note'));
    node.appendChild(el('p', `Game and VM cleanup: ${result.native_cleanup_verified && result.vm_teardown_verified ? 'verified' : 'not verified'}. New save losses: ${number(result.new_native_save_losses)}. Human gameplay rescue: ${result.human_gameplay_rescue ? 'recorded' : 'none recorded'}.${result.shutdown.guest_command_warning ? ' Guest poweroff returned a warning; the stopped VM was verified separately.' : ''}`, 'campaign-note'));
    node.appendChild(el('p', 'Clock outcomes: ' + Object.entries(result.new_window_clock_outcomes).map(([key, n]) => `${key}: ${number(n)}`).join(', ') + '.', 'campaign-note'));
    const history = table('New after-action observations retained in this save', ['Decision', 'New / cumulative ticks', 'Dwarves / recorded dead', 'Raw food / drinks', 'Completed workshops / beds / farms']);
    result.new_window_timeline.forEach(point => {
      const tr = el('tr'), m = point.metrics;
      [number(point.decision), `${number(point.new_elapsed_ticks)} / ${number(point.campaign_elapsed_ticks)}`, `${number(m.population)} / ${number(m.recorded_dead_citizens)}`, `${number(m.food_stock)} / ${number(m.drink_stock)}`, `${number(m.completed_workshops)} / ${number(m.completed_beds)} / ${number(m.completed_farms)}`].forEach(text => tr.appendChild(el('td', text)));
      history.body.appendChild(tr);
    });
    node.appendChild(history.region);
    if (result.new_window_activity) node.appendChild(el('p', 'Observed job types (boundaries, not completed jobs): ' + Object.entries(result.new_window_activity.boundaries_with_job_type).map(([key, n]) => `${key}: ${number(n)}`).join(', ') + '.', 'campaign-note'));
    node.appendChild(link('Read the immutable continuation result', row.evidence_url));
    node.appendChild(el('p', `New checkpoint SHA-256: ${result.checkpoint_sha256}. Result SHA-256: ${row.evidence_sha256}.`, 'campaign-note'));
    node.appendChild(link('Read this attempt’s initial saved result', row.initial_result_url));
    return node;
  }
  function render(data) {
    if (data.schema_version !== 'fortgym.public-keyboard-continuations/v1' || !Array.isArray(data.trials) ||
        data.strong_ranking_supported !== false || data.live_owner_status_included !== false) throw new Error('Unsupported continuation records');
    const output = el('div');
    const summary = table('Decision 32–64 windows, in declared order. Recorded saves, not live status.', ['Model / attempt', 'Published window', 'New / cumulative saved ticks', 'Dwarves / recorded dead', 'Raw food / drinks', 'Completed workshops / beds / farms', 'New / cumulative tokens']);
    data.trials.forEach(row => {
      const tr = el('tr'), result = row.result;
      tr.appendChild(el('td', label(row)));
      if (result === null) {
        tr.appendChild(el('td', 'No published continuation'));
        for (let i = 0; i < 5; i++) tr.appendChild(el('td', 'Not reported'));
      } else {
        const m = result.saved_metrics, usage = result.usage;
        [result.status === 'completed' ? 'Window complete; campaign unfinished' : 'Budget-limited pause',
          `${number(result.new_saved_ticks)} / ${number(result.saved_elapsed_ticks)}`,
          `${number(m.population)} / ${number(m.recorded_dead_citizens)}`,
          `${number(m.food_stock)} / ${number(m.drink_stock)}`,
          `${number(m.completed_workshops)} / ${number(m.completed_beds)} / ${number(m.completed_farms)}`,
          `${number(usage.new_returned_tokens)} / ${number(usage.campaign_returned_tokens)}`].forEach(text => tr.appendChild(el('td', text)));
      }
      summary.body.appendChild(tr);
    });
    output.appendChild(summary.region);
    data.limits.forEach(text => output.appendChild(el('p', text, 'campaign-note')));
    data.trials.filter(row => row.result !== null).forEach(row => output.appendChild(details(row)));
    content.replaceChildren(output); content.hidden = false;
    status.textContent = `${number(data.recorded_windows)} of ${number(data.declared_windows)} continuation windows published. Initial results below remain unchanged.`;
    status.className = '';
  }
  async function load() {
    if (refresh.disabled) return;
    refresh.disabled = true;
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 5000);
    try {
      const response = await fetch('/public/keyboard-cohort-continuations', {cache: 'no-store', signal: controller.signal});
      if (!response.ok) throw new Error('Unavailable');
      render(await response.json());
    } catch (_) {
      status.textContent = content.hidden ? 'Saved continuations are unavailable. Use the data link or retry.' : 'Refresh failed. Showing previously loaded saved evidence.';
      status.className = 'campaign-error';
    } finally { clearTimeout(timer); refresh.disabled = false; }
  }
  refresh.addEventListener('click', load);
  load();
})();

/* Audited saved windows, never a replacement for historical initial results. */
(() => {
  'use strict';
  const status = document.getElementById('endurance-records-status');
  const content = document.getElementById('endurance-records-content');
  const refresh = document.getElementById('refresh-endurance-records');
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
    node.appendChild(el('summary', `${label(row)}: saved window and decision evidence`));
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
    node.appendChild(link('Read this attempt’s decision-64 baseline', row.baseline_result_url));
    return node;
  }
  function render(data) {
    if (data.schema_version !== 'fortgym.public-keyboard-endurance-records/v1' || !Array.isArray(data.trials) ||
        data.strong_ranking_supported !== false || data.live_owner_status_included !== false) throw new Error('Unsupported endurance records');
    const output = el('div');
    const summary = table('Latest verified saves, in declared order. Different response totals are not equal-budget comparisons.',
      ['Model / attempt', 'Saved responses', 'Saved elapsed ticks', 'Dwarves / recorded dead', 'Raw food / drinks',
       'Completed workshops / beds / farms', 'Cumulative returned tokens', 'Published evidence']);
    data.trials.forEach(row => {
      const result = row.latest_result, m = result.saved_metrics, tr = el('tr');
      [label(row), number(result.next_decision), number(result.saved_elapsed_ticks),
        `${number(m.population)} / ${number(m.recorded_dead_citizens)}`,
        `${number(m.food_stock)} / ${number(m.drink_stock)}`,
        `${number(m.completed_workshops)} / ${number(m.completed_beds)} / ${number(m.completed_farms)}`,
        number(result.usage.campaign_returned_tokens),
        row.windows.length ? (result.status === 'completed' ? 'Saved endurance window' : 'Saved budget-limited pause') : 'Decision-64 baseline; no published endurance result'
      ].forEach(text => tr.appendChild(el('td', text)));
      summary.body.appendChild(tr);
    });
    output.appendChild(summary.region);
    data.limits.forEach(text => output.appendChild(el('p', text, 'campaign-note')));
    data.trials.forEach(row => row.windows.forEach(entry => {
      const holder = el('details', undefined, 'campaign-details');
      holder.appendChild(el('summary', `${label(row)}: saved decisions ${number(entry.result.start_decision)} to ${number(entry.result.next_decision)}`));
      let loaded = false;
      holder.addEventListener('toggle', () => {
        if (!holder.open || loaded) return;
        const built = details({...row, ...entry});
        holder.replaceChildren(...Array.from(built.children));
        holder.appendChild(link('Read the exact declared window', entry.declaration_url));
        loaded = true;
      });
      output.appendChild(holder);
    }));
    content.replaceChildren(output); content.hidden = false;
    status.textContent = `${number(data.recorded_endurance_windows)} audited endurance windows across ${number(data.declared_trials)} attempts. Latest verified saves shown; current live play is separate.`;
    status.className = '';
  }
  async function load() {
    if (refresh.disabled) return;
    refresh.disabled = true;
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 5000);
    try {
      const response = await fetch('/public/keyboard-cohort-endurance-records', {cache: 'no-store', signal: controller.signal});
      if (!response.ok) throw new Error('Unavailable');
      render(await response.json());
    } catch (_) {
      status.textContent = content.hidden ? 'Recorded endurance results are unavailable. Use the data link or retry.' : 'Refresh failed. Showing previously loaded saved evidence.';
      status.className = 'campaign-error';
    } finally { clearTimeout(timer); refresh.disabled = false; }
  }
  refresh.addEventListener('click', load);
  load();
})();

/* Recorded matched trials: absent measurements stay unknown, not zero. */
(() => {
  'use strict';
  const status = document.getElementById('keyboard-cohort-status');
  const content = document.getElementById('keyboard-cohort-content');
  const refresh = document.getElementById('refresh-keyboard-cohort');
  if (!status || !content || !refresh) return;
  const number = value => Number.isFinite(value) ? value.toLocaleString('en-US') : 'Unknown';
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
    region.setAttribute('role', 'region'); region.setAttribute('aria-label', caption);
    region.setAttribute('tabindex', '0');
    const tableNode = el('table', undefined, 'campaign-table');
    tableNode.appendChild(el('caption', caption));
    const head = el('thead'), row = el('tr'), body = el('tbody');
    headings.forEach(text => { const th = el('th', text); th.setAttribute('scope', 'col'); row.appendChild(th); });
    head.appendChild(row); tableNode.appendChild(head); tableNode.appendChild(body);
    region.appendChild(tableNode);
    return {region, body};
  }
  function details(row) {
    const result = row.result, node = el('details', undefined, 'campaign-details');
    node.appendChild(el('summary', `${label(row)}: saved outcomes and decision history`));
    const saved = result.saved_metrics, initial = result.initial_metrics;
    const amendment = result.storage_amendment;
    node.appendChild(el('p', amendment
      ? 'VM data disk: 32 GiB under the declared storage amendment. CPU, memory and gameplay settings unchanged; not an identical host configuration.'
      : 'VM data disk: 24 GiB, original execution binding.', 'campaign-note'));
    if (amendment) node.appendChild(link('Read the storage amendment', amendment.plan_url));
    node.appendChild(el('p', `Population ${number(initial.population)} → ${number(saved.population)}. Completed workshops ${number(saved.completed_workshops)}, placed beds ${number(saved.completed_beds)}, farms ${number(saved.completed_farms)}. Recorded dead citizens: ${number(saved.recorded_dead_citizens)}.`));
    node.appendChild(el('p', `${number(result.actions.accepted)} accepted key commands; ${number(result.actions.rejected)} rejected. Accepted input is not proof that its intended work completed.`, 'campaign-note'));
    node.appendChild(el('p', `Saved checkpoint verified: ${result.checkpoint_verified ? 'yes' : 'no'}. Fresh reload of this final checkpoint: ${result.final_fresh_reload_verified ? 'verified' : 'not yet verified'}. Stop reason: ${result.stop_reason}.`, 'campaign-note'));
    node.appendChild(el('p', `Game cleanup and VM teardown: ${result.native_cleanup_verified && result.vm_teardown_verified ? 'verified' : 'not verified'}.${result.shutdown.guest_command_warning ? ' Guest shutdown command returned a warning; the VM stopped state was verified separately.' : ''}`, 'campaign-note'));
    const usage = result.usage;
    node.appendChild(el('p', `${number(usage.accounted_responses)} accounted responses / ${number(usage.dispatched_requests)} dispatched calls. ${number(usage.returned_tokens)} returned tokens. Model charge: ${usage.reported_charge_usd === null ? 'unreported, not $0' : '$' + number(usage.reported_charge_usd)}.`, 'campaign-note'));
    const resources = result.resources;
    node.appendChild(el('p', `Observed memory peak ${number(Math.round(resources.memory_peak_bytes / 1048576))} MiB / ${number(resources.memory_limit_bytes / 1048576)} MiB limit; ${number(resources.memory_limit_events)} limit events and ${number(resources.oom_kills)} OOM kills. This does not establish headroom for a longer campaign.`, 'campaign-note'));
    node.appendChild(el('p', 'Observed job types (boundaries, not completed jobs): ' + Object.entries(result.activity.boundaries_with_job_type).map(([job, count]) => `${job}: ${number(count)}`).join(', ') + '.', 'campaign-note'));
    const history = table('After-action observations at each saved decision', ['Decision', 'Elapsed ticks', 'Dwarves', 'Raw food / drinks', 'Completed workshops / beds / farms']);
    result.timeline.forEach(point => {
      const tr = el('tr'), m = point.metrics;
      [number(point.decision), number(point.elapsed_ticks), number(m.population), `${number(m.food_stock)} / ${number(m.drink_stock)}`, `${number(m.completed_workshops)} / ${number(m.completed_beds)} / ${number(m.completed_farms)}`].forEach(text => tr.appendChild(el('td', text)));
      history.body.appendChild(tr);
    });
    node.appendChild(history.region);
    node.appendChild(link('Read the immutable result manifest', row.evidence_url));
    node.appendChild(el('p', `SHA-256: ${row.evidence_sha256}`, 'campaign-note'));
    return node;
  }
  function render(data) {
    if (data.schema_version !== 'fortgym.public-keyboard-cohort/v1' || !Array.isArray(data.trials)) throw new Error('Unsupported matched evidence');
    const output = el('div');
    const summary = table('Declared order, first-window results. No model ranking.', ['Model / attempt', 'Published state', 'Saved ticks / year', 'Dwarves', 'Raw food / drinks', 'Completed workshops / beds / farms', 'Returned tokens / charge', 'VM data disk']);
    data.trials.forEach(row => {
      const tr = el('tr'), result = row.result;
      tr.appendChild(el('td', label(row)));
      if (result === null) {
        tr.appendChild(el('td', 'No published result'));
        for (let i = 0; i < 6; i++) tr.appendChild(el('td', 'Not reported'));
      } else {
        const m = result.saved_metrics;
        const state = result.status === 'completed' ? 'Window complete; continuation pending' : 'Paused; continuation pending';
        [state, `${number(result.saved_elapsed_ticks)} / ${number(data.year_two_elapsed_ticks)}`, number(m.population), `${number(m.food_stock)} / ${number(m.drink_stock)}`, `${number(m.completed_workshops)} / ${number(m.completed_beds)} / ${number(m.completed_farms)}`, `${number(result.usage.returned_tokens)} / ${result.usage.reported_charge_usd === null ? 'charge unreported' : '$' + number(result.usage.reported_charge_usd)}`].forEach(text => tr.appendChild(el('td', text)));
        tr.appendChild(el('td', result.storage_amendment ? '32 GiB · amended' : '24 GiB · original'));
      }
      summary.body.appendChild(tr);
    });
    output.appendChild(summary.region);
    data.limits.forEach(text => output.appendChild(el('p', text, 'campaign-note')));
    data.trials.filter(row => row.result !== null).forEach(row => output.appendChild(details(row)));
    output.appendChild(link('Read the declared experiment plan', data.plan_url));
    content.replaceChildren(output); content.hidden = false;
    status.textContent = `${number(data.recorded_trials)} of ${number(data.declared_trials)} initial trial windows published. Recorded evidence, not live worker status.`;
    status.className = '';
  }
  async function load() {
    if (refresh.disabled) return;
    refresh.disabled = true;
    try {
      const response = await fetch('/public/keyboard-cohort', {cache: 'no-store'});
      if (!response.ok) throw new Error('Matched evidence unavailable');
      render(await response.json());
    } catch (_) {
      status.textContent = content.hidden ? 'Matched results are unavailable. Use the data link or retry.' : 'Refresh failed. Showing previously loaded recorded evidence.';
      status.className = 'campaign-error';
    } finally { refresh.disabled = false; }
  }
  refresh.addEventListener('click', load);
  load();
})();

/* One recorded control-condition pilot; never add it to the historical cohort. */
(() => {
  'use strict';
  const status = document.getElementById('binding-results-status');
  const content = document.getElementById('binding-results-content');
  const refresh = document.getElementById('refresh-binding-results');
  if (!status || !content || !refresh) return;
  const number = value => Number.isSafeInteger(value) && value >= 0 ? value.toLocaleString('en-US') : 'Unknown';
  const el = (tag, text, className) => {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
  };
  function link(label, url) {
    const node = el('a', label);
    if (/^https:\/\/github\.com\/lemoz\/fort-gym\/blob\/[a-f0-9]{40}\//.test(url || '')) node.href = url;
    return node;
  }
  function keys(labels) {
    const groups = [];
    labels.forEach(label => {
      const previous = groups[groups.length - 1];
      if (previous && previous.label === label) previous.count += 1;
      else groups.push({label, count: 1});
    });
    return groups.map(group => `${group.label === ' ' ? 'Space' : group.label}${group.count > 1 ? ' × ' + group.count : ''}`).join(', ');
  }
  function timeline(rows) {
    const details = el('details', undefined, 'campaign-details');
    details.appendChild(el('summary', 'Inspect all 32 decisions: keys, intent and saved outcomes'));
    details.appendChild(el('p', 'Intent is what the model tried to do, not proof that it succeeded. Repeated adjacent keys are shown as × counts. Full uncompressed keys are in the result data.', 'campaign-note'));
    const region = el('div', undefined, 'campaign-table-scroll');
    region.setAttribute('role', 'region'); region.setAttribute('aria-label', 'Displayed-key decision evidence'); region.setAttribute('tabindex', '0');
    const table = el('table', undefined, 'campaign-table'), head = el('thead'), labels = el('tr'), body = el('tbody');
    table.appendChild(el('caption', '32 saved after-action boundaries. A queued job is not completed production.'));
    ['Decision and model intent', 'Confirmed keys', 'Requested / actual ticks', 'Cumulative saved ticks', 'Dwarves / recorded dead', 'Raw food / drinks', 'Completed workshops / beds / farms', 'Returned tokens'].forEach(label => {
      const th = el('th', label); th.setAttribute('scope', 'col'); labels.appendChild(th);
    });
    head.appendChild(labels); table.appendChild(head);
    rows.forEach(row => {
      const tr = el('tr'), first = el('td', `${number(row.decision)}. ${row.model_intent}`);
      const input = el('details'); input.appendChild(el('summary', `${number(row.confirmed_key_presses)} key presses`));
      input.appendChild(el('p', keys(row.keys), 'campaign-note'));
      first.appendChild(input); tr.appendChild(first);
      const m = row.metrics;
      [row.input_accepted ? 'Accepted input' : 'Input not accepted',
        `${number(row.requested_ticks)} / ${number(row.ticks_advanced)}${row.clock_error ? ' · ' + row.clock_error : ''}`,
        number(row.saved_elapsed_ticks), `${number(m.population)} / ${number(m.recorded_dead_citizens)}`,
        `${number(m.food_stock)} / ${number(m.drink_stock)}`,
        `${number(m.completed_workshops)} / ${number(m.completed_beds)} / ${number(m.completed_farms)}`,
        number(row.returned_tokens)].forEach(text => tr.appendChild(el('td', text)));
      body.appendChild(tr);
    });
    table.appendChild(body); region.appendChild(table); details.appendChild(region);
    return details;
  }
  function render(data) {
    if (data.schema_version !== 'fortgym.public-keyboard-binding-results/v1' || data.recorded_only !== true ||
        data.included_in_historical_cohort !== false) throw new Error('Unsupported binding evidence');
    const result = data.result;
    if (result.schema_version !== 'fortgym.public-keyboard-binding-trial-result/v1' || result.responses !== 32 ||
        result.timeline.length !== 32 || result.status !== 'bounded_trial_complete') throw new Error('Incomplete pilot');
    const output = el('div'), facts = el('dl', undefined, 'campaign-save-facts'), m = result.saved_metrics;
    const values = [
      ['Model / reasoning', `${result.condition.model} / ${result.condition.reasoning_effort}`],
      ['Saved decisions', number(result.responses)], ['Saved elapsed ticks', number(result.saved_elapsed_ticks)],
      ['Dwarves / recorded dead', `${number(m.population)} / ${number(m.recorded_dead_citizens)}`],
      ['Completed workshops / beds / farms', `${number(m.completed_workshops)} / ${number(m.completed_beds)} / ${number(m.completed_farms)}`],
      ['Raw food / drinks', `${number(m.food_stock)} / ${number(m.drink_stock)}`],
      ['Returned tokens', number(result.usage.total_tokens)], ['Reported model charge', 'Unreported, not $0'],
    ];
    values.forEach(([label, value]) => { const item = el('div'); item.appendChild(el('dt', label)); item.appendChild(el('dd', value)); facts.appendChild(item); });
    output.appendChild(facts);
    output.appendChild(el('p', 'The 32-decision limit ended this trial. It is 0.0384 of an elapsed year, not year two. All 248 displayed key presses were confirmed. One blocking menu prevented time advance; the next decision exited it and advanced 2,000 ticks.', 'campaign-note'));
    output.appendChild(el('p', 'Final save verified; separate fresh reload not yet verified. Native game and VM teardown verified. No human gameplay rescue. Sustainable production, consumption and a model ranking are not established.', 'campaign-note'));
    output.appendChild(el('p', 'Food is measured with the native raw-edibility predicate, not the on-screen estimate or a production rate. Completed beds counts placed bed buildings, not bed items or queued jobs.', 'campaign-note'));
    const sources = el('p', undefined, 'campaign-note');
    sources.appendChild(link('Audited result', data.result_url)); sources.appendChild(el('span', ' · '));
    sources.appendChild(link('Exact model condition', data.condition_url)); sources.appendChild(el('span', ' · '));
    sources.appendChild(link('Predeclared trial', data.trial_url)); output.appendChild(sources);
    output.appendChild(timeline(result.timeline));
    content.replaceChildren(output); content.hidden = false;
    status.className = '';
    status.textContent = 'Recorded result: 32 decisions complete and audited. This section is not live status.';
  }
  async function load() {
    if (refresh.disabled) return;
    refresh.disabled = true;
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 5000);
    try {
      const response = await fetch('/public/keyboard-binding-results', {cache: 'no-store', signal: controller.signal});
      if (!response.ok) throw new Error('Unavailable');
      render(await response.json());
    } catch (_) {
      status.textContent = content.hidden ? 'Displayed-key result could not be loaded. Try refreshing.' : 'Refresh failed. The last loaded recorded result remains below; this is not live status.';
      status.className = 'campaign-stale';
    } finally { clearTimeout(timer); refresh.disabled = false; }
  }
  refresh.addEventListener('click', load);
  load();
})();

/* One recorded displayed-key campaign; preserve every saved decision in its own chain. */
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
    details.appendChild(el('summary', `Inspect all ${number(rows.length)} decisions: keys, intent and saved outcomes`));
    details.appendChild(el('p', 'Intent is what the model tried to do, not proof that it succeeded. Repeated adjacent keys are shown as × counts. Full uncompressed keys are in the result data.', 'campaign-note'));
    details.appendChild(el('p', 'Raw food and drink totals can include trader goods. The latest-save breakdown does not describe earlier rows; stock changes are not production.', 'campaign-note'));
    const region = el('div', undefined, 'campaign-table-scroll');
    region.setAttribute('role', 'region'); region.setAttribute('aria-label', 'Displayed-key decision evidence'); region.setAttribute('tabindex', '0');
    const table = el('table', undefined, 'campaign-table'), head = el('thead'), labels = el('tr'), body = el('tbody');
    table.appendChild(el('caption', `${number(rows.length)} saved after-action boundaries. A queued job is not completed production.`));
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
  function inventoryContext(result) {
    const context = result.stock_context;
    if (context === undefined) return el('p', 'Trader breakdown unavailable for this record. Raw food and drink totals may include trader goods and do not establish ownership, accessibility or production.', 'campaign-note');
    const last = result.checkpoints[result.checkpoints.length - 1];
    if (context.schema_version !== 'fortgym.recorded-stock-context/v1' || context.scope !== 'final_checkpoint_only' ||
        context.responses !== result.responses || context.checkpoint_sha256 !== last.checkpoint_sha256 ||
        context.ownership_and_accessibility_verified !== false || context.production_or_sustainability_verified !== false ||
        context.food.raw_units !== result.saved_metrics.food_stock || context.drink.raw_units !== result.saved_metrics.drink_stock ||
        context.drink.trader_flagged_units !== null) throw new Error('Stock context differs from the saved endpoint');
    const food = context.food, output = el('div', undefined, 'campaign-inventory-context');
    if (food.measurement_status === 'complete') {
      if (![food.raw_units, food.trader_flagged_units, food.units_without_trader_flag].every(value => Number.isSafeInteger(value) && value >= 0) ||
          food.trader_flagged_units + food.units_without_trader_flag !== food.raw_units) throw new Error('Invalid food breakdown');
      output.appendChild(el('p', `Food at the latest save: ${number(food.raw_units)} raw units; ${number(food.trader_flagged_units)} trader-flagged; ${number(food.units_without_trader_flag)} without the trader flag.`, 'campaign-note'));
    } else {
      if (!['unavailable', 'incomplete'].includes(food.measurement_status) || food.trader_flagged_units !== null || food.units_without_trader_flag !== null) throw new Error('Invalid unknown food breakdown');
      output.appendChild(el('p', `Food trader breakdown: Unknown (${food.measurement_status === 'incomplete' ? 'incomplete measurement' : 'not recorded'}).`, 'campaign-note'));
    }
    output.appendChild(el('p', 'Without the trader flag does not mean fortress-owned or reachable. Trader share of drinks: Unknown (not recorded). These counts do not establish production or sustainability.', 'campaign-note'));
    return output;
  }
  function render(data) {
    if (data.schema_version !== 'fortgym.public-keyboard-binding-campaign/v1' || data.recorded_only !== true ||
        data.included_in_historical_cohort !== false || data.independent_attempts !== 1) throw new Error('Unsupported campaign evidence');
    const result = data;
    if (!Number.isSafeInteger(result.responses) || result.responses < 1 ||
        !Array.isArray(result.timeline) || result.timeline.length !== result.responses ||
        !['completed', 'paused'].includes(result.status)) throw new Error('Incomplete campaign');
    const output = el('div'), facts = el('dl', undefined, 'campaign-save-facts'), m = result.saved_metrics;
    const values = [
      ['Model / reasoning', `${result.condition.model} / ${result.condition.reasoning_effort}`],
      ['Saved decisions', number(result.responses)], ['Saved elapsed ticks', number(result.saved_elapsed_ticks)],
      ['Dwarves / recorded dead', `${number(m.population)} / ${number(m.recorded_dead_citizens)}`],
      ['Completed workshops / beds / farms', `${number(m.completed_workshops)} / ${number(m.completed_beds)} / ${number(m.completed_farms)}`],
      ['Raw food / drinks', `${number(m.food_stock)} / ${number(m.drink_stock)}`],
      ['Functional rooms', number(m.functional_rooms)],
      ['Returned tokens', number(result.usage.total_tokens)], ['Reported model charge', 'Unreported, not $0'],
    ];
    values.forEach(([label, value]) => { const item = el('div'); item.appendChild(el('dt', label)); item.appendChild(el('dd', value)); facts.appendChild(item); });
    output.appendChild(facts);
    output.appendChild(inventoryContext(result));
    const years = result.saved_elapsed_ticks / result.ticks_per_year;
    const duration = Number.isFinite(years) ? years.toFixed(4) : 'Unknown';
    const stop = result.stop_reason === 'segment_limit' ? 'The declared decision window completed.' :
      result.stop_reason === 'budget_limited_pause' ? 'Paused at a usage or budget boundary.' : 'Recorded window ended.';
    output.appendChild(el('p', `${stop} ${duration} elapsed years. ${years < 1 ? 'This campaign has not reached year two.' : 'Reaching year two does not prove long-term self-sufficiency.'} All ${number(result.confirmed_key_presses)} displayed key presses were confirmed.`, 'campaign-note'));
    const window = result.latest_window, before = window.initial_metrics;
    output.appendChild(el('p', `Since the previous save: ${number(window.responses)} decisions, ${number(window.elapsed_ticks)} elapsed ticks and ${number(window.returned_tokens)} returned tokens. Completed beds ${number(before.completed_beds)} → ${number(m.completed_beds)}; workshops ${number(before.completed_workshops)} → ${number(m.completed_workshops)}; food ${number(before.food_stock)} → ${number(m.food_stock)}; drinks ${number(before.drink_stock)} → ${number(m.drink_stock)}.`, 'campaign-note'));
    const blocked = window.clock_outcomes.blocking_native_menu || 0;
    if (blocked) output.appendChild(el('p', `${number(blocked)} time-advance attempts were blocked by menus in this window. Inspect the decision history for each failure and the following action.`, 'campaign-note'));
    output.appendChild(el('p', 'Latest save, native game cleanup and VM shutdown verified. No human gameplay rescue. Sustainable production, consumption and a model ranking are not established.', 'campaign-note'));
    output.appendChild(el('p', 'Food is the measured edible inventory, not the on-screen estimate or a production rate. Completed beds counts placed bed buildings, not bed items or queued jobs.', 'campaign-note'));
    const history = el('details', undefined, 'campaign-details');
    history.appendChild(el('summary', 'Save and reload history'));
    result.checkpoints.forEach(checkpoint => {
      if (checkpoint.continuation_reload_verified === true || checkpoint.segment_index !== undefined) {
        const reload = checkpoint.continuation_reload_verified === true ? 'continued-play reload verified' : 'following reload not yet verified';
        history.appendChild(el('p', `Decision ${number(checkpoint.responses)}: save verified; ${reload}. ${number(checkpoint.saved_elapsed_ticks)} saved ticks.`));
        if (checkpoint.new_responses === 0) history.appendChild(el('p', 'Pause checkpoint: no additional model decisions. This save retains its own checkpoint identity.', 'campaign-note'));
      } else {
        history.appendChild(el('p', `Decision ${number(checkpoint.responses)}: save verified; separate fresh reload ${checkpoint.separate_fresh_reload_verified ? 'verified' : 'not yet tested'}.`));
      }
      history.appendChild(el('p', checkpoint.reload_note, 'campaign-note'));
      if (checkpoint.shutdown && checkpoint.shutdown.guest_command_warning) {
        history.appendChild(el('p', `Decision ${number(checkpoint.responses)}: the guest poweroff command returned an SSH warning. The separate VM stop succeeded, and an independent check confirmed it stopped.`, 'campaign-note'));
      }
      history.appendChild(link('Saved checkpoint evidence', checkpoint.result_url));
      if (checkpoint.reload_url) {
        history.appendChild(el('span', ' · '));
        history.appendChild(link('Reload verification', checkpoint.reload_url));
      }
      if (checkpoint.continuation_reload_url && checkpoint.continuation_reload_url !== checkpoint.result_url) {
        history.appendChild(el('span', ' · '));
        history.appendChild(link('Continued-play reload evidence', checkpoint.continuation_reload_url));
      }
    });
    output.appendChild(history);
    const sources = el('p', undefined, 'campaign-note');
    sources.appendChild(link('Audited result', data.result_url)); sources.appendChild(el('span', ' · '));
    sources.appendChild(link('Exact model condition', data.condition_url)); sources.appendChild(el('span', ' · '));
    sources.appendChild(link('Predeclared trial', data.trial_url)); output.appendChild(sources);
    output.appendChild(timeline(result.timeline));
    content.replaceChildren(output); content.hidden = false;
    status.className = '';
    status.textContent = `Recorded campaign: ${number(result.responses)} decisions saved and audited. One attempt, including its continuation. This is not live status.`;
  }
  async function load() {
    if (refresh.disabled) return;
    refresh.disabled = true;
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 5000);
    try {
      const response = await fetch('/public/keyboard-binding-campaign', {cache: 'no-store', signal: controller.signal});
      if (!response.ok) throw new Error('Unavailable');
      render(await response.json());
    } catch (_) {
      status.textContent = content.hidden ? 'Displayed-key campaign could not be loaded. Try refreshing.' : 'Refresh failed. The last loaded recorded result remains below; this is not live status.';
      status.className = 'campaign-stale';
    } finally { clearTimeout(timer); refresh.disabled = false; }
  }
  refresh.addEventListener('click', load);
  load();
})();

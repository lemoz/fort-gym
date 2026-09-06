(function () {
  'use strict';
  const TICKS_PER_YEAR = 403200;
  const metricNames = {
    population: 'Dwarves', food_stock: 'Food stock', drink_stock: 'Drink stock',
    wood_stock: 'Wood stock', stone_stock: 'Stone stock', functional_rooms: 'Detected functional rooms',
    completed_workshops: 'Completed workshops', completed_beds: 'Completed beds',
    completed_farms: 'Completed farms', recorded_dead_citizens: 'Recorded dead citizens'
  };
  const statusNames = {
    bounded_segment_complete: 'Segment complete', budget_limited_pause: 'Paused at a configured limit',
    failed: 'Failed segment', checkpoint_failed: 'Checkpoint failure', started: 'Started'
  };
  const failureNames = { model_action: 'Invalid model command', provider: 'Provider failure',
    runtime: 'Runtime failure', checkpoint: 'Checkpoint failure', unclassified: 'Unclassified failure' };
  const conditionFiles = {
    'development-continuation-v1': 'development_continuation_v1.json',
    'development-autonomous-v1': 'development_autonomous_v1.json',
    'endurance-autonomous-v1': 'endurance_autonomous_v1.json',
    'local-native-development-v1': 'local_native_development_v1.json',
    'local-native-visible-contract-v1': 'local_native_visible_contract_v1.json',
    'local-native-packed-comparison-v1': 'local_native_packed_comparison_v1.json',
    'local-native-harness-repair-v1': 'local_native_harness_repair_v1.json'
  };
  function known(value) { return typeof value === 'number' && Number.isFinite(value) && value >= 0; }
  function number(value) { return known(value) ? value.toLocaleString('en-US') : 'Unknown'; }
  function money(value) {
    if (typeof value !== 'string' || !/^\d+(\.\d+)?([eE][+-]?\d+)?$/.test(value)) return 'Unknown';
    const amount = Number(value);
    if (amount > 0 && amount < 0.000001) return '< $0.000001';
    return Number.isFinite(amount) && amount >= 0 ? `$${amount.toFixed(6)}` : 'Unknown';
  }
  function modelCost(usage) {
    if (usage?.cost_basis === 'self_hosted_no_metered_provider') {
      const charge = usage.metered_provider_charge_usd;
      const zero = typeof charge === 'string' && /^0+(\.0+)?([eE][+-]?\d+)?$/.test(charge);
      return zero ? '$0 model API · self-hosted' : 'Model API charge unknown · self-hosted';
    }
    return money(usage?.reported_model_cost_usd);
  }
  function duration(ticks) { return known(ticks) ? `${number(ticks)} ticks · ${(ticks / TICKS_PER_YEAR).toFixed(3)} years` : 'Unknown'; }
  function stateLabel(row, disconnected) {
    if (disconnected) return 'Update unavailable; last report below';
    if (row.freshness === 'clock_mismatch') return 'Update timestamp inconsistent';
    if (row.freshness === 'stale') return 'Stale report; current state unknown';
    if (row.lifecycle === 'starting') return 'Starting segment (reported)';
    if (row.lifecycle === 'running') return 'Running segment (reported)';
    if (row.lifecycle === 'awaiting_teardown') return 'Awaiting teardown report';
    return failureNames[row.failure_kind] || statusNames[row.segment_status] || 'Unknown';
  }
  const helpers = { number, money, modelCost, duration, stateLabel };
  if (typeof module !== 'undefined') module.exports = helpers;
  if (typeof document === 'undefined') return;
  const $ = id => document.getElementById(id);
  let data = null, disconnected = false, selected = null, timer = null, loading = false;
  function node(tag, text, parent) {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = text;
    if (parent) parent.append(element);
    return element;
  }
  function table(parent, title, headings) {
    const scroll = node('div', undefined, parent);
    scroll.className = 'campaign-table-scroll'; scroll.tabIndex = 0;
    const result = node('table', undefined, scroll); result.className = 'campaign-table';
    node('caption', title, result);
    const tr = node('tr', undefined, node('thead', undefined, result));
    headings.forEach(text => { node('th', text, tr).scope = 'col'; });
    return node('tbody', undefined, result);
  }
  function inspect(row) {
    const panel = $('campaign-profile-detail'); panel.replaceChildren();
    if (!row) return;
    node('h3', `${row.model} · ${row.campaign_id}`, panel);
    node('p', `${row.condition_id}; latest segment ${row.segment_id}. ${stateLabel(row, disconnected)}.`, panel);
    if (row.publication === 'versioned_snapshot') node('p', 'Published terminal snapshot from the versioned repository. This is recorded evidence, not a live worker.', panel);
    node('p', `${number(row.committed_steps)} committed actions; ${duration(row.elapsed_ticks)}.`, panel);
    const actions = row.actions || {};
    node('p', `${number(actions.accepted)} accepted commands; ${number(actions.rejected)} rejected; ${number(actions.unknown)} with unknown outcomes. Accepted commands can be no-ops or queued work, not completed development.`, panel);
    if (known(actions.path_cache_stale_rejections) && actions.path_cache_stale_rejections > 0) {
      node('p', `${number(actions.path_cache_stale_rejections)} commands were blocked because the native pathfinding cache was not ready. This is an adapter readiness limitation, not evidence that those placements were illegal.`, panel);
    }
    if (Object.keys(actions.by_type || {}).length) {
      const commands = table(panel, 'Recorded command choices', ['Control', 'Accepted', 'Rejected', 'Unknown']);
      Object.entries(actions.by_type).forEach(([kind, counts]) => {
        const tr = node('tr', undefined, commands);
        [kind, number(counts.accepted), number(counts.rejected), number(counts.unknown)].forEach(value => node('td', value, tr));
      });
      node('p', `${number(actions.changed_command_after_rejection)} changed commands following rejection. Changing a command does not establish recovery.`, panel);
    }
    node('p', `Checkpoint: ${row.checkpoint_verified ? 'verified' : 'not verified'}. Teardown: ${row.cleanup_verified === true ? 'verified' : row.cleanup_verified === false ? 'not verified' : 'unknown'}.`, panel);
    const usage = row.usage || {};
    const local = usage.cost_basis === 'self_hosted_no_metered_provider';
    node('p', `${modelCost(usage)}${local ? '' : ' response-reported model usage'}; ${number(usage.total_tokens)} tokens. ${number(usage.returned_responses)} returned responses across ${number(usage.dispatched_requests)} dispatches. ${number(usage.dispatches_without_returned_usage)} dispatches lack returned usage. This is not reconciled billing or remaining budget.`, panel);
    if (local) node('p', 'Hardware, electricity and infrastructure costs are not measured here. Zero model API charges do not mean zero operating cost.', panel);
    if (!local && money(usage.reported_model_cost_usd) !== 'Unknown') node('p', `Exact reported cost: ${usage.reported_model_cost_usd} USD.`, panel);
    const summaries = row.metric_summaries || {};
    const body = table(panel, 'Observed state, not an inferred success score', ['Measure', 'Start', 'Latest', 'Change', 'Observed min / max']);
    Object.entries(metricNames).forEach(([key, label]) => {
      const summary = summaries[key] || {}, tr = node('tr', undefined, body);
      node('td', label, tr); node('td', number(summary.start), tr);
      node('td', number(row.current_metrics?.[key]), tr);
      const change = known(summary.start) && known(summary.end) ? summary.end - summary.start : null;
      node('td', change === null ? 'Unknown' : `${change > 0 ? '+' : ''}${change}`, tr);
      node('td', `${number(summary.minimum_observed)} / ${number(summary.maximum_observed)}`, tr);
    });
    if ((row.timeline || []).length) {
      const details = node('details', undefined, panel);
      node('summary', row.timeline_sampled ? 'Recorded boundaries (sampled; gaps are not interpolated)' : 'Recorded boundaries', details);
      const timeline = table(details, 'Native calendar and observed resource stocks', ['Boundary', 'Native year / tick', 'Dwarves', 'Food', 'Drink', 'Rooms']);
      row.timeline.forEach(point => {
        const tr = node('tr', undefined, timeline), metrics = point.metrics || {};
        [number(point.boundary_index), `${number(point.year)} / ${number(point.year_tick)}`,
          number(metrics.population), number(metrics.food_stock), number(metrics.drink_stock), number(metrics.functional_rooms)]
          .forEach(text => node('td', text, tr));
      });
    } else node('p', 'Full metric history is available after a segment profile is recorded.', panel);
    node('p', 'Food and drink production, consumption rates, autonomous success, and fortress collapse are not assessed by these summaries.', panel);
    if (/^[a-f0-9]{40}$/.test(row.code_revision) && conditionFiles[row.condition_id]) {
      const link = node('a', 'Inspect this segment’s experiment configuration', panel);
      link.href = `https://github.com/lemoz/fort-gym/blob/${row.code_revision}/experiments/campaigns/${conditionFiles[row.condition_id]}`;
    }
    node('pre', JSON.stringify({ code_revision: row.code_revision, configuration_sha256: row.configuration_sha256,
      declared_starting_snapshot_receipt_sha256: row.declared_starting_snapshot_receipt_sha256 || null,
      source_sha256: row.source_sha256 }, null, 2), panel);
  }
  function render() {
    if (!data) return;
    const filter = $('campaign-condition-filter'), previous = filter.value || '';
    filter.replaceChildren(); node('option', 'All conditions', filter).value = '';
    const conditions = [...new Set(data.campaigns.map(row => row.condition_id))].sort();
    conditions.forEach(condition => { node('option', condition, filter).value = condition; });
    filter.value = conditions.includes(previous) ? previous : '';
    const rows = data.campaigns.filter(row => !filter.value || row.condition_id === filter.value);
    $('campaign-feed-rows').replaceChildren();
    rows.forEach(row => {
      const tr = node('tr', undefined, $('campaign-feed-rows'));
      const identity = node('td', row.model, tr);
      node('small', `${row.campaign_id} · ${row.condition_id}`, identity);
      const link = node('a', 'Inspect profile', identity); link.href = '#campaign-profile-detail';
      link.addEventListener('click', () => { selected = row.campaign_id; inspect(row); });
      const state = node('td', stateLabel(row, disconnected), tr);
      if (disconnected || ['stale', 'clock_mismatch'].includes(row.freshness)) state.className = 'campaign-stale';
      node('small', `Last reported: ${statusNames[row.segment_status] || 'unknown'}`, state);
      node('small', row.updated_at, state);
      node('td', duration(row.elapsed_ticks), tr);
      const metrics = row.current_metrics || {};
      node('td', number(metrics.population), tr);
      node('td', `${number(metrics.food_stock)} / ${number(metrics.drink_stock)}`, tr);
      node('td', `${number(metrics.completed_workshops)} / ${number(metrics.completed_beds)} / ${number(metrics.completed_farms)}`, tr);
      const cost = node('td', modelCost(row.usage), tr);
      if (row.usage?.cost_basis === 'self_hosted_no_metered_provider') node('small', 'Operating costs unknown', cost);
    });
    if (!rows.length) node('td', 'No campaign summaries match this condition.', node('tr', undefined, $('campaign-feed-rows'))).colSpan = 7;
    inspect(rows.find(row => row.campaign_id === selected));
    $('campaign-feed-content').hidden = !data.configured && !data.campaigns.length;
    if (!disconnected) $('campaign-feed-status').textContent = data.configured
      ? `${data.campaigns.length} campaign summaries. Status is based on the last report, not a live process check.`
      : data.campaigns.length ? `${data.campaigns.length} published terminal snapshots. Live campaign tracking is not connected to this site.`
      : 'Campaign tracking is not connected to this site yet. Published development probes remain below.';
  }
  async function refresh() {
    if (loading) return;
    loading = true; $('refresh-campaign-feed').disabled = true;
    if (timer !== null) clearTimeout(timer);
    try {
      const response = await fetch('/public/campaign-feed', { cache: 'no-store' });
      if (!response.ok) throw new Error('Unavailable');
      const received = await response.json();
      if (received.schema_version !== 'fortgym.public-campaign-feed/v1' || !Array.isArray(received.campaigns) || typeof received.configured !== 'boolean' || !received.campaigns.every(row => row && ['model', 'campaign_id', 'condition_id', 'segment_id'].every(key => typeof row[key] === 'string'))) throw new Error('Unsupported feed');
      data = received; disconnected = false;
      $('campaign-feed-status').className = ''; render();
    } catch (_) {
      disconnected = true; render();
      $('campaign-feed-status').className = 'campaign-error';
      $('campaign-feed-status').textContent = data
        ? 'Campaign updates could not be loaded. Showing the last fetched data; current state is unknown.'
        : 'Campaign tracking could not be loaded. This does not mean there are no campaigns.';
    } finally {
      loading = false; $('refresh-campaign-feed').disabled = false;
      timer = setTimeout(() => { if (!document.hidden) refresh(); else timer = null; }, 15000);
    }
  }
  $('campaign-condition-filter').addEventListener('change', render);
  $('refresh-campaign-feed').addEventListener('click', refresh);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
  refresh();
}());

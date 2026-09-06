(function () {
  'use strict';
  const labels = {
    model_action_contract_failure: 'Invalid model action; no gameplay success',
    provider_failure: 'Provider failure',
    budget_limited_pause: 'Budget-limited pause',
    bounded_probe_returned: 'Bounded probe returned; outcome unassessed',
    unclassified_failure: 'Unclassified failure',
    incomplete: 'Incomplete evidence'
  };
  function number(value) {
    return typeof value === 'number' && Number.isFinite(value) && value >= 0
      ? value.toLocaleString('en-US') : 'Unknown';
  }
  function money(value) {
    if (!['string', 'number'].includes(typeof value) || String(value).trim() === '') return 'Unknown';
    const parsed = Number(value);
    return Number.isFinite(parsed) && parsed >= 0 ? `$${parsed.toFixed(6)}` : 'Unknown';
  }
  function modelCoverage(data) {
    return data.condition.models.map(model => ({
      model, attempts: data.experiments.filter(row => row.model === model).length
    }));
  }
  const helpers = { number, money, modelCoverage, labels };
  if (typeof module !== 'undefined') module.exports = helpers;
  if (typeof document === 'undefined') return;
  const $ = id => document.getElementById(id);
  function node(tag, text, parent) {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = text;
    if (parent) parent.append(element);
    return element;
  }
  function render(data) {
    if (data.schema_version !== 'fortgym.public-campaign-experiments/v1') throw new Error('Unsupported evidence');
    $('condition-description').textContent = `${data.condition.max_steps} model-chosen actions maximum, ${data.condition.max_dispatches} dispatches maximum, ${money(data.condition.reported_usage_stop_usd)} reported-usage stop per attempt. Same retained starting save; not a fresh embark.`;
    $('model-coverage').replaceChildren();
    modelCoverage(data).forEach(item => {
      const card = node('p', undefined, $('model-coverage'));
      node('strong', item.model, card);
      node('span', item.attempts ? `${item.attempts} published attempt${item.attempts === 1 ? '' : 's'}` : 'No published attempt', card);
    });
    $('experiment-rows').replaceChildren();
    $('experiment-details').replaceChildren();
    data.experiments.forEach((row, index) => {
      const tr = node('tr', undefined, $('experiment-rows'));
      const identity = node('td', row.model, tr);
      const link = node('a', 'Inspect evidence', identity);
      link.href = `#experiment-${index}`;
      node('small', row.evidence_id, identity);
      node('td', labels[row.outcome] || 'Unclassified outcome', tr);
      node('td', number(row.native_elapsed_ticks), tr);
      node('td', number(row.last_observed_population), tr);
      const cost = node('td', money(row.reported_model_cost_usd), tr);
      node('small', `${number(row.dispatches_without_returned_usage)} dispatches without returned usage`, cost);
      node('td', row.cleanup_verified === true ? 'Verified' : row.cleanup_verified === false ? 'Not verified' : 'Unknown', tr);
      const detail = node('details', undefined, $('experiment-details'));
      detail.className = 'campaign-details';
      detail.id = `experiment-${index}`;
      node('summary', `${row.model}: ${row.evidence_id}`, detail);
      link.addEventListener('click', () => { detail.open = true; });
      node('p', row.action_diagnostic || 'No action diagnostic published.', detail);
      node('p', row.provider_diagnostic || 'No provider diagnostic published.', detail);
      node('p', `${number(row.action_rows)} action rows. ${number(row.returned_responses)} returned responses across ${number(row.dispatches)} dispatches.`, detail);
      const list = node('ul', undefined, detail);
      (row.limits || []).forEach(limit => node('li', limit, list));
      if (/^[a-f0-9]{40}$/.test(row.code_revision || '')) {
        const source = node('a', 'Inspect the exact experiment configuration', detail);
        source.href = `https://github.com/lemoz/fort-gym/blob/${row.code_revision}/experiments/campaigns/development_probe_v1.json`;
      }
      node('pre', JSON.stringify({ code_revision: row.code_revision, source_sha256: row.source_sha256 }, null, 2), detail);
    });
    if (!data.experiments.length) {
      const td = node('td', 'No experiment evidence has been published.', node('tr', undefined, $('experiment-rows')));
      td.colSpan = 6;
    }
    $('catalog-content').hidden = false;
    $('catalog-status').textContent = `${data.experiments.length} published development attempt${data.experiments.length === 1 ? '' : 's'}. Not a live activity feed.`;
  }
  async function refresh() {
    $('refresh-campaigns').disabled = true;
    $('catalog-status').className = '';
    $('catalog-status').textContent = 'Loading published experiment evidence…';
    try {
      const response = await fetch('/public/campaign-experiments', { cache: 'no-store' });
      if (!response.ok) throw new Error('Evidence request failed');
      render(await response.json());
    } catch (_) {
      $('catalog-content').hidden = true;
      $('catalog-status').className = 'campaign-error';
      $('catalog-status').textContent = 'Campaign evidence could not be loaded. Retry with Refresh evidence; this does not mean there are no experiments.';
    } finally {
      $('refresh-campaigns').disabled = false;
    }
  }
  $('refresh-campaigns').addEventListener('click', refresh);
  refresh();
}());

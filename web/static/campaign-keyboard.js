(function () {
  'use strict';
  function count(value) {
    return Number.isSafeInteger(value) && value >= 0 ? value.toLocaleString('en-US') : 'Unknown';
  }
  function cost(usage) {
    if (usage?.cost_basis === 'codex_subscription_charge_unreported/v1'
        && usage.reported_charge_usd === null) return 'Unreported · Codex subscription';
    return 'Unknown';
  }
  const helpers = { count, cost };
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
    if (data.schema_version !== 'fortgym.public-keyboard-milestones/v1'
        || data.live_tracking !== false || !Array.isArray(data.milestones)) {
      throw new Error('Unsupported keyboard evidence');
    }
    const results = $('keyboard-results');
    results.replaceChildren();
    data.milestones.slice().reverse().forEach(row => {
      const section = node('section', undefined, results);
      section.className = 'campaign-condition';
      const p = row.progress;
      node('h3', `${count(p.model_decisions)} decisions · ${count(p.elapsed_native_ticks)} elapsed ticks`, section);
      node('p', `${count(p.native_key_events_confirmed)} confirmed key events. Saved checkpoints at decisions ${p.checkpoint_cursors.map(count).join(', ')}.`, section);
      node('p', `${count(row.usage.campaign_tokens)} campaign tokens; ${count(row.usage.all_attempt_tokens)} including failed delivery attempts.`, section);
      node('p', `Model charge: ${cost(row.usage)}.`, section);
      node('p', row.teardown_verified === true ? 'Game and VM teardown verified for this milestone.' : 'Teardown unknown.', section);
      const details = node('details', undefined, section);
      details.className = 'campaign-details';
      node('summary', 'Inspect condition and evidence', details);
      node('p', `${row.model} / ${row.reasoning_effort}; ${row.control_profile}; ${row.observation_profile}.`, details);
      if (/^[a-f0-9]{40}$/.test(row.source_revision)
          && /^experiments\/evidence\/astra_native_keyboard_[a-z0-9_]+\.json$/.test(row.evidence_path)) {
        const link = node('a', 'Read the published operational evidence', details);
        link.href = 'https://github.com/lemoz/fort-gym/blob/codex/campaign-codex-subscription/' + row.evidence_path;
      }
      node('p', `Executed source: ${row.source_revision}`, details);
    });
    results.hidden = false;
    $('keyboard-status').textContent = data.milestones.length
      ? 'Recorded milestones. This is not a live activity indicator.'
      : 'No keyboard milestones published.';
  }
  async function refresh() {
    $('refresh-keyboard-campaigns').disabled = true;
    $('keyboard-status').textContent = 'Loading recorded keyboard results…';
    try {
      const response = await fetch('/public/keyboard-campaigns', { cache: 'no-store' });
      if (!response.ok) throw new Error('Keyboard evidence unavailable');
      render(await response.json());
    } catch (_) {
      $('keyboard-results').hidden = true;
      $('keyboard-status').textContent = 'Keyboard evidence could not be loaded. Refresh to retry; missing data is not a failed fortress.';
    } finally {
      $('refresh-keyboard-campaigns').disabled = false;
    }
  }
  $('refresh-keyboard-campaigns').addEventListener('click', refresh);
  refresh();
}());

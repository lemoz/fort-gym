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
    if (data.interruptions !== undefined && !Array.isArray(data.interruptions)) {
      throw new Error('Unsupported keyboard interruption evidence');
    }
    if (data.recoveries !== undefined && !Array.isArray(data.recoveries)) {
      throw new Error('Unsupported keyboard recovery evidence');
    }
    const recoveries = data.recoveries || [];
    if (data.checkpoint_failures !== undefined && !Array.isArray(data.checkpoint_failures)) {
      throw new Error('Unsupported checkpoint failure evidence');
    }
    if (data.restarts !== undefined && !Array.isArray(data.restarts)) {
      throw new Error('Unsupported restart evidence');
    }
    const restarts = data.restarts || [];
    restarts.slice().reverse().forEach(row => {
      const section = node('section', undefined, results);
      section.className = 'campaign-condition';
      const p = row.progress;
      node('h3', `New branch saved · checkpoint ${count(p.checkpoint_cursor)}`, section);
      node('p', `${count(p.new_accepted_decisions)} new accepted decisions after restarting from checkpoint ${count(p.restored_checkpoint_cursor)}. Verified game save: ${count(p.retained_elapsed_ticks)} retained elapsed ticks, including ${count(p.new_elapsed_ticks)} new ticks.`, section);
      node('p', `The original unsaved ${count(p.discarded_native_ticks)} ticks remain lost. Astra chose new actions; no historical action was replayed. This is not uninterrupted play or an independent comparison attempt.`, section);
      node('p', `${count(p.cumulative_model_responses)} total accounted model responses. The new branch cursor is ${count(p.checkpoint_cursor)} because it replaces the lost branch, not its usage.`, section);
      node('p', `${count(row.usage.campaign_tokens)} campaign tokens; ${count(row.usage.all_attempt_tokens)} including historical failed deliveries. This segment used ${count(row.usage.new_tokens)} tokens. The lost tail's ${count(row.usage.lost_tail_tokens_retained)} tokens are still included. Model charge: ${cost(row.usage)}.`, section);
      node('p', row.teardown_verified === true ? 'Game and VM teardown verified. Recorded result, not a running campaign.' : 'Teardown unknown.', section);
      if (/^experiments\/evidence\/astra_native_keyboard_[a-z0-9_]+\.json$/.test(row.evidence_path)) {
        const link = node('a', 'Read the published restart evidence', section);
        link.href = 'https://github.com/lemoz/fort-gym/blob/codex/campaign-codex-subscription/' + row.evidence_path;
      }
    });
    (data.checkpoint_failures || []).slice().reverse().forEach(row => {
      const section = node('section', undefined, results);
      section.className = 'campaign-condition';
      const p = row.progress;
      node('h3', `Save failed after decision ${count(p.retained_trace_cursor)}`, section);
      node('p', `${count(p.new_accepted_model_responses)} accepted model responses and ${count(p.unsaved_new_native_ticks)} new ticks were not preserved in the game save. Their trace and usage are retained. This is a harness save failure, not a recorded fortress collapse.`, section);
      node('p', `Game save at this failure: decision ${count(p.last_resumable_checkpoint_cursor)}, ${count(p.last_saved_elapsed_ticks)} elapsed ticks. The trace reached ${count(p.committed_elapsed_ticks_in_trace)} ticks, but that newer game state is not resumable.`, section);
      node('p', restarts.some(item => item.original_failure === row.failure_id)
        ? 'A later, explicitly recorded restart is shown above. It preserves this usage but does not recover the lost game state.'
        : 'A later attempt must explicitly record the lost progress and retain its usage. The old checkpoint is not a seamless continuation.', section);
      node('p', `${count(row.usage.campaign_tokens)} campaign tokens; ${count(row.usage.all_attempt_tokens)} including historical failed deliveries. The unsaved tail used ${count(row.usage.new_tokens)} tokens, all included. Model charge: ${cost(row.usage)}.`, section);
      node('p', row.teardown_verified === true ? 'Game and VM teardown verified for this save failure.' : 'Teardown unknown.', section);
      if (/^experiments\/evidence\/astra_native_keyboard_[a-z0-9_]+\.json$/.test(row.evidence_path)) {
        const link = node('a', 'Read the published save-failure evidence', section);
        link.href = 'https://github.com/lemoz/fort-gym/blob/codex/campaign-codex-subscription/' + row.evidence_path;
      }
    });
    function renderRecovery(row) {
      const section = node('section', undefined, results);
      section.className = 'campaign-condition';
      node('h3', `Recovery verified · checkpoint ${count(row.checkpoint_cursor)}`, section);
      node('p', `${count(row.returned_model_decisions)} existing model responses and ${count(row.elapsed_native_ticks)} elapsed ticks preserved. Model memory and usage are unchanged.`, section);
      node('p', `${count(row.model_calls_to_recover)} new model calls, ${count(row.native_keys_to_recover)} replayed keys, ${count(row.native_ticks_to_recover)} added ticks. Recovery preserved the retained state and responses; it is not new gameplay progress.`, section);
      node('p', 'The original interrupted window remains failed. This checkpoint was verified at this point in the campaign; later records determine the latest resumable state. It does not prove that a new run has started.', section);
      node('p', `${count(row.usage.campaign_tokens)} campaign tokens; ${count(row.usage.all_attempt_tokens)} including historical failed deliveries. Model charge: ${cost(row.usage)}.`, section);
      node('p', row.teardown_verified === true ? 'Game and VM teardown verified for recovery.' : 'Teardown unknown.', section);
      if (/^experiments\/evidence\/astra_native_keyboard_[a-z0-9_]+\.json$/.test(row.evidence_path)) {
        const link = node('a', 'Read the published recovery evidence', section);
        link.href = 'https://github.com/lemoz/fort-gym/blob/codex/campaign-codex-subscription/' + row.evidence_path;
      }
    }
    (data.interruptions || []).slice().reverse().forEach(row => {
      const recovery = recoveries.find(item => item.original_interruption === row.interruption_id);
      if (recovery) renderRecovery(recovery);
      const section = node('section', undefined, results);
      section.className = 'campaign-condition';
      const p = row.progress;
      node('h3', `Interrupted at ${count(p.committed_decisions)} committed decisions`, section);
      node('p', row.terminal_reason === 'unsupported_model_key_names_stopped_harness'
        ? 'Unsupported model key names stopped the harness. No input or time from that response was dispatched. This is not a recorded fortress collapse.'
        : 'Harness clock timeout. This interruption is not a recorded fortress collapse.', section);
      node('p', `${count(p.returned_model_decisions)} model responses; ${count(p.elapsed_native_ticks)} committed elapsed ticks. Checkpoint at interruption: decision ${count(p.latest_verified_checkpoint_cursor)}.`, section);
      node('p', recovery
        ? `Subsequently recovered as checkpoint ${count(recovery.checkpoint_cursor)} without replay. The original failure remains recorded.`
        : 'Newer native state is retained. Recovery must reconcile it before continuing; the older checkpoint must not silently replace it.', section);
      node('p', `${count(row.usage.campaign_tokens)} campaign tokens; ${count(row.usage.all_attempt_tokens)} including historical failed deliveries. Failed-request usage is included, not discarded.`, section);
      node('p', `Model charge: ${cost(row.usage)}.`, section);
      node('p', row.teardown_verified === true ? 'Game and VM teardown verified for this interruption.' : 'Teardown unknown.', section);
      if (/^experiments\/evidence\/astra_native_keyboard_[a-z0-9_]+\.json$/.test(row.evidence_path)) {
        const link = node('a', 'Read the published interruption evidence', section);
        link.href = 'https://github.com/lemoz/fort-gym/blob/codex/campaign-codex-subscription/' + row.evidence_path;
      }
    });
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
    $('keyboard-status').textContent = data.milestones.length || data.interruptions?.length || recoveries.length || data.checkpoint_failures?.length || restarts.length
      ? 'Recorded milestones, failures, recoveries and restarts. This is not a live activity indicator.'
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

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
    if (data.checkpoint_reviews !== undefined && !Array.isArray(data.checkpoint_reviews)) {
      throw new Error('Unsupported checkpoint review evidence');
    }
    const reviews = data.checkpoint_reviews || [];
    if (data.checkpoint_recoveries !== undefined && !Array.isArray(data.checkpoint_recoveries)) {
      throw new Error('Unsupported settled checkpoint recovery evidence');
    }
    const checkpointRecoveries = data.checkpoint_recoveries || [];
    if (data.continuations !== undefined && !Array.isArray(data.continuations)) {
      throw new Error('Unsupported continuation evidence');
    }
    const continuations = data.continuations || [];
    for (const name of ['tail_interruptions', 'tail_recoveries', 'presave_failures', 'partial_failures', 'oom_failures', 'resumed_windows', 'prompt_trials', 'modal_trials', 'save_acceptances']) {
      if (data[name] !== undefined && !Array.isArray(data[name])) {
        throw new Error('Unsupported continuation recovery evidence');
      }
    }
    function renderModalTrial(row) {
      const section = node('section', undefined, results);
      section.className = 'campaign-condition campaign-save-failure';
      const p = row.progress, o = row.last_unsaved_observation;
      node('h3', 'Dialog handling worked · host interruption prevented a save', section);
      const facts = node('dl', undefined, section);
      facts.className = 'campaign-save-facts';
      for (const [label, value] of [
        ['Saved game time', `${count(p.checkpointed_elapsed_ticks)} ticks`],
        ['New unsaved game time', `${count(p.new_committed_unsaved_ticks)} ticks`],
        ['Final uncommitted game time', count(p.final_uncommitted_ticks)],
        ['New model responses', count(p.new_responses)]
      ]) {
        const item = node('div', undefined, facts);
        node('dt', label, item); node('dd', value, item);
      }
      node('p', `${count(p.native_modal_deferrals_verified)} paused-dialog receipts were verified. Astra chose the next inputs and resumed game time. The host later failed to read the exchange directory and stopped the run; the underlying read failure is unknown.`, section);
      node('p', `The final input sent ${count(p.final_input_keys_confirmed)} confirmed keys and requested no time advance, but its final clock receipt is missing. Unknown time is not zero. Checkpoint ${count(p.parent_checkpoint_cursor)} remains the latest save for this attempt.`, section);
      node('p', `${count(p.existing_loss_records)} earlier losses retain at least ${count(p.existing_known_lost_ticks)} lost ticks plus an unknown remainder. This attempt's unsaved time is additional. All ${count(row.usage.new_tokens)} new tokens are included: ${count(row.usage.campaign_tokens)} campaign tokens, ${count(row.usage.all_attempt_tokens)} including historical failed deliveries. Charge: ${cost(row.usage)}.`, section);
      node('p', `Last unsaved observation: ${count(o.population)} living dwarves, ${count(o.recorded_dead_citizens)} recorded deaths, ${count(o.drink_stock)} drinks, ${count(o.completed_farms)} farms, ${count(o.completed_beds)} beds and ${count(o.completed_workshops)} workshops. Food: ${count(o.food_stock)}.`, section);
      node('p', 'Game and VM teardown verified for this recorded attempt. No new save, sustainability result, year-two success or matched model comparison. The later read-retry repair was not tested by this run.', section);
      if (/^experiments\/evidence\/astra_native_keyboard_[a-z0-9_]+\.json$/.test(row.evidence_path)) {
        node('a', 'Read the recorded dialog trial', section).href = 'https://github.com/lemoz/fort-gym/blob/codex/campaign-codex-subscription/' + row.evidence_path;
      }
    }
    function renderPromptTrial(row) {
      const section = node('section', undefined, results);
      section.className = 'campaign-condition campaign-save-failure';
      const p = row.progress;
      node('h3', `Memory experiment interrupted · last saved checkpoint ${count(p.parent_checkpoint_cursor)}`, section);
      node('p', `Astra Medium returned ${count(p.new_responses)} decisions with ${count(p.memory_clears)} empty memory updates. ${count(p.advancing_decisions)} completed decisions advanced time; ${count(p.zero_tick_committed_decisions)} advanced none.`, section);
      node('p', `A liaison dialogue remained open after the model’s key. The harness rejected the clock baseline, then could not complete its save. The ${count(p.new_committed_unsaved_ticks)} new game ticks are unsaved; saved progress remains ${count(p.checkpointed_elapsed_ticks)} ticks.`, section);
      node('p', `All ${count(p.new_tokens)} new tokens are included in ${count(p.campaign_tokens)} campaign tokens, or ${count(p.all_attempt_tokens)} including historical failed deliveries. Model charge: ${cost(row.usage)}.`, section);
      node('p', `The last unsaved observation had ${count(row.counts.population.end)} living dwarves and ${count(row.counts.recorded_dead_citizens.end)} recorded deaths. Food and sustainability remain unproven. This interrupted continuation is not a matched comparison or proof that the memory change improved play.`, section);
      node('p', `The previous ${count(p.existing_loss_records)} losses remain recorded, with at least ${count(p.existing_known_lost_ticks)} lost ticks and an unknown remainder. The original checkpoint is intact. Game and VM stopped.`, section);
      if (/^experiments\/evidence\/astra_native_keyboard_[a-z0-9_]+\.json$/.test(row.evidence_path)) {
        node('a', 'Read the recorded experiment', section).href = 'https://github.com/lemoz/fort-gym/blob/codex/campaign-codex-subscription/' + row.evidence_path;
      }
    }
    function renderOomFailure(row) {
      const section = node('section', undefined, results);
      section.className = 'campaign-condition campaign-save-failure';
      const p = row.progress;
      node('h3', `Memory-related interruption · last saved checkpoint ${count(row.checkpoint_cursor)}`, section);
      const facts = node('dl', undefined, section);
      facts.className = 'campaign-save-facts';
      for (const [label, value] of [
        ['Saved game time', `${count(p.checkpointed_elapsed_ticks)} ticks`],
        ['Confirmed unsaved game time', `${count(p.new_committed_unsaved_ticks)} ticks`],
        ['Final uncommitted game time', count(p.uncommitted_elapsed_ticks)],
        ['Accounted model responses', count(p.accounted_responses)]
      ]) {
        const item = node('div', undefined, facts);
        node('dt', label, item);
        node('dd', value, item);
      }
      node('p', `${count(p.new_model_responses)} new responses produced ${count(p.new_committed_decisions)} committed actions. The final action sent ${count(p.uncommitted_native_keys_confirmed)} confirmed keys but has no clock receipt or final calendar reading. No new save was produced.`, section);
      node('p', 'The container reported an out-of-memory event. A live diagnostic loaded the full trace inside the game container and may have contributed. The exact cause and affected process are unverified. This is an infrastructure failure, not a clean model-performance result or proof of fortress collapse.', section);
      node('p', `Last recorded observation: ${count(p.last_population)} living dwarves and ${count(p.last_recorded_dead)} recorded deaths. These are not measurements after the interruption.`, section);
      node('p', `${count(row.usage.campaign_tokens)} campaign tokens; ${count(row.usage.all_attempt_tokens)} including historical failed deliveries. This attempt used ${count(row.usage.new_tokens)} tokens, all included. Model charge: ${cost(row.usage)}.`, section);
      const details = node('details', undefined, section);
      details.className = 'campaign-details';
      node('summary', 'Inspect interrupted progress and prior losses', details);
      node('p', `This attempt restored checkpoint ${count(row.checkpoint_cursor)} and retained ${count(p.existing_loss_records)} earlier loss records totaling ${count(p.existing_lost_ticks)} ticks. Its ${count(p.new_committed_unsaved_ticks)} newly unsaved ticks are additional; missing terminal game time remains unknown, not zero. The trace reached decision ${count(p.committed_trace_cursor)}, not a saved checkpoint.`, details);
      const resumed = (data.resumed_windows || []).some(item => item.parent_record === row.failure_id);
      node('p', `All prior usage is retained. ${resumed ? 'The following saved window retained this loss, including its unknown terminal time.' : 'Another restart has not been recorded for this attempt.'} Diagnostic changes do not prove sustainable production or year-two survival.`, details);
      node('p', row.teardown_verified === true ? 'Game and VM stopped. Recorded evidence, not a live run.' : 'Teardown unknown.', section);
      if (/^experiments\/evidence\/astra_native_keyboard_[a-z0-9_]+\.json$/.test(row.evidence_path)) {
        node('a', 'Read the interrupted-attempt evidence', section).href = 'https://github.com/lemoz/fort-gym/blob/codex/campaign-codex-subscription/' + row.evidence_path;
      }
    }
    function renderPartialFailure(row) {
      const section = node('section', undefined, results);
      section.className = 'campaign-condition campaign-save-failure';
      const p = row.progress;
      node('h3', `Harness interruption · last saved checkpoint ${count(row.checkpoint_cursor)}`, section);
      const facts = node('dl', undefined, section);
      facts.className = 'campaign-save-facts';
      for (const [label, value] of [
        ['Saved game time', `${count(p.checkpointed_elapsed_ticks)} ticks`],
        ['Unsaved game time', `${count(p.unsaved_new_native_ticks)} ticks`],
        ['Accounted model responses', count(p.accounted_model_responses)]
      ]) {
        const item = node('div', undefined, facts);
        node('dt', label, item);
        node('dd', value, item);
      }
      node('p', `${count(p.new_model_responses)} new model responses produced ${count(p.new_committed_decisions)} committed actions and one additional partial action. The committed actions advanced ${count(p.new_committed_ticks)} ticks; the partial action advanced ${count(p.uncommitted_native_ticks)} more. All ${count(p.unsaved_new_native_ticks)} ticks are unsaved, and all responses remain counted.`, section);
      node('p', 'A dialogue interrupted game time after the model left a menu. The harness checked the interruption against the old screen and rejected it. A save was then requested but remained pending. This is a harness failure, not a recorded fortress collapse.', section);
      node('p', `${count(row.usage.campaign_tokens)} campaign tokens; ${count(row.usage.all_attempt_tokens)} including historical failed deliveries. This failed attempt used ${count(row.usage.new_tokens)} tokens, all included. Model charge: ${cost(row.usage)}.`, section);
      const details = node('details', undefined, section);
      details.className = 'campaign-details';
      node('summary', 'Inspect saved vs. unsaved progress', details);
      node('p', `The committed trace reached decision ${count(p.committed_trace_next_step)} and ${count(p.committed_trace_elapsed_ticks)} elapsed ticks, but the last verified save remains checkpoint ${count(row.checkpoint_cursor)}. The ${count(p.uncommitted_native_ticks)} partial ticks are included in the unsaved total, not added twice.`, details);
      const followingRestart = (data.oom_failures || []).some(item => item.parent_record === row.failure_id);
      node('p', `The earlier ${count(p.inherited_save_loss_restarts)} recorded restarts and ${count(p.inherited_discarded_native_ticks)} lost ticks remain in the history. ${followingRestart ? 'This loss was retained by the following restarted attempt.' : 'No restart has been recorded for this failure yet.'} Preparing or testing a repair does not create a new saved checkpoint.`, details);
      node('p', row.teardown_verified === true ? 'Game and VM stopped. Recorded evidence, not a live run.' : 'Teardown unknown.', section);
      if (/^experiments\/evidence\/astra_native_keyboard_[a-z0-9_]+\.json$/.test(row.evidence_path)) {
        node('a', 'Read the failed-attempt evidence', section).href = 'https://github.com/lemoz/fort-gym/blob/codex/campaign-codex-subscription/' + row.evidence_path;
      }
    }
    function renderPresaveFailure(row) {
      const section = node('section', undefined, results);
      section.className = 'campaign-condition campaign-save-failure';
      const p = row.progress;
      const restarted = restarts.some(item => item.original_failure === row.failure_id);
      node('h3', `${restarted ? 'Save failure before restart' : 'Paused after save failure'} · checkpoint ${count(row.checkpoint_cursor)}`, section);
      const facts = node('dl', undefined, section);
      facts.className = 'campaign-save-facts';
      for (const [label, value] of [
        ['Saved game time', `${count(p.checkpointed_elapsed_ticks)} ticks`],
        ['Unsaved game time', `${count(p.unsaved_new_native_ticks)} ticks`],
        ['Accounted model responses', count(p.accounted_model_responses)]
      ]) {
        const item = node('div', undefined, facts);
        node('dt', label, item);
        node('dd', value, item);
      }
      node('p', `${count(p.new_accepted_decisions)} accepted inputs reached the game, but the save check failed before requesting a save. The trace reached decision ${count(p.observed_trace_next_step)}; there is no checkpoint at that boundary. This is a harness failure, not a recorded fortress collapse.`, section);
      node('p', `${count(row.usage.campaign_tokens)} campaign tokens; ${count(row.usage.all_attempt_tokens)} including historical failed deliveries. The failed window used ${count(row.usage.new_tokens)} tokens, all included. Model charge: ${cost(row.usage)}.`, section);
      const details = node('details', undefined, section);
      details.className = 'campaign-details';
      node('summary', 'Inspect unsaved observations', details);
      const observed = row.observed_unsaved_outcomes;
      const table = node('table', undefined, details);
      table.className = 'campaign-outcome-counts';
      node('caption', 'Start of failed window vs. unsaved final observation', table);
      const heading = node('tr', undefined, node('thead', undefined, table));
      for (const title of ['Metric', 'Start', 'Unsaved end']) node('th', title, heading).scope = 'col';
      const body = node('tbody', undefined, table);
      for (const [key, label] of [
        ['population', 'Living dwarves'], ['food_stock', 'Native-predicate food units'],
        ['drink_stock', 'Existing drink units'], ['completed_farms', 'Completed farm plots'],
        ['completed_beds', 'Installed beds'], ['completed_workshops', 'Completed workshops'],
        ['recorded_dead_citizens', 'Recorded dead citizens']
      ]) {
        const item = node('tr', undefined, body);
        node('th', label, item).scope = 'row';
        node('td', count(observed.counts[key].start), item);
        node('td', count(observed.counts[key].end), item);
      }
      node('p', `${count(observed.food_complete_measurements)} complete food readings and ${count(observed.food_unknown_measurements)} unknown readings across ${count(observed.food_observed_boundaries)} boundaries. These final counts were not saved. Inventory changes do not establish production or sustainability.`, details);
      const fix = (data.save_acceptances || []).find(item => item.original_failure === row.failure_id);
      if (fix) {
        const followup = node('aside', undefined, section);
        followup.className = 'campaign-save-acceptance';
        node('h4', 'Save fix verified', followup);
        node('p', 'A separate paused test reproduced the DFHack status-menu overlay failure, saved with the overlay intact, and reloaded that save in a fresh game process. No model calls or game ticks were used. This did not recover the unsaved progress or restart gameplay.', followup);
        if (/^experiments\/evidence\/native_status_stack_acceptance_[0-9]+\.json$/.test(fix.evidence_path)) {
          node('a', 'Read save/reload verification', followup).href = 'https://github.com/lemoz/fort-gym/blob/codex/campaign-codex-subscription/' + fix.evidence_path;
        }
      }
      node('p', restarted
        ? 'A later recorded restart preserves this failed-window usage and records the lost game time. The original failure remains part of this fortress history.'
        : 'Resuming requires a recorded restart from the saved checkpoint, retaining all failed-window usage and recording the lost game time. No restart is recorded for this failure yet.', section);
      node('p', row.teardown_verified === true ? 'Game and VM stopped. Recorded evidence, not a live run.' : 'Teardown unknown.', section);
      if (/^experiments\/evidence\/astra_native_keyboard_[a-z0-9_]+\.json$/.test(row.evidence_path)) {
        node('a', 'Read the original failed-attempt evidence', section).href = 'https://github.com/lemoz/fort-gym/blob/codex/campaign-codex-subscription/' + row.evidence_path;
      }
    }
    function renderTailInterruption(row) {
      const recovered = (data.tail_recoveries || []).find(item => item.original_interruption === row.interruption_id);
      const section = node('section', undefined, results);
      section.className = 'campaign-condition';
      const p = row.progress;
      node('h3', `Workshop clock interrupted · decision ${count(p.trace_cursor)}`, section);
      node('p', `${count(p.new_returned_model_decisions)} new responses, ${count(p.new_committed_decisions)} committed actions and ${count(p.new_elapsed_ticks)} new ticks. All ${count(p.failed_tail_keys_confirmed)} keys from the final response were delivered, but its clock request advanced zero ticks.`, section);
      node('p', recovered
        ? `Subsequently recovered as checkpoint ${count(recovered.checkpoint_cursor)} and verified in a fresh game process. The original window remains failed; no actions were replayed.`
        : `Newer game state is retained but needs reconciliation. Last verified checkpoint at failure: ${count(p.latest_verified_checkpoint_cursor)}.`, section);
      node('p', `${count(p.cumulative_model_responses)} accounted responses and ${count(p.trace_elapsed_ticks)} retained trace ticks. ${count(row.usage.campaign_tokens)} campaign tokens; ${count(row.usage.all_attempt_tokens)} including historical failed deliveries. Model charge: ${cost(row.usage)}.`, section);
      node('p', row.teardown_verified === true ? 'Game and VM teardown verified. Harness failure, not a recorded fortress collapse.' : 'Teardown unknown.', section);
      if (/^experiments\/evidence\/astra_native_keyboard_[a-z0-9_]+\.json$/.test(row.evidence_path)) {
        const link = node('a', 'Read the published interruption evidence', section);
        link.href = 'https://github.com/lemoz/fort-gym/blob/codex/campaign-codex-subscription/' + row.evidence_path;
      }
    }
    function renderContinuation(row) {
      const section = node('section', undefined, results);
      section.className = 'campaign-condition';
      const p = row.progress;
      node('h3', `${row.new_restart_performed ? 'Play resumed after restart' : 'Play continued'} · checkpoint ${count(row.checkpoint_cursor)}`, section);
      if (row.operator_observation_warning) {
        const warning = row.operator_observation_warning;
        if (warning.kind === 'terminal_container_observation_error') {
          node('p', `Runner observation warning: a final container check returned exit ${count(warning.command_exit_code)}. The container was then observed stopped with exit 0. The native save and teardown were independently verified. The check's underlying cause is unverified; the original error is retained.`, section);
        } else {
          node('p', `Runner warning: the game completed and saved, but the outer runner failed while checking its exchange directory (exit ${count(warning.command_exit_code)}). The cause is unverified; the original error is retained. This was not a fully clean run.`, section);
        }
      }
      node('p', `${count(p.new_model_calls)} new model decisions, ${count(p.new_elapsed_ticks)} new ticks. ${count(p.retained_elapsed_ticks)} retained ticks toward the 403,200-tick full-year target.`, section);
      node('p', `Verified saves at ${row.checkpoints.map(item => count(item.cursor)).join(', ')}. When this gameplay window ended, its final save still needed a separate fresh-process reload.`, section);
      node('p', `${count(p.cumulative_model_responses)} accounted model responses; ${count(row.usage.campaign_tokens)} campaign tokens, ${count(row.usage.all_attempt_tokens)} including historical failed deliveries. This window used ${count(row.usage.new_tokens)} tokens. Model charge: ${cost(row.usage)}.`, section);
      if (row.new_restart_performed) {
        node('p', `Restored checkpoint ${count(p.parent_checkpoint_cursor)} with its saved model memory and all prior usage retained. No actions were replayed and no gameplay strategy was supplied.`, section);
        node('p', `${count(p.native_save_loss_restarts)} loss records remain: at least ${count(p.confirmed_discarded_native_ticks)} ticks were lost. Total discarded time is Unknown because the previous attempt's final clock was unavailable. This is not uninterrupted play, an independent model comparison, or proof of sustainability.`, section);
      } else {
        node('p', `Model memory and all usage continued without replay or strategy intervention. The earlier ${count(p.discarded_native_ticks)} lost ticks remain recorded. This is the same fortress, not an independent model comparison or proof of sustainability.`, section);
      }
      if (row.execution_counts) {
        const execution = row.execution_counts;
        node('p', `${count(p.new_accepted_decisions)} inputs accepted; ${count(execution.model_input_rejections)} rejected before native dispatch. ${count(execution.requested_elapsed_ticks)} ticks requested, ${count(p.new_elapsed_ticks)} actually advanced. Menu-blocked requests: ${count(execution.menu_deferrals)}; verified clock timeouts: ${count(execution.clock_unavailable_timeouts)}.`, section);
      }
      if (row.outcome_counts) {
        const outcomes = row.outcome_counts;
        const table = node('table', undefined, section);
        table.className = 'campaign-outcome-counts';
        node('caption', 'Observed fortress counts', table);
        const header = node('tr', undefined, node('thead', undefined, table));
        for (const title of ['Metric', 'Before', 'After']) node('th', title, header).scope = 'col';
        const body = node('tbody', undefined, table);
        for (const [key, label] of [
          ['population', 'Living dwarves'], ['completed_farms', 'Completed farm plots'],
          ['completed_beds', 'Installed beds'], ['completed_workshops', 'Completed workshops'],
          ['recorded_dead_citizens', 'Recorded dead citizens'], ['drink_units', 'Existing drink units']
        ]) {
          const item = node('tr', undefined, body);
          node('th', label, item).scope = 'row';
          node('td', count(outcomes.counts[key].start), item);
          node('td', count(outcomes.counts[key].end), item);
        }
        const foodStatus = row.food_inventory
          ? 'Separate native food measurements are shown below.' : 'Food stocks are unverified.';
        node('p', `${count(outcomes.advancing_decisions)} decisions advanced game time; ${count(outcomes.zero_tick_decisions)} did not advance it. ${foodStatus} Production and consumption were not measured; sustainability is not established.`, section);
      }
      if (row.food_inventory) {
        const food = row.food_inventory;
        node('h4', 'Measured food inventory', section);
        node('p', `Native-predicate food units: ${count(food.initial_units)} at window start (checkpoint ${count(food.initial_checkpoint_cursor)}); ${count(food.final_units)} at window end. Drinks are excluded.`, section);
        node('p', `${count(food.complete_measurements)} complete readings across ${count(food.observed_boundaries)} observation boundaries; ${count(food.unknown_measurements)} unknown readings. A missing or partial reading is unknown, not zero.`, section);
        node('p', 'These counts use the native raw-edibility predicate, not the older screen estimate. Earlier food unknowns remain unknown. Accessibility was not assessed; inventory counts do not establish production, consumption or sustainability.', section);
      }
      node('p', row.teardown_verified === true ? 'Game and VM teardown verified. Recorded result, not a running campaign.' : 'Teardown unknown.', section);
      if (/^experiments\/evidence\/astra_native_keyboard_[a-z0-9_]+\.json$/.test(row.evidence_path)) {
        const link = node('a', 'Read the published continuation evidence', section);
        link.href = 'https://github.com/lemoz/fort-gym/blob/codex/campaign-codex-subscription/' + row.evidence_path;
      }
    }
    function renderRestart(row) {
      const section = node('section', undefined, results);
      section.className = 'campaign-condition';
      const p = row.progress;
      node('h3', `New branch saved · checkpoint ${count(p.checkpoint_cursor)}`, section);
      node('p', `${count(p.new_accepted_decisions)} new accepted decisions after restarting from checkpoint ${count(p.restored_checkpoint_cursor)}. Verified game save: ${count(p.retained_elapsed_ticks)} retained elapsed ticks, including ${count(p.new_elapsed_ticks)} new ticks.`, section);
      if (p.new_elapsed_ticks === 0) node('p', 'This window added no game time. A successful save is not progress toward the next game year.', section);
      node('p', `Total discarded game time remains ${count(p.discarded_native_ticks)} ticks. Astra chose new actions; no historical action was replayed. This is not uninterrupted play or an independent comparison attempt.`, section);
      node('p', `${count(p.cumulative_model_responses)} total accounted model responses. The new branch cursor is ${count(p.checkpoint_cursor)} because it replaces the lost branch, not its usage.`, section);
      node('p', `${count(row.usage.campaign_tokens)} campaign tokens; ${count(row.usage.all_attempt_tokens)} including historical failed deliveries. This segment used ${count(row.usage.new_tokens)} tokens. The lost tail's ${count(row.usage.lost_tail_tokens_retained)} tokens are still included. Model charge: ${cost(row.usage)}.`, section);
      node('p', row.teardown_verified === true ? 'Game and VM teardown verified. Recorded result, not a running campaign.' : 'Teardown unknown.', section);
      if (/^experiments\/evidence\/astra_native_keyboard_[a-z0-9_]+\.json$/.test(row.evidence_path)) {
        const link = node('a', 'Read the published restart evidence', section);
        link.href = 'https://github.com/lemoz/fort-gym/blob/codex/campaign-codex-subscription/' + row.evidence_path;
      }
    }
    const recent = {
      continuation: continuations.map(row => ({id: row.continuation_id, row})),
      interruption: (data.tail_interruptions || []).map(row => ({id: row.interruption_id, row})),
      recovery: (data.tail_recoveries || []).map(row => ({id: row.recovery_id, row})),
      presave_failure: (data.presave_failures || []).map(row => ({id: row.failure_id, row})),
      partial_failure: (data.partial_failures || []).map(row => ({id: row.failure_id, row})),
      oom_failure: (data.oom_failures || []).map(row => ({id: row.failure_id, row})),
      resumed: (data.resumed_windows || []).map(row => ({id: row.resumed_id, row})),
      prompt_trial: (data.prompt_trials || []).map(row => ({id: row.trial_id, row})),
      modal_trial: (data.modal_trials || []).map(row => ({id: row.trial_id, row})),
      restart: restarts.filter(row => row.recent_event === true).map(row => ({id: row.restart_id, row}))
    };
    const events = data.continuation_events || Object.entries(recent).flatMap(([kind, rows]) => rows.map(row => ({kind, id: row.id})));
    if (!Array.isArray(events)) throw new Error('Unsupported continuation order');
    const seen = new Set();
    for (const event of events.slice().reverse()) {
      const found = recent[event.kind]?.find(item => item.id === event.id);
      const identity = `${event.kind}:${event.id}`;
      if (!found || seen.has(identity)) throw new Error('Invalid continuation order');
      seen.add(identity);
      if (event.kind === 'continuation' || event.kind === 'resumed') renderContinuation(found.row);
      else if (event.kind === 'interruption') renderTailInterruption(found.row);
      else if (event.kind === 'presave_failure') renderPresaveFailure(found.row);
      else if (event.kind === 'partial_failure') renderPartialFailure(found.row);
      else if (event.kind === 'oom_failure') renderOomFailure(found.row);
      else if (event.kind === 'prompt_trial') renderPromptTrial(found.row);
      else if (event.kind === 'modal_trial') renderModalTrial(found.row);
      else if (event.kind === 'restart') renderRestart(found.row);
      else renderRecovery(found.row);
    }
    if (seen.size !== Object.values(recent).reduce((n, rows) => n + rows.length, 0)) {
      throw new Error('Incomplete continuation order');
    }
    reviews.slice().reverse().forEach(row => {
      const recovered = checkpointRecoveries.find(item => item.original_review === row.review_id);
      if (recovered) renderRecovery(recovered);
      const section = node('section', undefined, results);
      section.className = 'campaign-condition';
      const p = row.progress;
      node('h3', `Checkpoint verification stopped · decision ${count(p.trace_cursor)}`, section);
      const identityFailure = row.terminal_reason === 'native_menu_identity_changed_during_save';
      node('p', `${count(p.new_accepted_decisions)} new accepted decisions and ${count(p.new_elapsed_ticks)} new ticks reached the game. ${identityFailure ? 'Menu identity' : 'The screen'} changed during saving, so checkpoint verification stopped.`, section);
      node('p', recovered
        ? `Subsequently recovered as checkpoint ${count(recovered.checkpoint_cursor)} and verified in a fresh game process, without replay. This original validation failure remains recorded. At the failure, the last verified checkpoint was ${count(p.latest_verified_checkpoint_cursor)} and the retained trace: ${count(p.trace_elapsed_ticks)} ticks.`
        : `At this failure, a changed game save was retained${identityFailure ? ' inside the stopped runtime' : ''} without a verified campaign checkpoint. Last verified checkpoint at failure: ${count(p.latest_verified_checkpoint_cursor)}, ${count(p.last_verified_elapsed_ticks)} ticks; retained trace: ${count(p.trace_elapsed_ticks)} ticks.`, section);
      if (identityFailure) node('p', 'Recorded world observations stayed unchanged during saving. The original rejected operation did not retain its raw receipt, so its exact menu-field change was not captured.', section);
      node('p', `${count(p.cumulative_model_responses)} accounted model responses; ${count(row.usage.campaign_tokens)} campaign tokens, ${count(row.usage.all_attempt_tokens)} including historical failed deliveries. This segment used ${count(row.usage.new_tokens)} tokens. Model charge: ${cost(row.usage)}.`, section);
      node('p', row.teardown_verified === true ? 'Game and VM teardown verified. A harness validation failure, not a recorded fortress collapse.' : 'Teardown unknown.', section);
      if (/^experiments\/evidence\/astra_native_keyboard_[a-z0-9_]+\.json$/.test(row.evidence_path)) {
        const link = node('a', 'Read the published checkpoint review', section);
        link.href = 'https://github.com/lemoz/fort-gym/blob/codex/campaign-codex-subscription/' + row.evidence_path;
      }
    });
    restarts.filter(row => row.recent_event !== true).slice().reverse().forEach(renderRestart);
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
      node('p', row.recovery_kind === 'clock_tail'
        ? 'The latest native state passed a fresh game reload. The original zero-tick clock failure, all accounted responses and the earlier lost branch remain recorded. No additional game progress was lost.'
        : row.recovery_kind === 'settled_checkpoint'
        ? 'The checkpoint passed a fresh game reload. Save validation now checks unchanged menu identity and world observations while retaining the animated screen captures. The original validation failure and earlier lost branch remain recorded; no additional progress was lost.'
        : 'The original interrupted window remains failed. This checkpoint was verified at this point in the campaign; later records determine the latest resumable state. It does not prove that a new run has started.', section);
      if (row.snapshot_profile === 'native_menu_preserving_save/v3') {
        node('p', 'Menu selection is verified again after the save call returns, when the native selection helper is consistent. The transient helper reading remains recorded; the world-state checks are unchanged.', section);
      }
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
    $('keyboard-status').textContent = data.milestones.length || data.interruptions?.length || recoveries.length || data.checkpoint_failures?.length || restarts.length || reviews.length || checkpointRecoveries.length || continuations.length
      ? 'Recorded play, failures, recoveries and restarts. This is not a live activity indicator.'
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

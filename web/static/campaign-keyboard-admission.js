(function () {
  'use strict';
  const box = document.getElementById('keyboard-admission');
  if (!box) return;
  let busy = false;
  function node(tag, text) {
    const element = document.createElement(tag);
    element.textContent = text;
    box.append(element);
    return element;
  }
  async function refresh() {
    if (busy || document.hidden) return;
    busy = true;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 5000);
    try {
      const response = await fetch('/public/keyboard-admission', {cache: 'no-store', signal: controller.signal});
      if (!response.ok) throw new Error('Unavailable');
      const data = await response.json();
      if (data.schema_version !== 'fortgym.public-keyboard-admission/v1'
          || data.recorded_only !== true || data.status !== 'budget_limited_pause'
          || data.reason !== 'included_usage_headroom_threshold' || data.phase !== 'before_vm_start'
          || data.vm_started !== false || data.game_started !== false
          || data.api_fallback_used !== false || data.usage_reset_used !== false
          || data.new_model_calls !== 0 || data.new_tokens !== 0 || data.new_game_ticks !== 0
          || data.checkpoint_unchanged !== true || data.reported_charge_usd !== null
          || !Number.isSafeInteger(data.checkpoint_cursor) || data.checkpoint_cursor < 0) {
        throw new Error('Invalid recorded admission');
      }
      box.replaceChildren();
      node('h3', 'Recorded launch pause · subscription allowance');
      node('p', `The attempted continuation from checkpoint ${data.checkpoint_cursor} stopped at the harness’s included-usage cutoff, before starting the VM or game. It made 0 model calls and used 0 new model tokens. The saved fortress is unchanged.`);
      node('p', 'This was not a gameplay failure or a dollar-budget overrun. It is a recorded attempt, not a live account-quota reading. No paid fallback or usage reset was used.');
      const path = data.evidence_path;
      if (/^experiments\/evidence\/[a-z0-9_]+\.json$/.test(path)) {
        node('a', 'Read the recorded admission evidence').href = 'https://github.com/lemoz/fort-gym/blob/codex/campaign-codex-subscription/' + path;
      }
      box.hidden = false;
    } catch (_) {
      box.replaceChildren();
      node('p', 'Recorded launch status is unavailable. Saved campaign results remain below.');
      box.hidden = false;
    } finally {
      clearTimeout(timer);
      busy = false;
    }
  }
  document.getElementById('refresh-keyboard-live')?.addEventListener('click', refresh);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
  refresh();
}());

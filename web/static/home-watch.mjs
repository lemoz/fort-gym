import {decodeScreen, frameIndex, liveState, validateRecording, renderCapturedScreen, initialRecording, recoverySummary, readLiveStatus, campaignSummary, campaignHistory} from './home-watch-model.mjs?v=20260911-year-two';
const $ = id => document.getElementById('watch-' + id);
const root = $('root');
if (root) {
  let recording = null, catalog = [], index = 0, playing = null, generation = 0;
  let latestLive = null, mode = 'replay', autoLive = true, liveFrames = [], liveRun = null;
  let loading = false, pollBusy = false;
  const cache = new Map(), canvas = $('canvas');
  const text = (id, value) => { $(id).textContent = value; };
  async function json(url) {
    const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), 10000);
    try {
      const result = await fetch(url, {cache:'no-store', signal:controller.signal});
      if (!result.ok) throw Error('Unavailable');
      return await result.json();
    } finally { clearTimeout(timeout); }
  }
  function stop() { clearInterval(playing); playing = null; text('play','Play'); $('play').setAttribute('aria-pressed','false'); }
  function moves(frames, current, live) {
    $('moves').replaceChildren();
    const start = Math.max(0, current - 3);
    frames.slice(start,current + 1).reverse().forEach((frame, n) => {
      const li = document.createElement('li'), button = document.createElement('button');
      button.type = 'button';
      button.textContent = '#' + frame.decision + ' · ' + (frame.action?.intent || 'Awaiting response');
      button.addEventListener('click', () => {
        stop();
        if (live) { autoLive = false; mode = 'live-history'; index = current - n; }
        else index = current - n;
        render();
      });
      li.append(button); $('moves').append(li);
    });
  }
  function render() {
    const live = mode !== 'replay';
    const frames = live ? liveFrames : recording?.frames;
    if (!frames?.length) return;
    if (mode === 'live') index = frames.length - 1;
    index = frameIndex(index, frames.length);
    const frame = frames[index];
    renderCapturedScreen(canvas, frame.screen, frame.decision);
    text('badge', mode === 'live' ? 'LIVE · latest model decision' : mode === 'live-history' ? 'LIVE SESSION · earlier decision' : recording.recovery ? 'RECOVERED RUN' : 'RECORDED RUN');
    $('badge').dataset.live = String(mode === 'live');
    text('title', live ? latestLive.model : recording.title);
    text('decision', 'Decision ' + frame.decision + (live ? '' : ' / ' + recording.last_decision));
    text('intent', frame.action?.intent || 'Waiting for a completed model response.');
    text('intent-label', 'Model’s stated intent');
    $('keys').replaceChildren();
    for (const key of frame.action?.keys || []) {
      const chip = document.createElement('code'); chip.textContent = key === ' ' ? 'SPACE' : key;
      $('keys').append(chip);
    }
    text('execution', live ? frame.action_status === 'rejected'
      ? 'Model command rejected. No keys were sent to the game.'
      : 'Chosen keys. This feed does not yet verify their execution.'
      : frame.accepted ? 'Key command accepted by the harness. Acceptance does not prove the intended outcome.'
      : 'Key command was not accepted.');
    text('population', live ? '—' : String(frame.after.population));
    text('advance', live ? '—' : frame.after.ticks_advanced.toLocaleString());
    text('clock', live ? 'Screen captured ' + new Date(frame.captured_at_unix * 1000).toLocaleTimeString()
      : 'Screen before action: year ' + frame.before.year + ', tick ' + frame.before.tick.toLocaleString());
    text('boundary', live ? 'Live observations are provisional, not a verified save.'
      : frame.decision > recording.saved_through_decision
        ? 'UNSAVED TAIL · observed actions after checkpoint ' + recording.saved_through_decision + '. The final save failed.'
        : 'This decision precedes or reaches saved checkpoint ' + recording.saved_through_decision + '.');
    $('boundary').className = 'watch-note' + (!live && frame.decision > recording.saved_through_decision ? ' watch-error' : '');
    const recovered = !live && Boolean(recording.recovery), outcome = !live && Boolean(recording.campaign);
    $('recovery').hidden = $('prior').hidden = !(recovered || outcome);
    text('recovery', outcome ? campaignHistory(recording) : recovered ? recoverySummary(recording) : '');
    const prior = outcome ? recording.campaign.source_recording_id : recovered ? recording.recovery.source_recording_id : null;
    $('prior').href = prior ? '/?recording=' + encodeURIComponent(prior) + '#watch-root' : '#watch-root';
    text('prior', outcome ? 'View the preceding continuation →' : 'View the earlier failed window →');
    $('outcome').hidden = !outcome;
    text('outcome-summary', outcome ? campaignSummary(recording) : '');
    $('result').href = outcome ? recording.campaign.result_url : '#watch-root';
    $('reload').href = outcome ? recording.campaign.reload_url : '#watch-root';
    $('range').max = String(frames.length - 1); $('range').value = String(index);
    $('range').setAttribute('aria-valuetext', 'Decision ' + frame.decision);
    $('range').disabled = loading;
    $('prev').disabled = loading || index === 0;
    $('next').disabled = loading || index === frames.length - 1;
    $('play').disabled = loading || live || frames.length < 2;
    $('speed').disabled = live;
    text('caption', live ? 'Sampled at completed decisions, not video. Refreshes while the observer is connected.'
      : 'Drag the timeline or use the arrow buttons. Screen is before the action; population and elapsed ticks are measured after it.');
    moves(frames,index,live);
    $('live').setAttribute('aria-pressed',String(mode === 'live'));
    for (const button of $('runs').querySelectorAll('[data-recording]'))
      button.setAttribute('aria-pressed',String(!live && button.dataset.recording === recording?.id));
  }
  async function select(id, manual = true) {
    const item = catalog.find(row => row.id === id);
    if (!item) return;
    if (manual) autoLive = false;
    stop(); mode = 'replay'; const mine = ++generation; loading = true;
    text('load-status','Loading recording…');
    if (recording) render();
    try {
      const data = cache.get(id) || validateRecording(await json('/static/recordings/' + id + '.json'));
      if (data.id !== id) throw Error('Wrong recording');
      cache.set(id,data);
      if (mine !== generation) return;
      recording = data; index = 0; text('load-status','');
    } catch (_) {
      if (mine === generation) text('load-status','Recording unavailable. Try another run.');
    } finally {
      if (mine === generation) { loading = false; render(); }
    }
  }
  function step(delta) {
    stop(); autoLive = false; if (mode === 'live') mode = 'live-history';
    index += delta; render();
  }
  $('prev').addEventListener('click', () => step(-1));
  $('next').addEventListener('click', () => step(1));
  $('range').addEventListener('input', event => {
    stop(); autoLive = false; if (mode === 'live') mode = 'live-history';
    index = Number(event.target.value); render();
  });
  $('play').addEventListener('click', () => {
    if (playing) { stop(); return; }
    if (!recording || mode !== 'replay') return;
    if (index === recording.frames.length - 1) index = 0;
    text('play','Pause'); $('play').setAttribute('aria-pressed','true'); render();
    playing = setInterval(() => {
      index += 1; render();
      if (index === recording.frames.length - 1) stop();
    }, 1000 / Number($('speed').value));
  });
  $('speed').addEventListener('change', stop);
  $('zoom').addEventListener('click', () => {
    const zoomed = $('screen').dataset.zoom !== 'true';
    $('screen').dataset.zoom = String(zoomed);
    $('zoom').setAttribute('aria-pressed',String(zoomed));
    text('zoom',zoomed ? 'Fit screen' : 'Enlarge');
  });
  $('screen').addEventListener('keydown', event => {
    if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
      event.preventDefault(); step(event.key === 'ArrowLeft' ? -1 : 1);
    }
  });
  function freshness() {
    let state = 'not_connected';
    if (latestLive) state = liveState(latestLive);
    const active = state === 'running' && latestLive.frame;
    $('live').hidden = !active;
    text('connection', state === 'running' ? active ? 'Session broadcasting · latest completed decision' : 'Session connected · waiting for first decision'
      : state === 'stale' ? 'Live connection expired · showing recordings'
      : state === 'stopped' ? 'Session ended · explore the recordings'
      : 'No live broadcast connected · explore a recent run');
    if (!active && mode !== 'replay') { mode = 'replay'; index = 0; stop(); render(); }
    return active;
  }
  $('live').addEventListener('click', () => {
    if (!freshness()) return;
    autoLive = true; stop(); mode = 'live'; render();
  });
  async function poll() {
    if (pollBusy || document.hidden) return;
    pollBusy = true;
    try {
      const data = await readLiveStatus(json);
      liveState(data);
      if (data.frame) decodeScreen(data.frame.screen);
      latestLive = data;
      if (freshness()) {
        if (liveRun !== data.run_id) { liveRun = data.run_id; liveFrames = []; }
        if (!liveFrames.length || liveFrames.at(-1).decision !== data.frame.decision)
          liveFrames.push(data.frame);
        else liveFrames[liveFrames.length - 1] = data.frame;
        if (liveFrames.length > 128) liveFrames.shift();
        if (autoLive) { stop(); mode = 'live'; render(); }
      }
    } catch (_) {
      freshness();
      if (!latestLive) text('connection','Live status unavailable · recordings still work');
    } finally { pollBusy = false; }
  }
  document.addEventListener('visibilitychange', () => { stop(); if (!document.hidden) { freshness(); poll(); } });
  async function start() {
    try {
      const data = await json('/static/recordings/catalog.json');
      if (data.schema_version !== 'fortgym.watch-catalog/v1' || !Array.isArray(data.recordings) ||
          !data.recordings.length || !data.recordings.every(row => /^[a-z0-9-]+$/.test(row.id))) throw Error('Invalid catalog');
      catalog = data.recordings;
      catalog.forEach(item => {
        const button = document.createElement('button');
        button.type = 'button'; button.dataset.recording = item.id;
        button.textContent = item.title + ' · ' + item.window;
        button.setAttribute('aria-pressed','false');
        button.addEventListener('click', () => select(item.id));
        $('runs').append(button);
      });
      const initial = initialRecording(catalog, globalThis.location?.search || '');
      await select(initial.id,initial.explicit);
    } catch (_) { text('load-status','Recordings unavailable. Try reloading or opening Runs.'); }
    await poll();
  }
  setInterval(poll,10000);
  setInterval(freshness,1000);
  start();
}

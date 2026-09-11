// Pure replay helpers shared by the homepage and contract tests.
export const PALETTE = ['#000000','#000080','#008000','#008080','#800000','#800080','#808000','#c0c0c0',
  '#808080','#0000ff','#00ff00','#00ffff','#ff0000','#ff00ff','#ffff00','#ffffff'];
const LOW = ' ☺☻♥♦♣♠•◘○◙♂♀♪♫☼►◄↕‼¶§▬↨↑↓→←∟↔▲▼';
const HIGH = 'ÇüéâäàåçêëèïîìÄÅÉæÆôöòûùÿÖÜ¢£¥₧ƒáíóúñÑªº¿⌐¬½¼¡«»░▒▓│┤╡╢╖╕╣║╗╝╜╛┐└┴┬├─┼╞╟╚╔╩╦╠═╬╧╨╤╥╙╘╒╓╫╪┘┌█▄▌▐▀αßΓπΣσµτΦΘΩδ∞φε∩≡±≥≤⌠⌡÷≈°∙·√ⁿ²■ ';
export function glyph(code) {
  if (!Number.isInteger(code) || code < 0 || code > 255) throw Error('Invalid glyph');
  return code < 32 ? LOW[code] : code === 127 ? '⌂' : code < 127 ? String.fromCharCode(code) : HIGH[code - 128];
}
export function decodeScreen(screen) {
  const {width, height, tile_order: order, runs} = screen || {};
  if (!Number.isInteger(width) || !Number.isInteger(height) || width < 1 || width > 240 ||
      height < 1 || height > 100 || order !== 'column_major' || !Array.isArray(runs) ||
      runs.length > width * height) throw Error('Invalid screen');
  const tiles = [];
  for (const run of runs) {
    if (!Array.isArray(run) || run.length !== 4 || !run.every(Number.isInteger) ||
        run[0] < 1 || run[0] + tiles.length > width * height || run[1] < 0 || run[1] > 255 ||
        run[2] < 0 || run[2] > 15 || run[3] < 0 || run[3] > 15) throw Error('Invalid screen run');
    for (let n = 0; n < run[0]; n++) tiles.push(run.slice(1));
  }
  if (tiles.length !== width * height) throw Error('Incomplete screen');
  return tiles;
}
export function frameIndex(value, length) {
  return Math.max(0, Math.min(length - 1, Math.round(Number(value) || 0)));
}
export function renderCapturedScreen(canvas, screen, decision) {
  const tiles = decodeScreen(screen), h = screen.height;
  const ctx = canvas.getContext('2d');
  if (!ctx) throw Error('Canvas unavailable');
  canvas.width = screen.width * 10; canvas.height = h * 16;
  ctx.font = '14px Menlo, Consolas, monospace'; ctx.textBaseline = 'top';
  tiles.forEach(([code, fg, bg], n) => {
    const x = Math.floor(n / h) * 10, y = (n % h) * 16;
    ctx.fillStyle = PALETTE[bg]; ctx.fillRect(x,y,10,16);
    if (code && code !== 32) { ctx.fillStyle = PALETTE[fg]; ctx.fillText(glyph(code),x,y,10); }
  });
  canvas.setAttribute('aria-label', 'Captured Dwarf Fortress screen before decision ' + decision);
}
export function initialRecording(catalog, search = '') {
  const requested = new URLSearchParams(search).get('recording');
  const selected = catalog.find(row => row.id === requested);
  return {id: (selected || catalog[0]).id, explicit: Boolean(selected)};
}
export function liveState(value, now = Date.now() / 1000) {
  if (value?.schema_version !== 'fortgym.watch-live/v1' ||
      !['not_connected','running','stopped','stale'].includes(value.status)) throw Error('Invalid live feed');
  if (value.status === 'not_connected') return value.status;
  if (!Number.isSafeInteger(value.observed_at_unix) || value.observed_at_unix < 1 ||
      value.observed_at_unix > now + 5 || value.fresh_for_seconds !== 30) throw Error('Invalid live clock');
  return now - value.observed_at_unix > 30 ? 'stale' : value.status;
}
export function validateRecording(data) {
  const count = value => Number.isSafeInteger(value) && value >= 0;
  if (data?.schema_version !== 'fortgym.watch-recording/v1' || !Array.isArray(data.frames) ||
      !data.frames.length || data.frames.length > 1024 ||
      !/^[a-z0-9-]+$/.test(data.id) || typeof data.title !== 'string' || data.title.length > 160 ||
      !count(data.first_decision) || data.first_decision < 1 || !count(data.last_decision) ||
      !count(data.saved_through_decision) || data.saved_through_decision > data.last_decision ||
      data.last_decision - data.first_decision + 1 !== data.frames.length) throw Error('Invalid recording');
  validateRecovery(data);
  data.frames.forEach((frame, index) => {
    if (frame.decision !== data.first_decision + index) throw Error('Nonconsecutive recording');
    decodeScreen(frame.screen);
    if (typeof frame.action?.intent !== 'string' || !Array.isArray(frame.action.keys) ||
        frame.action.intent.length > 2000 || frame.action.keys.length > 128 ||
        !frame.action.keys.every(key => typeof key === 'string' && key.length <= 100) ||
        !count(frame.action.advance_ticks) || !count(frame.before?.year) || !count(frame.before?.tick) ||
        !count(frame.after?.year) || !count(frame.after?.tick) || !count(frame.after?.population) ||
        !count(frame.after?.ticks_advanced) ||
        typeof frame.accepted !== 'boolean') throw Error('Invalid recorded action');
  });
  return data;
}

export function validateRecovery(data) {
  const value = data.recovery;
  if (value === undefined) return null;
  const count = n => Number.isSafeInteger(n) && n >= 0;
  if (!value || value.schema_version !== 'fortgym.watch-recovery/v1' ||
      ![value.restored_checkpoint,value.lost_decisions,value.lost_ticks,value.total_responses].every(count) ||
      value.restored_checkpoint < 1 || value.lost_decisions < 1 ||
      data.first_decision !== value.restored_checkpoint + 1 ||
      value.total_responses < data.last_decision + value.lost_decisions ||
      value.uninterrupted_campaign !== false || value.actions_replayed !== false ||
      typeof value.source_recording_id !== 'string' || typeof value.source_checkpoint_sha256 !== 'string' ||
      !/^[a-z0-9-]{1,100}$/.test(value.source_recording_id) || value.source_recording_id === data.id ||
      !/^[a-f0-9]{64}$/.test(value.source_checkpoint_sha256)) throw Error('Invalid recovery record');
  return value;
}

export function recoverySummary(data) {
  const value = validateRecovery(data);
  if (!value) return '';
  return 'Resumed from checkpoint ' + value.restored_checkpoint + '. Earlier ' + value.lost_decisions +
    ' decisions and ' + value.lost_ticks.toLocaleString() + ' game ticks were not saved. All ' +
    value.total_responses.toLocaleString() + ' model responses remain counted. No actions were replayed.';
}

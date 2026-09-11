import {renderCapturedScreen} from './home-watch-model.mjs';

export const recordingUrl = id => '/?recording=' + encodeURIComponent(id) + '#watch-root';
export function validateCatalog(data) {
  if (data?.schema_version !== 'fortgym.watch-catalog/v1' || !Array.isArray(data.recordings) ||
      !data.recordings.length || data.recordings.length > 100) throw Error('Invalid recording catalog');
  const ids = new Set();
  for (const row of data.recordings) {
    if (!/^[a-z0-9-]+$/.test(row.id) || ids.has(row.id) || typeof row.title !== 'string' ||
        row.title.length > 160 || typeof row.control_profile !== 'string' ||
        ![row.first_decision,row.last_decision,row.saved_through_decision,row.frame_count].every(Number.isSafeInteger) ||
        row.first_decision < 1 || row.frame_count < 1 || row.frame_count > 1024 ||
        row.last_decision - row.first_decision + 1 !== row.frame_count ||
        row.saved_through_decision < 0 || row.saved_through_decision > row.last_decision)
      throw Error('Invalid recording metadata');
    ids.add(row.id);
  }
  return data.recordings;
}
async function json(request, url) {
  const controller = new AbortController(), timer = setTimeout(() => controller.abort(),10000);
  try {
    const response = await request(url,{signal:controller.signal,cache:'no-store'});
    if (!response.ok) throw Error('Unavailable');
    return await response.json();
  } finally { clearTimeout(timer); }
}
function node(doc, tag, className, text) {
  const element = doc.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}
export async function renderPublishedRecordings(doc = document, request = fetch) {
  const lists = [...doc.querySelectorAll('[data-published-recordings]')], screens = [];
  const set = (id,value) => { const element = doc.getElementById(id); if (element) element.textContent = value; };
  const link = (id,url) => { const element = doc.getElementById(id); if (element) element.href = url; };
  let catalog;
  try {
    catalog = validateCatalog(await json(request,'/static/recordings/catalog.json'));
    for (const list of lists) {
      list.replaceChildren();
      for (const row of catalog) {
        const card = node(doc,'article','published-card');
        const media = node(doc,'a','published-media'); media.href = recordingUrl(row.id);
        media.setAttribute('aria-label','Replay '+row.title);
        const canvas = node(doc,'canvas'); canvas.setAttribute('role','img');
        canvas.setAttribute('aria-label','Captured game-screen preview loading');
        media.append(canvas);
        const copy = node(doc,'div','published-copy');
        const caption = node(doc,'p','published-caption','Loading captured screen…');
        const action = node(doc,'a','fl-link','Open replay →'); action.href = media.href;
        copy.append(node(doc,'h3','',row.title),
          node(doc,'p','','Decisions '+row.first_decision+'–'+row.last_decision+' · '+row.frame_count+' frames'),
          node(doc,'p','published-boundary','Saved through '+row.saved_through_decision+
            (row.last_decision > row.saved_through_decision ? ' · unsaved tail included' : '')),
          caption,action);
        card.append(media,copy); list.append(card);
        screens.push({canvas,caption,id:row.id});
      }
    }
    const latest = catalog[0];
    set('latest-model',latest.title); set('latest-status','Recorded, not live');
    set('latest-step',latest.first_decision+'–'+latest.last_decision);
    set('latest-save',String(latest.saved_through_decision)); set('latest-ranking','Not compared');
    link('latest-link',recordingUrl(latest.id)); link('hero-run-link',recordingUrl(latest.id));
    link('story-link',recordingUrl((catalog[1] || latest).id));
    for (const [prefix,row] of [['story',catalog[1] || latest],['reason',catalog[2] || latest]]) {
      const canvas = doc.getElementById(prefix+'-canvas'), caption = doc.getElementById(prefix+'-source');
      if (canvas && caption) screens.push({canvas,caption,id:row.id});
    }
  } catch (_) {
    for (const list of lists) {
      const message = node(doc,'p','fl-empty','Recording catalog unavailable. ');
      const fallback = node(doc,'a','fl-link','Browse the published recordings →'); fallback.href='/worlds';
      message.append(fallback); list.replaceChildren(message);
    }
    set('latest-model','Recordings unavailable'); set('latest-status','Try the Runs page');
    for (const id of ['latest-step','latest-save','latest-ranking']) set(id,'—');
    set('story-source','Preview unavailable · open Runs'); set('reason-source','Preview unavailable · open Runs');
    return;
  }
  try {
    const previews = await json(request,'/static/recordings/previews.json');
    if (previews.schema_version !== 'fortgym.watch-previews/v1' || !Array.isArray(previews.recordings))
      throw Error('Invalid preview catalog');
    for (const target of screens) {
      try {
        const preview = previews.recordings.find(row => row.id === target.id);
        const entry = catalog.find(row => row.id === target.id);
        if (!preview || preview.recording_sha256 !== entry.sha256 || preview.decision !== entry.first_decision)
          throw Error('Mismatched preview');
        renderCapturedScreen(target.canvas,preview.screen,preview.decision);
        target.caption.textContent = entry.title+' · captured before decision '+preview.decision;
      } catch (_) { target.caption.textContent='Preview unavailable · replay remains available'; }
    }
  } catch (_) {
    for (const target of screens) target.caption.textContent='Preview unavailable · replay remains available';
  }
}
if (typeof document !== 'undefined' && document.querySelector('[data-published-recordings]'))
  renderPublishedRecordings();

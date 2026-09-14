import {renderCapturedScreen} from './home-watch-model.mjs';

// Cards and replay links are already in the HTML, independent of either API.
export async function loadRecordingPreviews(doc = document, request = fetch) {
  const cards = [...doc.querySelectorAll('[data-recording-preview]')];
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 10000);
  try {
    const response = await request('/static/recordings/previews.json', {signal:controller.signal});
    if (!response.ok) throw Error('Previews unavailable');
    const data = await response.json();
    if (data.schema_version !== 'fortgym.watch-previews/v1' || !Array.isArray(data.recordings))
      throw Error('Invalid previews');
    for (const card of cards) {
      const label = card.querySelector('[data-preview-status]');
      try {
        const preview = data.recordings.find(row => row.id === card.dataset.recordingPreview);
        if (!preview || !Number.isSafeInteger(preview.decision)) throw Error('Missing preview');
        renderCapturedScreen(card.querySelector('canvas'),preview.screen,preview.decision);
        label.textContent = 'Captured screen · decision ' + preview.decision;
      } catch (_) { label.textContent = 'Preview unavailable · open the replay below'; }
    }
  } catch (_) {
    for (const card of cards)
      card.querySelector('[data-preview-status]').textContent = 'Preview unavailable · open the replay below';
  } finally { clearTimeout(timeout); }
}
if (typeof document !== 'undefined') loadRecordingPreviews();

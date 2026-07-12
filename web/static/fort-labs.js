(function () {
  'use strict';

  const observedCanvases = new WeakSet();
  const resizeObserver = typeof ResizeObserver === 'function'
    ? new ResizeObserver(entries => entries.forEach(entry => entry.target.__fortLabsRender?.()))
    : null;

  function escapeHtml(value) {
    return String(value ?? '')
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#039;');
  }

  function formatNumber(value, digits = 1) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed.toFixed(digits) : '--';
  }

  function statusLabel(status) {
    const value = String(status || 'unknown');
    return value.charAt(0).toUpperCase() + value.slice(1);
  }

  function runUrl(run) {
    return run?.token ? `/r/${encodeURIComponent(run.token)}` : '/live';
  }

  function isActiveStatus(status) {
    return ['pending', 'running', 'paused'].includes(String(status || ''));
  }

  function canWatchLive(run) {
    return run?.status === 'running' && Array.isArray(run.scopes) && run.scopes.includes('live');
  }

  function formatDate(value) {
    if (!value) return 'Date not reported';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return 'Date not reported';
    return new Intl.DateTimeFormat(undefined, {
      month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit'
    }).format(date);
  }

  function sizeCanvas(canvas) {
    const rect = canvas.getBoundingClientRect();
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    const width = Math.max(320, Math.round((rect.width || canvas.clientWidth || 640) * ratio));
    const height = Math.max(180, Math.round((rect.height || canvas.clientHeight || 360) * ratio));
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width;
      canvas.height = height;
    }
  }

  function glyphColor(char) {
    if ('@☺☻'.includes(char)) return '#f1f0e8';
    if ('Wwbdtc'.includes(char)) return '#d9f45b';
    if ('T,s'.includes(char)) return '#7ed18a';
    if ('~i'.includes(char)) return '#68d9d0';
    if ('#X<>^'.includes(char)) return '#b4b8ad';
    if ('!?'.includes(char)) return '#ef756f';
    return '#7d8979';
  }

  function observeCanvas(canvas) {
    if (resizeObserver && !observedCanvases.has(canvas)) {
      observedCanvases.add(canvas);
      resizeObserver.observe(canvas);
    }
  }

  function renderScreenText(canvas, text) {
    const clean = String(text || '').replaceAll('\r', '');
    const render = () => {
      sizeCanvas(canvas);
      const ctx = canvas.getContext('2d');
      const width = canvas.width;
      const height = canvas.height;
      ctx.fillStyle = '#010201';
      ctx.fillRect(0, 0, width, height);
      const lines = clean.split('\n').slice(0, 30);
      if (!lines.some(line => line.trim())) return renderUnavailable(canvas, 'No frame was recorded');
      const cols = Math.max(80, ...lines.map(line => line.length));
      const fontSize = Math.max(8, Math.floor(Math.min(width / (cols * .62), height / Math.max(25, lines.length) / 1.12)));
      const charWidth = fontSize * .62;
      const lineHeight = fontSize * 1.12;
      ctx.font = `700 ${fontSize}px ui-monospace, monospace`;
      ctx.textBaseline = 'top';
      const offsetX = Math.max(6, (width - cols * charWidth) / 2);
      const offsetY = Math.max(6, (height - lines.length * lineHeight) / 2);
      lines.forEach((line, row) => {
        for (let col = 0; col < line.length; col += 1) {
          const char = line[col];
          if (char === ' ') continue;
          ctx.fillStyle = glyphColor(char);
          ctx.fillText(char, offsetX + col * charWidth, offsetY + row * lineHeight);
        }
      });
      canvas.setAttribute('aria-label', 'Recorded Dwarf Fortress gameplay frame');
    };
    canvas.__fortLabsRender = render;
    observeCanvas(canvas);
    render();
  }

  function renderScreenTiles(canvas, data) {
    if (!data || !Array.isArray(data.tiles) || !data.width || !data.height) return false;
    const render = () => {
      sizeCanvas(canvas);
      const ctx = canvas.getContext('2d');
      const palette = ['#000','#17354a','#305f35','#28726f','#74362f','#623a62','#75642c','#bbb','#666','#4b83d2','#7ed18a','#68d9d0','#ef756f','#d28bd2','#d9f45b','#f1f0e8'];
      const cellW = canvas.width / data.width;
      const cellH = canvas.height / data.height;
      ctx.fillStyle = '#000';
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.font = `700 ${Math.max(7, Math.floor(cellH * .9))}px ui-monospace, monospace`;
      ctx.textBaseline = 'top';
      for (let y = 0; y < data.height; y += 1) {
        for (let x = 0; x < data.width; x += 1) {
          const tile = data.tiles[x * data.height + y];
          if (!Array.isArray(tile)) continue;
          const [code, fg, bg] = tile;
          if (bg) {
            ctx.fillStyle = palette[bg % 16];
            ctx.fillRect(x * cellW, y * cellH, cellW + 1, cellH + 1);
          }
          if (code > 31 && code < 127) {
            ctx.fillStyle = palette[fg % 16];
            ctx.fillText(String.fromCharCode(code), x * cellW, y * cellH);
          }
        }
      }
      canvas.setAttribute('aria-label', 'Live Dwarf Fortress gameplay frame');
    };
    canvas.__fortLabsRender = render;
    observeCanvas(canvas);
    render();
    return true;
  }

  function renderUnavailable(canvas, message = 'No frame was recorded for this moment') {
    const render = () => {
      sizeCanvas(canvas);
      const ctx = canvas.getContext('2d');
      ctx.fillStyle = '#010201';
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.strokeStyle = '#182018';
      ctx.lineWidth = 1;
      for (let x = 0; x <= canvas.width; x += 28) {
        ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, canvas.height); ctx.stroke();
      }
      for (let y = 0; y <= canvas.height; y += 28) {
        ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(canvas.width, y); ctx.stroke();
      }
      ctx.fillStyle = '#7d8979';
      ctx.font = '700 12px ui-monospace, monospace';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(message.toUpperCase(), canvas.width / 2, canvas.height / 2);
      ctx.textAlign = 'start';
      canvas.setAttribute('aria-label', message);
    };
    canvas.__fortLabsRender = render;
    observeCanvas(canvas);
    render();
  }

  async function fetchJson(url, options) {
    const response = await fetch(url, options);
    if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
    return response.json();
  }

  async function loadRunFrame(run, canvas, sourceElement) {
    if (!run?.token) {
      renderUnavailable(canvas);
      return {status: 'not_reported'};
    }
    try {
      const preview = await fetchJson(`/public/runs/${encodeURIComponent(run.token)}/preview`);
      if (preview.screen_status === 'recorded' && preview.screen_text) {
        renderScreenText(canvas, preview.screen_text);
        if (sourceElement) sourceElement.textContent = `Recorded step ${preview.step ?? run.step ?? '--'}`;
        return {status: 'recorded', preview};
      }
      renderUnavailable(canvas);
      if (sourceElement) sourceElement.textContent = 'Frame not recorded';
      return {status: 'not_reported'};
    } catch (_) {
      renderUnavailable(canvas, 'Frame temporarily unavailable');
      if (sourceElement) sourceElement.textContent = 'Frame temporarily unavailable';
      return {status: 'unavailable'};
    }
  }

  function initShell() {
    const button = document.querySelector('[data-fl-menu-button]');
    const menu = document.querySelector('[data-fl-mobile-menu]');
    if (!button || !menu) return;
    const setOpen = open => {
      menu.dataset.open = String(open);
      button.setAttribute('aria-expanded', String(open));
      button.setAttribute('aria-label', open ? 'Close navigation' : 'Open navigation');
      menu.setAttribute('aria-hidden', String(!open));
      button.textContent = open ? '×' : '☰';
      document.body.classList.toggle('menu-open', open);
    };
    button.addEventListener('click', () => setOpen(menu.dataset.open !== 'true'));
    menu.querySelectorAll('a').forEach(link => link.addEventListener('click', () => setOpen(false)));
    window.addEventListener('keydown', event => {
      if (event.key === 'Escape' && menu.dataset.open === 'true') {
        setOpen(false);
        button.focus();
      }
    });
  }

  window.FortLabs = {
    escapeHtml,
    canWatchLive,
    fetchJson,
    formatDate,
    formatNumber,
    initShell,
    isActiveStatus,
    loadRunFrame,
    renderScreenText,
    renderScreenTiles,
    renderUnavailable,
    runUrl,
    statusLabel,
  };
})();

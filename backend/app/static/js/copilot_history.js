// copilot_history.js — Copilot session archive UI (CLI + VS Code local + Crow devices)

(function () {

  // ── State ──────────────────────────────────────────────────────────────────
  let _sessions = [];
  let _searchTimeout = null;

  // ── Init ───────────────────────────────────────────────────────────────────
  function initCopilotHistory() {
    el('chScanBtn').addEventListener('click', triggerScan);
    el('chHarvestBtn').addEventListener('click', triggerHarvest);
    el('chSearchInput').addEventListener('input', function () {
      clearTimeout(_searchTimeout);
      _searchTimeout = setTimeout(() => loadSessions(this.value.trim()), 350);
    });
    el('chSourceFilter').addEventListener('change', function () {
      loadSessions(el('chSearchInput').value.trim());
    });
    el('chDetailClose').addEventListener('click', () => el('chDetailDialog').close());
    loadSessions();
  }

  // ── Load session list ──────────────────────────────────────────────────────
  async function loadSessions(q = '') {
    const grid = el('chSessionGrid');
    grid.innerHTML = '<p class="ch-empty">Loading…</p>';
    try {
      const source = el('chSourceFilter').value;
      let url = `/api/copilot-history/sessions?limit=100`;
      if (q) url += `&q=${encodeURIComponent(q)}`;
      if (source) url += `&source_type=${encodeURIComponent(source)}`;
      const resp = await fetch(url);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      _sessions = data.sessions || [];
      renderGrid(_sessions, data.total || 0);
    } catch (e) {
      grid.innerHTML = `<p class="ch-empty" style="color:var(--red-hi)">Failed to load: ${e.message}</p>`;
    }
  }

  // ── Render grid ────────────────────────────────────────────────────────────
  function renderGrid(sessions, total) {
    const grid = el('chSessionGrid');
    if (!sessions.length) {
      grid.innerHTML = '<p class="ch-empty">No sessions found. Click "Scan Local" to import from this machine, or "Harvest All Devices" to pull from connected Crow devices.</p>';
      return;
    }
    grid.innerHTML = sessions.map(s => sessionCard(s)).join('');
    grid.querySelectorAll('.ch-card').forEach(card => {
      card.addEventListener('click', () => openDetail(card.dataset.id));
    });
    grid.querySelectorAll('.ch-delete-btn').forEach(btn => {
      btn.addEventListener('click', e => { e.stopPropagation(); deleteSession(btn.dataset.id); });
    });
    grid.querySelectorAll('.ch-rename-btn').forEach(btn => {
      btn.addEventListener('click', e => { e.stopPropagation(); inlineRenameCard(btn); });
    });
  }

  const SOURCE_LABELS = {
    cli:        { icon: '🖥', label: 'Copilot CLI',     cls: 'ch-tag' },
    vscode:     { icon: '💻', label: 'VS Code (local)', cls: 'ch-tag ch-tag-vscode' },
    crow_vscode:{ icon: '🪶', label: '',                cls: 'ch-tag ch-tag-crow' },
  };

  function sessionCard(s) {
    const date = s.session_updated_at
      ? new Date(s.session_updated_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
      : '—';
    const repo   = s.repository || '';
    const branch = s.branch || '';
    const embeddedDot = s.embedded
      ? '<span class="ch-dot ch-dot-ok" title="Embedded"></span>'
      : '<span class="ch-dot ch-dot-pending" title="Not yet embedded"></span>';
    const summary = s.ai_summary || s.cli_summary || '';
    const stats = [
      s.user_messages ? `${s.user_messages} turns` : '',
      s.tool_calls    ? `${s.tool_calls} tools`    : '',
    ].filter(Boolean).join(' · ');

    const srcType  = s.source_type || 'cli';
    const srcMeta  = SOURCE_LABELS[srcType] || SOURCE_LABELS.cli;
    const srcLabel = srcType === 'crow_vscode'
      ? `🪶 ${esc(s.source_device_label || 'Crow device')}`
      : `${srcMeta.icon} ${srcMeta.label}`;

    return `
      <div class="ch-card" data-id="${s.session_id}">
        <div class="ch-card-top">
          ${embeddedDot}
          <span class="ch-card-date">${date}</span>
          <button class="ch-delete-btn" data-id="${s.session_id}" title="Remove from index">✕</button>
        </div>
        <h4 class="ch-card-title">${esc(s.title || s.session_id.slice(0, 8))} <button class="ch-rename-btn" data-id="${s.session_id}" data-title="${esc(s.title || '')}" title="Edit title">✏️</button></h4>
        ${summary ? `<p class="ch-card-summary">${esc(summary)}</p>` : ''}
        <div class="ch-card-meta">
          <span class="${srcMeta.cls}">${srcLabel}</span>
          ${repo   ? `<span class="ch-tag">${esc(repo)}</span>`                   : ''}
          ${branch ? `<span class="ch-tag ch-tag-branch">${esc(branch)}</span>`   : ''}
          ${stats  ? `<span class="ch-stats">${esc(stats)}</span>`                : ''}
        </div>
      </div>`;
  }

  // ── Detail dialog ──────────────────────────────────────────────────────────
  async function openDetail(sessionId) {
    const dlg = el('chDetailDialog');
    el('chDetailTitle').textContent = 'Loading…';
    el('chDetailMeta').textContent = '';
    el('chDetailSummary').textContent = '';
    el('chDetailTranscript').innerHTML = '';
    dlg.showModal();

    try {
      const resp = await fetch(`/api/copilot-history/sessions/${sessionId}`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const s = await resp.json();
      el('chDetailTitle').textContent = s.title || s.session_id.slice(0, 8);
      el('chDetailTitle').dataset.id = s.session_id;
      const date = s.session_updated_at ? new Date(s.session_updated_at).toLocaleString() : '—';
      const srcLabel = s.source_type === 'crow_vscode'
        ? `🪶 ${s.source_device_label || 'Crow device'}`
        : s.source_type === 'vscode' ? '💻 VS Code (local)' : '🖥 Copilot CLI';
      el('chDetailMeta').textContent = [srcLabel, s.repository, s.branch, date].filter(Boolean).join(' · ');
      el('chDetailSummary').textContent = s.ai_summary || s.cli_summary || '';
      el('chDetailTranscript').innerHTML = renderTranscript(s.transcript || '');

      // wire rename button in dialog
      const renameBtn = el('chDetailRenameBtn');
      renameBtn.onclick = () => renameSessionDialog(s.session_id, el('chDetailTitle').textContent);
    } catch (e) {
      el('chDetailTitle').textContent = 'Error';
      el('chDetailTranscript').textContent = e.message;
    }
  }

  function renderTranscript(text) {
    if (!text) return '<p class="ch-empty">No transcript available.</p>';
    return text.split('\n\n').map(block => {
      if (block.startsWith('USER: ')) {
        return `<div class="ch-turn ch-turn-user"><span class="ch-role">You</span><p>${esc(block.slice(6))}</p></div>`;
      } else if (block.startsWith('ASSISTANT: ')) {
        return `<div class="ch-turn ch-turn-asst"><span class="ch-role">Copilot</span><p>${esc(block.slice(11))}</p></div>`;
      }
      return block ? `<div class="ch-turn"><p>${esc(block)}</p></div>` : '';
    }).join('');
  }

  // ── Scan local ─────────────────────────────────────────────────────────────
  async function triggerScan() {
    const btn = el('chScanBtn');
    btn.disabled = true;
    btn.textContent = 'Scanning…';
    try {
      const resp = await fetch('/api/copilot-history/scan', { method: 'POST' });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const res = await resp.json();
      const total = (res.ingested || 0) + (res.cli || 0) + (res.vscode || 0);
      btn.textContent = `↺ Done (${total} new)`;
      await loadSessions(el('chSearchInput').value.trim());
    } catch (e) {
      btn.textContent = '↺ Error';
    } finally {
      setTimeout(() => { btn.disabled = false; btn.textContent = '↻ Scan Local'; }, 2500);
    }
  }

  // ── Harvest crow devices ───────────────────────────────────────────────────
  async function triggerHarvest() {
    const btn = el('chHarvestBtn');
    btn.disabled = true;
    btn.textContent = '🪶 Harvesting…';
    try {
      const resp = await fetch('/api/copilot-history/harvest', { method: 'POST' });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const res = await resp.json();
      btn.textContent = `🪶 Done (${res.ingested} new)`;
      await loadSessions(el('chSearchInput').value.trim());
    } catch (e) {
      btn.textContent = '🪶 Error';
    } finally {
      setTimeout(() => { btn.disabled = false; btn.textContent = '🪶 Harvest All Devices'; }, 3000);
    }
  }

  // ── Rename ─────────────────────────────────────────────────────────────────
  async function renameSessionDialog(sessionId, currentTitle) {
    const newTitle = prompt('Rename session:', currentTitle);
    if (newTitle === null || newTitle.trim() === '') return;
    try {
      const resp = await fetch(`/api/copilot-history/sessions/${sessionId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: newTitle.trim() }),
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      // update dialog title in place
      const titleEl = el('chDetailTitle');
      if (titleEl) titleEl.textContent = newTitle.trim();
      // reload grid in background
      loadSessions(el('chSearchInput').value.trim());
    } catch (e) {
      alert('Rename failed: ' + e.message);
    }
  }

  async function inlineRenameCard(btn) {
    const sessionId = btn.dataset.id;
    const currentTitle = btn.dataset.title;
    const newTitle = prompt('Rename session:', currentTitle);
    if (newTitle === null || newTitle.trim() === '') return;
    try {
      const resp = await fetch(`/api/copilot-history/sessions/${sessionId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: newTitle.trim() }),
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      loadSessions(el('chSearchInput').value.trim());
    } catch (e) {
      alert('Rename failed: ' + e.message);
    }
  }

  // ── Delete ─────────────────────────────────────────────────────────────────
  async function deleteSession(sessionId) {
    if (!confirm('Remove this session from the index? (Does not delete the original file.)')) return;
    try {
      await fetch(`/api/copilot-history/sessions/${sessionId}`, { method: 'DELETE' });
      await loadSessions(el('chSearchInput').value.trim());
    } catch (e) {
      alert('Delete failed: ' + e.message);
    }
  }

  // ── Helpers ────────────────────────────────────────────────────────────────
  function esc(s) {
    return String(s || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  // ── Register ───────────────────────────────────────────────────────────────
  window.initCopilotHistory = initCopilotHistory;
  window.loadCopilotHistory = loadSessions;

})();

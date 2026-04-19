// copilot_history.js — Copilot CLI session archive UI

(function () {

  // ── State ──────────────────────────────────────────────────────────────
  let _sessions = [];
  let _searchTimeout = null;

  // ── Init ───────────────────────────────────────────────────────────────
  function initCopilotHistory() {
    el('chScanBtn').addEventListener('click', triggerScan);
    el('chSearchInput').addEventListener('input', function () {
      clearTimeout(_searchTimeout);
      _searchTimeout = setTimeout(() => loadSessions(this.value.trim()), 350);
    });
    el('chDetailClose').addEventListener('click', () => el('chDetailDialog').close());
    loadSessions();
  }

  // ── Load session list ──────────────────────────────────────────────────
  async function loadSessions(q = '') {
    const grid = el('chSessionGrid');
    grid.innerHTML = '<p class="ch-empty">Loading…</p>';
    try {
      const url = q
        ? `/api/copilot-history/sessions?limit=100&q=${encodeURIComponent(q)}`
        : '/api/copilot-history/sessions?limit=100';
      const data = await apiFetch(url);
      _sessions = data.sessions || [];
      renderGrid(_sessions, data.total || 0);
    } catch (e) {
      grid.innerHTML = `<p class="ch-empty" style="color:var(--red-hi)">Failed to load: ${e.message}</p>`;
    }
  }

  // ── Render grid ────────────────────────────────────────────────────────
  function renderGrid(sessions, total) {
    const grid = el('chSessionGrid');
    if (!sessions.length) {
      grid.innerHTML = '<p class="ch-empty">No sessions found. Click "Scan Now" to import from ~/.copilot/session-state/</p>';
      return;
    }
    grid.innerHTML = sessions.map(s => sessionCard(s)).join('');
    // wire click
    grid.querySelectorAll('.ch-card').forEach(card => {
      card.addEventListener('click', () => openDetail(card.dataset.id));
    });
    grid.querySelectorAll('.ch-delete-btn').forEach(btn => {
      btn.addEventListener('click', e => { e.stopPropagation(); deleteSession(btn.dataset.id); });
    });
  }

  function sessionCard(s) {
    const date = s.session_updated_at
      ? new Date(s.session_updated_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
      : '—';
    const repo = s.repository || '';
    const branch = s.branch || '';
    const embeddedDot = s.embedded
      ? '<span class="ch-dot ch-dot-ok" title="Embedded"></span>'
      : '<span class="ch-dot ch-dot-pending" title="Not yet embedded"></span>';
    const summary = s.ai_summary || s.cli_summary || '';
    const stats = [
      s.user_messages ? `${s.user_messages} turns` : '',
      s.tool_calls ? `${s.tool_calls} tools` : '',
    ].filter(Boolean).join(' · ');

    return `
      <div class="ch-card" data-id="${s.session_id}">
        <div class="ch-card-top">
          ${embeddedDot}
          <span class="ch-card-date">${date}</span>
          <button class="ch-delete-btn" data-id="${s.session_id}" title="Remove from index">✕</button>
        </div>
        <h4 class="ch-card-title">${esc(s.title || s.session_id.slice(0, 8))}</h4>
        ${summary ? `<p class="ch-card-summary">${esc(summary)}</p>` : ''}
        <div class="ch-card-meta">
          ${repo ? `<span class="ch-tag">${esc(repo)}</span>` : ''}
          ${branch ? `<span class="ch-tag ch-tag-branch">${esc(branch)}</span>` : ''}
          ${stats ? `<span class="ch-stats">${esc(stats)}</span>` : ''}
        </div>
      </div>`;
  }

  // ── Detail dialog ──────────────────────────────────────────────────────
  async function openDetail(sessionId) {
    const dlg = el('chDetailDialog');
    el('chDetailTitle').textContent = 'Loading…';
    el('chDetailMeta').textContent = '';
    el('chDetailSummary').textContent = '';
    el('chDetailTranscript').innerHTML = '';
    dlg.showModal();

    try {
      const s = await apiFetch(`/api/copilot-history/sessions/${sessionId}`);
      el('chDetailTitle').textContent = s.title || s.session_id.slice(0, 8);
      const date = s.session_updated_at
        ? new Date(s.session_updated_at).toLocaleString()
        : '—';
      el('chDetailMeta').textContent =
        [s.repository, s.branch, date].filter(Boolean).join(' · ');
      el('chDetailSummary').textContent = s.ai_summary || s.cli_summary || '';
      el('chDetailTranscript').innerHTML = renderTranscript(s.transcript || '');
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

  // ── Scan ───────────────────────────────────────────────────────────────
  async function triggerScan() {
    const btn = el('chScanBtn');
    btn.disabled = true;
    btn.textContent = 'Scanning…';
    try {
      const res = await apiFetch('/api/copilot-history/scan', { method: 'POST' });
      btn.textContent = `↺ Done (${res.ingested} new)`;
      await loadSessions(el('chSearchInput').value.trim());
    } catch (e) {
      btn.textContent = '↺ Error';
    } finally {
      setTimeout(() => { btn.disabled = false; btn.textContent = '↺ Scan Now'; }, 2500);
    }
  }

  // ── Delete ─────────────────────────────────────────────────────────────
  async function deleteSession(sessionId) {
    if (!confirm('Remove this session from the index? (Does not delete the original file.)')) return;
    try {
      await apiFetch(`/api/copilot-history/sessions/${sessionId}`, { method: 'DELETE' });
      await loadSessions(el('chSearchInput').value.trim());
    } catch (e) {
      alert('Delete failed: ' + e.message);
    }
  }

  // ── Helpers ────────────────────────────────────────────────────────────
  function esc(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  async function apiFetch(url, opts = {}) {
    const token = state.token;
    const res = await fetch(url, {
      ...opts,
      headers: { ...(opts.headers || {}), ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  }

  // ── Register ───────────────────────────────────────────────────────────
  window.initCopilotHistory = initCopilotHistory;
  window.loadCopilotHistory = loadSessions;

})();

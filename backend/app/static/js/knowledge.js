async function jinaFetchUrl() {
  const raw = el('jinaUrl').value.trim();
  if (!raw) return;
  const isSearch = el('jinaSearchMode').checked;
  const btn = el('jinaFetchBtn');
  btn.disabled = true;
  btn.textContent = 'Fetching…';
  el('jinaStatus').textContent = '';
  try {
    const resp = await fetch('/api/notes/fetch-url', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url: raw, search: isSearch }),
    });
    const out = await resp.json();
    if (!resp.ok) {
      el('jinaStatus').textContent = `Error: ${out.detail || 'fetch failed'}`;
      return;
    }
    el('jinaStatus').textContent = `✓ Imported "${out.title}" — ${out.chunks_indexed} chunks, ${out.chars} chars`;
    el('jinaUrl').value = '';
    await loadNoteList();
    await loadSummary();
  } finally {
    btn.disabled = false;
    btn.textContent = 'Import URL';
  }
}

async function saveNote() {
  const title = el('noteTitle').value.trim();
  const body = el('noteBody').value.trim();
  if (!title || !body) return;

  const resp = await fetch('/api/notes', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title, body }),
  });
  const out = await resp.json();
  el('searchOut').textContent = `Indexed ${out.chunks_indexed} chunks in note ${out.note_id}`;
  await loadSummary();
  await loadNoteList();
}

async function loadNoteList() {
  const resp = await fetch('/api/notes');
  if (!resp.ok) return;
  state.noteList = await resp.json();
  renderNoteList();
}

function renderNoteList() {
  const target = el('noteListContainer');
  if (!target) return;
  target.innerHTML = '';
  if (!state.noteList.length) {
    target.innerHTML = '<div class="tiny" style="color:var(--muted);">No notes saved yet. Use Knowledge Capture or Zen Knowledge Capture above.</div>';
    return;
  }
  state.noteList.forEach((note) => {
    const item = document.createElement('div');
    item.className = 'list-item';
    const preview = (note.body || '').slice(0, 140);
    item.innerHTML = `
      <div><strong>${note.title}</strong></div>
      <div class="tiny mono" style="margin-top:4px;">${preview}${note.body.length > 140 ? '...' : ''}</div>
      <div class="tiny" style="color:var(--muted); margin-top:4px;">${note.created_at}</div>
      <button data-delete-note="${note.id}" class="warn" style="margin-top:6px; width:auto; padding:4px 10px;">Delete</button>
    `;
    target.appendChild(item);
  });
  target.querySelectorAll('button[data-delete-note]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const id = btn.getAttribute('data-delete-note');
      await fetch(`/api/notes/${id}`, { method: 'DELETE' });
      await loadNoteList();
      await loadSummary();
    });
  });
}

async function fetchVsCodeConfig() {
  const resp = await fetch('/api/mcp/vscode-config');
  if (!resp.ok) return;
  const data = await resp.json();
  el('vsCodeRelaySnippet').value = data.snippet || data.relay_only_snippet || '';
  el('vsCodeAllServersSnippet').value = '';
  el('vsCodeRelayUrl').textContent = data.relay_url || '';
  el('vsCodeConfigInstructions').textContent = data.instructions || '';
  el('vsCodeConfigDialog').showModal();
}

async function searchNotes() {
  const query = el('searchQ').value.trim();
  if (!query) return;
  const resp = await fetch('/api/notes/search', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, limit: 10 }),
  });
  const out = await resp.json();
  el('searchOut').textContent = out.map((x) => `${x.note_title} [${x.chunk_index}]\n${x.chunk_text.slice(0, 180)}...`).join('\n\n') || 'No matches';
}



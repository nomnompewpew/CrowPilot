async function loadConversationHistory(nextFilter = null) {
  const resp = await fetch('/api/conversations/sidebar');
  if (!resp.ok) return;
  const data = await resp.json();
  state.conversationBuckets = data.buckets || state.conversationBuckets;

  const allIds = Object.values(state.conversationBuckets).flat().map((conv) => conv.id);
  if (state.conversationId && !allIds.includes(state.conversationId)) {
    state.conversationId = null;
  }

  renderConversationFilters(data.counts || {});
  if (nextFilter) {
    state.conversationFilter = nextFilter;
  }
  renderConversationList();
}

async function loadConversationMessages(convId) {
  const resp = await fetch(`/api/conversations/${convId}`);
  if (!resp.ok) return;
  const conv = await resp.json();
  
  el('messages').innerHTML = '';
  conv.messages.forEach((msg) => {
    addMessage(msg.role, msg.content);
  });
  el('chatStatus').textContent = `Conversation ${convId} loaded`;
}

function updateSidebarStatus() {
  const status = el('sidebarStatus');
  const convText = state.conversationId ? `Chat: ${state.conversationId}` : 'New chat';
  const modeText = state.uiMode === 'zen' ? 'Mode: Zen' : 'Mode: Big Brain';
  const filterText = `Bucket: ${state.conversationFilter.replace('_', ' ')}`;
  status.innerHTML = `${modeText}<br/>${filterText}<br/>${convText}`;
}

async function mutateConversation(action) {
  const selected = currentConversationRecord();
  if (!selected) return;

  const filterAfter = {
    restore: 'active',
    hide: 'hidden',
    archive_good: 'archived_good',
    archive_bad: 'archived_bad',
  };

  const resp = await fetch(`/api/conversations/${selected.id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action }),
  });
  if (!resp.ok) {
    el('chatStatus').textContent = `Conversation update failed: ${await resp.text()}`;
    return;
  }

  await loadConversationHistory(filterAfter[action] || state.conversationFilter);
}

async function deleteSelectedConversation() {
  const selected = currentConversationRecord();
  if (!selected) return;
  if (!confirm(`Delete conversation "${selected.title}" permanently?`)) return;

  const resp = await fetch(`/api/conversations/${selected.id}`, { method: 'DELETE' });
  if (!resp.ok) {
    el('chatStatus').textContent = `Conversation delete failed: ${await resp.text()}`;
    return;
  }

  state.conversationId = null;
  el('messages').innerHTML = '';
  el('chatStatus').textContent = 'Conversation deleted.';
  await loadConversationHistory('active');
  await loadSummary();
}


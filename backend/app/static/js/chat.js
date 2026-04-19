function setUiMode(mode) {
  state.uiMode = mode;
  localStorage.setItem('crowpilot_ui_mode', mode);
  document.body.classList.toggle('big-brain-mode', mode === 'big-brain');
  document.body.classList.toggle('zen-mode', mode === 'zen');
  el('bigBrainModeBtn').classList.toggle('tb-active', mode === 'big-brain');
  el('zenModeBtn').classList.toggle('tb-active', mode === 'zen');
  el('modeTitle').textContent = mode === 'zen' ? 'Zen Mode' : 'Big Brain Mode';
  el('modeNote').textContent = mode === 'zen'
    ? 'Prompt-driven rails with minimal controls. CrowPilot interprets your intent and fills the structured parts for you.'
    : 'Full controls, direct forms, and lower-level levers for building and inspecting everything.';
  updateSidebarStatus();
}

function currentConversationRecord() {
  return Object.values(state.conversationBuckets)
    .flat()
    .find((conv) => conv.id === state.conversationId) || null;
}

function renderConversationFilters(counts = {}) {
  const labels = {
    active: `Live ${counts.active || 0}`,
    hidden: `Hidden ${counts.hidden || 0}`,
    archived_good: `Good ${counts.archived_good || 0}`,
    archived_bad: `Bad ${counts.archived_bad || 0}`,
  };

  document.querySelectorAll('button[data-conv-filter]').forEach((btn) => {
    const filter = btn.dataset.convFilter;
    btn.classList.toggle('active', filter === state.conversationFilter);
    btn.textContent = labels[filter];
  });
}

function renderConversationSelectionMeta() {
  const meta = el('conversationSelectionMeta');
  const selected = currentConversationRecord();
  if (!selected) {
    meta.textContent = 'Select a conversation to manage it.';
    return;
  }

  const bucket = selected.sidebar_state === 'archived'
    ? `archived/${selected.archive_bucket || 'unknown'}`
    : selected.sidebar_state === 'hidden' && selected.archive_bucket
      ? `hidden/${selected.archive_bucket}`
      : selected.sidebar_state;
  meta.innerHTML = `${selected.title}<br/>${bucket} | ${selected.message_count || 0} messages`;
}

function renderConversationList() {
  const list = el('conversationList');
  list.innerHTML = '';

  const rows = state.conversationBuckets[state.conversationFilter] || [];
  const labelMap = {
    active: 'Live conversations ready to continue.',
    hidden: 'Hidden conversations stay recoverable but out of the main lane.',
    archived_good: 'Good examples to keep as reusable patterns.',
    archived_bad: 'Bad examples kept as anti-patterns and poison references.',
  };
  el('conversationBucketMeta').textContent = labelMap[state.conversationFilter] || '';

  rows.forEach((conv) => {
    const item = document.createElement('div');
    item.className = `conversation-item ${conv.id === state.conversationId ? 'active' : ''}`;
    const bucketBadge = conv.archive_bucket ? ` [${conv.archive_bucket}]` : '';
    item.textContent = `${conv.title || `Chat ${conv.id}`}${bucketBadge}`;
    item.title = `${conv.title || `Chat ${conv.id}`} (${conv.message_count || 0} messages)`;
    item.addEventListener('click', async () => {
      state.conversationId = conv.id;
      await loadConversationMessages(conv.id);
      renderConversationList();
      renderConversationSelectionMeta();
      updateSidebarStatus();
      tabSwitch('deck');
    });
    list.appendChild(item);
  });

  renderConversationSelectionMeta();
}

function setConversationFilter(filter) {
  state.conversationFilter = filter;
  renderConversationFilters({
    active: state.conversationBuckets.active.length,
    hidden: state.conversationBuckets.hidden.length,
    archived_good: state.conversationBuckets.archived_good.length,
    archived_bad: state.conversationBuckets.archived_bad.length,
  });
  renderConversationList();
  updateSidebarStatus();
}

function addMessage(role, text, klass = '') {
  const wrap = el('messages');
  const node = document.createElement('div');
  node.className = `msg ${role} ${klass}`;
  node.textContent = text;
  wrap.appendChild(node);
  wrap.scrollTop = wrap.scrollHeight;
  return node;
}

async function runZenAction(domain, promptId, resultId) {
  const prompt = el(promptId).value.trim();
  if (!prompt) return;

  el(resultId).textContent = 'Thinking...';
  const resp = await fetch('/api/zen/act', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      domain,
      prompt,
      provider: state.providers.local_openai ? 'local_openai' : null,
    }),
  });

  if (!resp.ok) {
    el(resultId).textContent = `Failed: ${await resp.text()}`;
    return;
  }

  const out = await resp.json();
  const recordName = out.record?.title || out.record?.name || out.record?.id || 'saved item';
  let extra = '';
  if (domain === 'mcp_create' && out.record?.validation_report) {
    const reportLines = [];
    (out.record.validation_report.checks || []).forEach((c) => {
      reportLines.push(`${c.ok ? 'OK' : 'FAIL'} ${c.step}: ${c.detail}`);
    });
    if ((out.record.validation_report.tools || []).length) {
      reportLines.push(`Tools: ${(out.record.validation_report.tools || []).join(', ')}`);
    }
    if (reportLines.length) {
      extra = `\n\nValidation:\n${reportLines.join('\n')}`;
    }
  }
  el(resultId).textContent = `${out.summary}\n\nSaved: ${recordName}${extra}`;

  if (domain === 'task_create') {
    await listAutomationTasks();
  } else if (domain === 'skill_create') {
    await listSkills();
  } else if (domain === 'note_create') {
    el('searchOut').textContent = `Saved note: ${out.record?.title || 'Zen note'}`;
  } else if (domain === 'mcp_create') {
    await listMcpServers();
  } else if (domain === 'widget_create') {
    await listWidgets();
  }
  await loadSummary();
}

async function loadSummary() {
  const resp = await fetch('/api/dashboard/summary');
  const data = await resp.json();
  state.lastSummary = data;
  renderStatStrip(data, state.serverStats);
}

function renderStatStrip(summary, server) {
  const strip = el('statStrip');
  if (!summary) return;
  const c = summary.counts || {};
  const net = (server && server.network) || {};
  const mem = (server && server.memory) || {};
  const cpu = (server && server.cpu) || {};
  const disk = (server && server.disk) || {};

  const memPct = mem.used_pct || 0;
  const diskPct = disk.used_pct || 0;
  const memClass = memPct > 85 ? 'danger-chip' : memPct > 65 ? 'warn-chip' : '';
  const diskClass = diskPct > 85 ? 'danger-chip' : diskPct > 65 ? 'warn-chip' : '';

  // LAN IP chip — clicking opens Server & Logs page
  const ipChip = net.primary_lan_ip
    ? `<div class="chip highlight" style="cursor:pointer;" title="Open Server &amp; Logs" onclick="tabSwitch('server')">
         <strong style="font-size:.9rem;">${net.primary_lan_ip}</strong>
         <span>LAN IP · click for server</span>
       </div>`
    : '';

  const memChip = mem.used_pct != null
    ? `<div class="chip ${memClass}" title="RAM: ${mem.used_mb}MB / ${mem.total_mb}MB">
         <strong>${mem.used_pct}%</strong><span>RAM Used</span>
       </div>` : '';

  const cpuChip = cpu.load_1m != null
    ? `<div class="chip" title="Load avg 1m/5m/15m">
         <strong>${cpu.load_1m}</strong><span>CPU Load 1m</span>
       </div>` : '';

  const diskChip = disk.used_pct != null
    ? `<div class="chip ${diskClass}" title="Disk: ${disk.used_gb}GB / ${disk.total_gb}GB">
         <strong>${disk.used_pct}%</strong><span>Disk Used</span>
       </div>` : '';

  strip.innerHTML = `
    ${ipChip}
    ${memChip}
    ${cpuChip}
    ${diskChip}
    <div class="chip"><strong>${c.conversations || 0}</strong><span>Conversations</span></div>
    <div class="chip"><strong>${c.messages || 0}</strong><span>Messages</span></div>
    <div class="chip"><strong>${c.notes || 0}</strong><span>Knowledge Notes</span></div>
    <div class="chip"><strong>${c.mcp_servers || 0}</strong><span>MCP Servers</span></div>
    <div class="chip"><strong>${c.automation_tasks || 0}</strong><span>Tasks</span></div>
    <div class="chip"><strong>${c.skills || 0}</strong><span>Skills</span></div>
    <div class="chip"><strong>${c.integrations || 0}</strong><span>Integrations</span></div>
    <div class="chip"><strong>${c.projects || 0}</strong><span>Projects</span></div>
  `;
}

async function refreshHealth() {
  const resp = await fetch('/api/health');
  const data = await resp.json();
  state.providers = data.providers || {};

  const select = el('provider');
  select.innerHTML = ''; // Clear existing options
  Object.keys(state.providers).forEach((name) => {
    const opt = document.createElement('option');
    opt.value = name;
    opt.textContent = name;
    select.appendChild(opt);
  });

  // Populate models for the currently selected provider
  await updateModelsForProvider();

  el('healthOut').textContent = JSON.stringify(state.providers, null, 2);
}

async function updateModelsForProvider() {
  const provider = el('provider').value;
  if (!provider) return;

  const autoToggle = el('autoModelToggle');
  autoToggle.disabled = provider !== 'copilot_proxy';
  if (provider !== 'copilot_proxy' && autoToggle.checked) {
    autoToggle.checked = false;
    state.autoModel = false;
  }

  try {
    const resp = await fetch(`/api/models?provider=${encodeURIComponent(provider)}`);
    const data = await resp.json();

    const select = el('model');
    select.innerHTML = ''; // Clear existing options

    if (data.ok && data.models.length > 0) {
      // Add default model first if available
      if (data.default_model) {
        const opt = document.createElement('option');
        opt.value = data.default_model;
        opt.textContent = data.default_model + ' (default)';
        opt.selected = true;
        select.appendChild(opt);
      }

      // Add other models
      data.models.forEach((model) => {
        if (model !== data.default_model) {
          const opt = document.createElement('option');
          opt.value = model;
          opt.textContent = model;
          select.appendChild(opt);
        }
      });
    } else if (data.default_model) {
      // Fallback: at least show the default model
      const opt = document.createElement('option');
      opt.value = data.default_model;
      opt.textContent = data.default_model + ' (default)';
      opt.selected = true;
      select.appendChild(opt);
    }

    if (state.autoModel && provider === 'copilot_proxy') {
      el('model').value = 'auto';
    }
  } catch (err) {
    console.error('Failed to load models:', err);
    // Fallback: keep what was there
  }
}

async function sendChat() {
  const prompt = el('prompt').value.trim();
  if (!prompt) return;

  const provider = el('provider').value;
  const selectedModel = el('model').value.trim();
  const model = state.autoModel && provider === 'copilot_proxy' ? 'auto' : selectedModel;
  const useMemory = el('useMemoryToggle').checked;
  const secureMode = true; // always scan via local model before cloud

  addMessage('user', prompt);
  el('prompt').value = '';
  const assistant = addMessage('assistant', '');
  // thinking container (hidden until thinking tokens arrive)
  let thinkingEl = null;
  let thinkingBuf = '';
  el('chatStatus').textContent = secureMode ? '🔍 Scanning locally…' : 'Streaming…';

  const body = {
    message: prompt,
    conversation_id: state.conversationId,
    provider,
    model: model || null,
    use_memory: useMemory,
    secure_mode: secureMode,
  };

  const resp = await fetch('/api/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });

  if (!resp.ok || !resp.body) {
    const errText = await resp.text().catch(() => resp.status);
    assistant.classList.add('error');
    assistant.textContent = `Request failed (${resp.status}): ${errText}`;
    el('chatStatus').textContent = 'Error';
    return;
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let memoryHits = 0;

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const blocks = buffer.split('\n\n');
    buffer = blocks.pop() || '';

    blocks.forEach((block) => {
      const line = block.split('\n').find((l) => l.startsWith('data: '));
      if (!line) return;
      let payload;
      try { payload = JSON.parse(line.slice(6)); } catch { return; }

      if (payload.type === 'meta') {
        state.conversationId = payload.conversation_id;
        memoryHits = payload.memory_hits || 0;
      } else if (payload.type === 'status') {
        el('chatStatus').textContent = payload.text;
      } else if (payload.type === 'pii_scan') {
        const n = payload.redacted_count;
        if (n > 0) {
          const badge = document.createElement('div');
          badge.className = 'tiny';
          badge.style.cssText = 'color:var(--yellow,#e0b854);margin-bottom:4px;';
          badge.textContent = `🔒 ${n} sensitive value${n === 1 ? '' : 's'} redacted before sending to cloud`;
          assistant.parentNode.insertBefore(badge, assistant);
        }
      } else if (payload.type === 'thinking') {
        // Show thinking tokens in a collapsible dim section
        thinkingBuf += payload.token;
        if (!thinkingEl) {
          thinkingEl = document.createElement('details');
          thinkingEl.className = 'thinking-block';
          thinkingEl.innerHTML = '<summary>Thinking…</summary>';
          const pre = document.createElement('pre');
          pre.className = 'thinking-content';
          thinkingEl.appendChild(pre);
          assistant.parentNode.insertBefore(thinkingEl, assistant);
        }
        thinkingEl.querySelector('pre').textContent = thinkingBuf;
      } else if (payload.type === 'token') {
        if (thinkingEl) thinkingEl.querySelector('summary').textContent = 'Thought process';
        assistant.textContent += payload.token;
      } else if (payload.type === 'error') {
        assistant.classList.add('error');
        assistant.textContent += `\n[error] ${payload.error}`;
        el('chatStatus').textContent = 'Error';
      } else if (payload.type === 'done') {
        const memBadge = memoryHits > 0 ? ` · 🧠 ${memoryHits} memor${memoryHits === 1 ? 'y' : 'ies'} recalled` : '';
        const secBadge = secureMode ? ' · 🔒 secure' : '';
        el('chatStatus').textContent = `Done. Conversation ${state.conversationId}${memBadge}${secBadge}`;
      }
    });
  }
}


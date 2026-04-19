function initApp() {
  document.querySelectorAll('button[data-nav]').forEach((btn) => {
    btn.addEventListener('click', () => tabSwitch(btn.dataset.nav));
  });
  document.querySelectorAll('button[data-conv-filter]').forEach((btn) => {
    btn.addEventListener('click', () => setConversationFilter(btn.dataset.convFilter));
  });
  el('newConvSidebarBtn').addEventListener('click', () => {
    state.conversationId = null;
    el('messages').innerHTML = '';
    el('chatStatus').textContent = 'New conversation started.';
    renderConversationList();
    updateSidebarStatus();
    tabSwitch('deck');
  });

  el('sendBtn').addEventListener('click', sendChat);
  el('prompt').addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) sendChat();
  });
  el('provider').addEventListener('change', async () => {
    // Deck provider change → sync right-panel chatProvider and reload models
    if (el('chatProvider')) el('chatProvider').value = el('provider').value;
    state.autoModel = el('autoModelToggle') ? el('autoModelToggle').checked : false;
    await updateModelsForProvider();
  });
  el('autoModelToggle').addEventListener('change', async () => {
    state.autoModel = el('autoModelToggle').checked;
    // Reflect in chatModel: check → set Auto, uncheck → keep current
    if (state.autoModel && el('chatModel')) el('chatModel').value = 'auto';
    if (state.autoModel && el('model')) el('model').value = 'auto';
    await updateModelsForProvider();
  });

  el('archiveGoodBtn').addEventListener('click', () => mutateConversation('archive_good'));
  el('archiveBadBtn').addEventListener('click', () => mutateConversation('archive_bad'));
  el('hideConversationBtn').addEventListener('click', () => mutateConversation('hide'));
  el('restoreConversationBtn').addEventListener('click', () => mutateConversation('restore'));
  el('deleteConversationBtn').addEventListener('click', deleteSelectedConversation);

  el('logoutBtn').addEventListener('click', async () => {
    await fetch('/api/auth/logout', { method: 'POST' });
    showLogin();
  });

  el('bigBrainModeBtn').addEventListener('click', () => setUiMode('big-brain'));
  el('zenModeBtn').addEventListener('click', () => setUiMode('zen'));
  el('vsCodeViewBtn').addEventListener('click', toggleVsCodeView);
  el('openCredentialsBtn').addEventListener('click', () => tabSwitch('credentials'));

  // Right-panel model picker
  if (el('chatProvider')) {
    el('chatProvider').addEventListener('change', () => updateModelsForProvider());
  }
  if (el('agentModeBtn')) {
    el('agentModeBtn').addEventListener('click', toggleAgentMode);
  }

  el('jinaFetchBtn').addEventListener('click', jinaFetchUrl);
  el('jinaUrl').addEventListener('keydown', (e) => { if (e.key === 'Enter') jinaFetchUrl(); });
  el('saveNoteBtn').addEventListener('click', saveNote);
  el('searchBtn').addEventListener('click', searchNotes);
  el('zenKnowledgeBtn').addEventListener('click', () => runZenAction('note_create', 'zenKnowledgePrompt', 'zenKnowledgeResult'));

  el('vsCodeConfigBtn').addEventListener('click', fetchVsCodeConfig);
  el('closeVsCodeConfigDialog').addEventListener('click', () => el('vsCodeConfigDialog').close());
  el('copyRelaySnippetBtn').addEventListener('click', () => {
    navigator.clipboard.writeText(el('vsCodeRelaySnippet').value);
    el('copyRelaySnippetBtn').textContent = 'Copied!';
    setTimeout(() => { el('copyRelaySnippetBtn').textContent = 'Copy Snippet'; }, 1500);
  });
  el('copyAllServersSnippetBtn').addEventListener('click', () => {
    navigator.clipboard.writeText(el('vsCodeAllServersSnippet').value);
  });

  el('createMcpBtn').addEventListener('click', createMcpServer);
  el('createAndCheckMcpBtn').addEventListener('click', createAndCheckMcpServer);
  el('mcpCredDialogSave').addEventListener('click', mcpCredDialogSubmit);
  el('mcpCredDialogCancel').addEventListener('click', () => { el('mcpCredDialog').close(); _mcpCatalogPending = null; });
  el('mcpCredDialogInput').addEventListener('keydown', (e) => { if (e.key === 'Enter') mcpCredDialogSubmit(); });

  el('createWidgetBtn').addEventListener('click', createWidget);
  el('zenWidgetBtn').addEventListener('click', () => runZenAction('widget_create', 'zenWidgetPrompt', 'zenWidgetResult'));

  el('createAutoTaskBtn').addEventListener('click', createAutomationTask);
  el('createSkillBtn').addEventListener('click', createSkill);
  el('zenTaskBtn').addEventListener('click', () => runZenAction('task_create', 'zenTaskPrompt', 'zenTaskResult'));
  el('zenSkillBtn').addEventListener('click', () => runZenAction('skill_create', 'zenSkillPrompt', 'zenSkillResult'));
  el('createCredentialBtn').addEventListener('click', createCredential);
  el('refreshCredentialBtn').addEventListener('click', listCredentials);
  el('importCredentialEnvBtn').addEventListener('click', importCredentialsEnv);
  el('launchConnectorBtn').addEventListener('click', () => launchConnector(null, !!el('connectorOpenBrowser').checked, 'connectorStatus'));
  el('createIntegrationBtn').addEventListener('click', createIntegration);
  el('integrationUseCredentialBtn').addEventListener('click', useCredentialForIntegration);
  el('integrationLaunchConnectorBtn').addEventListener('click', () => launchConnector(el('integrationKind').value.trim().toLowerCase(), true, 'integrationStatusOut'));
  el('integrationOpenCredentialsBtn').addEventListener('click', () => tabSwitch('credentials'));
  el('sensitivePreviewBtn').addEventListener('click', runSensitivePreview);

  el('browseProjectBtn').addEventListener('click', browseProjectFolder);
  el('importProjectPathBtn').addEventListener('click', () => importProjectByPath(el('projectFolderPath').value));
  el('projectFolderPath').addEventListener('keydown', (e) => { if (e.key === 'Enter') importProjectByPath(el('projectFolderPath').value); });
  el('projectSelect').addEventListener('change', (e) => { if (e.target.value) selectProject(Number(e.target.value)); });
  el('refreshProjectScriptsBtn').addEventListener('click', loadProjectScripts);
  el('runProjectScriptBtn').addEventListener('click', runProjectScript);
  el('openProjectPreviewBtn').addEventListener('click', openProjectPreview);
  el('autoDetectPreviewBtn').addEventListener('click', autoDetectPreviewUrl);
  el('projectPreviewUrl').addEventListener('keydown', (e) => { if (e.key === 'Enter') openProjectPreview(); });

  el('refreshServerStatsBtn').addEventListener('click', loadServerStats);
  el('clearLogsBtn').addEventListener('click', () => {
    el('logStream').innerHTML = '';
    _logLineCount = 0;
  });
  el('pauseLogsBtn').addEventListener('click', (e) => {
    _logPaused = !_logPaused;
    e.target.textContent = _logPaused ? 'Resume' : 'Pause';
    e.target.className = _logPaused ? 'alt' : '';
  });
  el('logFilter').addEventListener('input', () => {
    // Filter only affects new lines; clear and let stream refill
  });

  startLogStream();
  initCopilotHistory();

  Promise.all([
    loadSummary(),
    loadServerStats(),
    refreshHealth(),
    listMcpServers(),
    listWidgets(),
    listAutomationTasks(),
    listSkills(),
    listIntegrations(),
    listCredentials(),
    loadCredentialConnectors(),
    loadHubAccess(),
    loadOauthTemplates(),
    loadProjectCapabilities(),
    listProjects(),
    loadConversationHistory(),
    loadNoteList(),
  ]).then(() => {
    tabSwitch('deck');
    setUiMode(localStorage.getItem('crowpilot_ui_mode') || 'zen');
    updateSidebarStatus();
    initWizard();
    startEmbedBadge();
  }).catch((err) => {
    console.error(err);
  });
}

/* ── Embed Status Badge ────────────────────────────────────────── */
function startEmbedBadge() {
  const badge = el('embedBadge');
  if (!badge) return;
  setInterval(async () => {
    try {
      const r = await fetch('/api/memory/queue-size', { signal: AbortSignal.timeout(2000) });
      if (!r.ok) return;
      const d = await r.json();
      badge.style.display = (d.pending > 0) ? 'block' : 'none';
      badge.textContent = `⚙ Embedding… (${d.pending} left)`;
    } catch { /* ignore */ }
  }, 5000);
}

/* ── Setup Wizard ──────────────────────────────────────────────── */
async function initWizard() {
  try {
    const r = await fetch('/api/wizard/status');
    if (!r.ok) return;
    const d = await r.json();
    if (d.setup_complete) return;          // already done
    const incomplete = d.steps.filter(s => !s.ok);
    if (incomplete.length === 0) return;  // all checks pass
    showWizard(d.steps);
  } catch { /* non-fatal */ }
}

function showWizard(steps) {
  const dlg = el('wizardOverlay');
  const list = el('wizardStepList');
  list.innerHTML = steps.map(s =>
    `<li style="padding:6px 0; ${s.ok ? '' : 'color:var(--yellow,#e0b854)'}">${s.ok ? '✅' : '⚠️'} <strong>${s.label}</strong> — ${s.detail}</li>`
  ).join('');

  const closeBtn = el('wizardCloseBtn');
  closeBtn.onclick = async () => {
    dlg.close();
    try { await fetch('/api/wizard/complete', { method: 'POST' }); } catch {}
  };

  dlg.showModal();
}

/* ── Zen Credential ────────────────────────────────────────────── */
el('zenCredentialBtn')?.addEventListener('click', async () => {
  const prompt = (el('zenCredentialPrompt')?.value || '').trim();
  if (!prompt) return;
  const st = el('zenCredentialStatus');
  st.textContent = 'Thinking…';
  try {
    const r = await fetch('/api/zen/act', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ domain: 'credential_create', prompt }),
    });
    const d = await r.json();
    if (!r.ok) { st.textContent = `Error: ${d.detail || r.status}`; return; }
    st.textContent = `✅ Created "${d.record?.name}". ${d.summary}`;
    el('zenCredentialPrompt').value = '';
    if (typeof loadCredentialList === 'function') loadCredentialList();
  } catch (e) { st.textContent = `Error: ${e.message}`; }
});

/* ── Zen Integration ───────────────────────────────────────────── */
el('zenIntegrationBtn')?.addEventListener('click', async () => {
  const prompt = (el('zenIntegrationPrompt')?.value || '').trim();
  if (!prompt) return;
  const st = el('zenIntegrationStatus');
  st.textContent = 'Thinking…';
  try {
    const r = await fetch('/api/zen/act', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ domain: 'integration_create', prompt }),
    });
    const d = await r.json();
    if (!r.ok) { st.textContent = `Error: ${d.detail || r.status}`; return; }
    st.textContent = `✅ Created "${d.record?.name}". ${d.summary}`;
    el('zenIntegrationPrompt').value = '';
    if (typeof loadIntegrationList === 'function') loadIntegrationList();
  } catch (e) { st.textContent = `Error: ${e.message}`; }
});

/* Bootstrap */
checkAuth();

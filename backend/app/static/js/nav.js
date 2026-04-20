/* ── Helpers & NAV ─────────────────────────────────────────────── */
const NAV_LABELS = {
  deck: 'Command Deck',
  mcp: 'MCP Forge',
  knowledge: 'Knowledge Lab',
  tasks: 'Tasks',
  skills: 'Skills',
  credentials: 'Credentials Vault',
  integrations: 'Integrations',
  projects: 'Projects',
  'copilot-history': 'Copilot History',
  server: 'Server & Logs',
};

function tabSwitch(tab) {
  if (state.editionProfile && state.editionProfile.nav && state.editionProfile.nav[tab] === false) {
    tab = 'deck';
  }

  state.activeTab = tab;
  document.querySelectorAll('button[data-nav]').forEach((btn) => {
    btn.classList.toggle('active', btn.dataset.nav === tab);
  });
  document.querySelectorAll('.view').forEach((view) => {
    view.classList.toggle('active', view.id === `view-${tab}`);
  });
  if (el('topBarSection')) el('topBarSection').textContent = NAV_LABELS[tab] || tab;
  if (tab === 'server') loadServerStats();
  if (tab === 'mcp') { loadMcpCatalog(); listMcpServers(); }
  if (tab === 'deck') { loadLanDevices(); loadNetworkRouters(); }
}

function applyEditionProfile() {
  const profile = state.editionProfile;
  if (!profile) return;

  const nav = profile.nav || {};
  document.querySelectorAll('button[data-nav]').forEach((btn) => {
    const name = btn.dataset.nav;
    const enabled = nav[name] !== false;
    btn.style.display = enabled ? '' : 'none';
  });

  const features = profile.features || {};
  document.querySelectorAll('[data-edition-feature]').forEach((node) => {
    const feature = node.dataset.editionFeature;
    const enabled = features[feature] !== false;
    node.style.display = enabled ? '' : 'none';
  });

  if (el('monacoViewBtn')) {
    const monacoEnabled = features.monaco_editor !== false;
    el('monacoViewBtn').style.display = monacoEnabled ? '' : 'none';
    if (!monacoEnabled && state.monacoViewActive && typeof toggleMonacoView === 'function') {
      toggleMonacoView();
    }
  }

  if (el('bigBrainModeBtn')) {
    const modeEnabled = features.big_brain_mode !== false;
    el('bigBrainModeBtn').style.display = modeEnabled ? '' : 'none';
    if (!modeEnabled && state.uiMode === 'big-brain' && typeof setUiMode === 'function') {
      setUiMode('zen');
    }
  }

  if (el('editionBadge')) {
    el('editionBadge').textContent = `${profile.label} (${state.edition || 'unknown'})`;
  }

  if (el('editionRuntimeHint')) {
    const model = state.modelProfile || {};
    const scan = model.scan_model || model.local_model || 'unset';
    const embed = model.embedding_model || 'unset';
    const embedMode = model.embed_mode || 'realtime';
    el('editionRuntimeHint').textContent = `${profile.intent} Scan: ${scan} | Embed: ${embed} | Mode: ${embedMode}`;
  }

  if (state.activeTab && nav[state.activeTab] === false) {
    tabSwitch('deck');
  }
}

/* ── Copy helper ────────────────────────────────────────────────── */
function copyText(elId, btn) {
  const text = el(elId).textContent.trim();
  navigator.clipboard.writeText(text).then(() => {
    const orig = btn.textContent;
    btn.textContent = 'Copied!';
    setTimeout(() => { btn.textContent = orig; }, 1500);
  });
}


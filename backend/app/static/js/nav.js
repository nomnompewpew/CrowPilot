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
  server: 'Server & Logs',
};

function tabSwitch(tab) {
  document.querySelectorAll('button[data-nav]').forEach((btn) => {
    btn.classList.toggle('active', btn.dataset.nav === tab);
  });
  document.querySelectorAll('.view').forEach((view) => {
    view.classList.toggle('active', view.id === `view-${tab}`);
  });
  if (el('topBarSection')) el('topBarSection').textContent = NAV_LABELS[tab] || tab;
  if (tab === 'server') loadServerStats();
  if (tab === 'mcp') { loadMcpCatalog(); listMcpServers(); }
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


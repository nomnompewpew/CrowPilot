const AUTH_ICONS  = { none: '🆓', api_key: '🔑', bearer: '🔑', oauth: '🔗' };
const AUTH_LABELS = { none: 'Free', api_key: 'API Key', bearer: 'Token', oauth: 'OAuth' };

let _mcpCatalogPending = null; // { service, envKey, docsUrl }

// Catalog names for filtering custom servers
let _catalogNames = new Set();

async function loadMcpCatalog() {
  const [catResp, srvResp] = await Promise.all([
    fetch('/api/mcp/catalog'),
    fetch('/api/mcp/servers'),
  ]);
  if (!catResp.ok) return;
  const items = await catResp.json();
  const allServers = srvResp.ok ? await srvResp.json() : [];

  // Build name→server map for cross-referencing
  const serverByName = {};
  allServers.forEach((s) => { serverByName[s.name] = s; });
  _catalogNames = new Set(items.map((i) => i.name));

  const grid = el('mcpCatalogGrid');
  grid.innerHTML = '';

  items.forEach((item) => {
    const srv = serverByName[item.name] || null;
    const online = srv?.status === 'online';
    const authIcon = AUTH_ICONS[item.auth_type] || '🔌';
    const authLabel = AUTH_LABELS[item.auth_type] || item.auth_type;
    const docsUrl = (item.docs || [])[0] || '';
    const envKey = (item.env_keys || [])[0] || '';

    const tile = document.createElement('div');
    tile.className = 'mcp-tile' + (srv ? ' installed' : '');

    const badgeHtml = srv
      ? `<span class="badge ${online ? 'ok' : 'offline'}">${online ? 'online' : 'offline'}</span>`
      : `<span class="badge" style="opacity:.6;">${authIcon} ${authLabel}</span>`;

    const localBadge = item.pip_package
      ? `<span class="badge" title="Runs locally via pip install ${item.pip_package}" style="opacity:.7;">📦 local</span>`
      : '';

    const connectBtn = `<button data-service="${item.key}" data-auth="${item.auth_type}" data-env-key="${envKey}" data-docs="${docsUrl}" data-pip="${item.pip_package || ''}"
      class="${online ? 'alt' : ''}" style="flex:2;">${online ? '✓ Connected' : srv ? 'Reconnect' : 'Connect'}</button>`;
    const checkBtn  = srv ? `<button data-check="${srv.id}" class="alt">Check</button>` : '';
    const delBtn    = srv && !srv.is_builtin ? `<button data-delete="${srv.id}" class="warn">Delete</button>` : '';

    let errorMsg = srv?.last_error || '';
    if (errorMsg) {
      try {
        const parsed = JSON.parse(errorMsg.match(/(\{.*\})/s)?.[1] || errorMsg);
        if (parsed.error_description) errorMsg = parsed.error_description;
        else if (parsed.error) errorMsg = parsed.error;
      } catch {}
    }
    const errorHtml = errorMsg ? `<div class="mcp-tile-error">${errorMsg.slice(0, 160)}</div>` : '';

    tile.innerHTML = `
      <div class="mcp-tile-header">
        <span class="mcp-tile-name">${item.name}</span>
        <span style="display:flex;gap:4px;align-items:center;">${localBadge}${badgeHtml}</span>
      </div>
      <p class="mcp-tile-desc">${item.notes}</p>
      <div class="mcp-tile-actions">
        ${connectBtn}${checkBtn}${delBtn}
      </div>
      ${errorHtml}
    `;
    grid.appendChild(tile);
  });

  // Append custom (non-catalog) server tiles to the same grid
  const custom = allServers.filter((s) => !_catalogNames.has(s.name));
  custom.forEach((row) => {
    const tile = document.createElement('div');
    tile.className = 'mcp-tile installed';
    const badgeClass = row.status === 'online' ? 'ok' : row.status === 'offline' ? 'offline' : '';
    const desc = [row.transport, row.url || row.command || 'n/a'].filter(Boolean).join(' · ');
    const checkBtn = `<button data-check="${row.id}" class="alt" style="flex:2;">Check</button>`;
    const delBtn = row.is_builtin ? '' : `<button data-delete="${row.id}" class="warn">Delete</button>`;
    let errorMsg = row.last_error || '';
    if (errorMsg) {
      try {
        const parsed = JSON.parse(errorMsg.match(/(\{.*\})/s)?.[1] || errorMsg);
        if (parsed.error_description) errorMsg = parsed.error_description;
        else if (parsed.error) errorMsg = parsed.error;
      } catch {}
    }
    const errorHtml = errorMsg ? `<div class="mcp-tile-error">${errorMsg.slice(0, 160)}</div>` : '';
    tile.innerHTML = `
      <div class="mcp-tile-header">
        <span class="mcp-tile-name">${row.name}</span>
        <span style="display:flex;gap:4px;align-items:center;">
          ${row.is_builtin ? '<span class="badge" style="opacity:.6;">locked</span>' : ''}
          <span class="badge ${badgeClass}">${row.status}</span>
        </span>
      </div>
      <p class="mcp-tile-desc">${desc}</p>
      <div class="mcp-tile-actions">
        ${checkBtn}${delBtn}
      </div>
      ${errorHtml}
    `;
    grid.appendChild(tile);
  });

  // Wire all buttons in one pass
  grid.querySelectorAll('button[data-service]').forEach((btn) => {
    btn.addEventListener('click', () => mcpCatalogConnect(
      btn.dataset.service, btn.dataset.auth, btn.dataset.envKey, btn.dataset.docs, btn.dataset.pip,
    ));
  });

  grid.querySelectorAll('button[data-check]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const id = btn.getAttribute('data-check');
      btn.textContent = '…'; btn.disabled = true;
      await fetch(`/api/mcp/servers/${id}/check`, { method: 'POST' });
      await loadMcpCatalog();
    });
  });

  grid.querySelectorAll('button[data-delete]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const id = btn.getAttribute('data-delete');
      await fetch(`/api/mcp/servers/${id}`, { method: 'DELETE' });
      await loadMcpCatalog(); await loadSummary();
    });
  });
}

async function mcpCatalogConnect(service, authType, envKey, docsUrl, pipPackage) {
  if (authType === 'none') {
    const btn = el('mcpCatalogGrid').querySelector(`button[data-service="${service}"]`);
    if (btn) { btn.textContent = 'Connecting…'; btn.disabled = true; }
    await fetch('/api/mcp/connect', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ service }),
    });
    await loadMcpCatalog();
    await loadSummary();
    return;
  }

  _mcpCatalogPending = { service, envKey, docsUrl, pipPackage };

  // Title + label
  el('mcpCredDialogTitle').textContent = `Connect ${service}`;
  el('mcpCredDialogLabel').textContent = envKey || 'API Key / Token';
  el('mcpCredDialogInput').value = '';
  el('mcpCredDialogStatus').textContent = '';

  // Hint text
  const isOauth = authType === 'oauth';
  const pipHint = pipPackage ? ` Will auto-install \`${pipPackage}\` and run locally.` : '';
  el('mcpCredDialogHint').textContent = isOauth
    ? `Complete OAuth in the tab that opens, copy the token you receive, and paste it below.${pipHint}`
    : `Paste your ${envKey || 'API key'} — stored encrypted in the vault, never sent to the cloud.${pipHint}`;

  // Show / hide the "Get your key" button
  const getKeyBtn = el('mcpCredDialogGetKey');
  if (docsUrl) {
    getKeyBtn.style.display = 'inline-flex';
    getKeyBtn.textContent = isOauth ? '🔗 Open login page →' : '🔑 Get your key →';
    getKeyBtn.onclick = () => window.open(docsUrl, '_blank');
  } else {
    getKeyBtn.style.display = 'none';
  }

  el('mcpCredDialog').showModal();
}

async function mcpCredDialogSubmit() {
  if (!_mcpCatalogPending) return;
  const { service, envKey, docsUrl } = _mcpCatalogPending;
  const value = el('mcpCredDialogInput').value.trim();
  if (!value) { el('mcpCredDialogStatus').textContent = 'Please paste a value.'; return; }
  el('mcpCredDialogStatus').textContent = _mcpCatalogPending.pipPackage
    ? `Installing ${_mcpCatalogPending.pipPackage} and connecting…`
    : 'Connecting…';
  const resp = await fetch('/api/mcp/connect', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ service, credential_value: value, env_key: envKey }),
  });
  const out = await resp.json();
  if (!resp.ok) {
    el('mcpCredDialogStatus').textContent = `Error: ${out.detail || 'failed'}`;
    return;
  }
  el('mcpCredDialog').close();
  _mcpCatalogPending = null;
  await loadMcpCatalog();
  await loadSummary();
}

async function listMcpServers() {
  return loadMcpCatalog();
}

async function createMcpServer() {
  return createMcpServerInternal(false);
}

async function createAndCheckMcpServer() {
  return createMcpServerInternal(true);
}

async function createMcpServerInternal(runCheckAfterCreate) {
  const name = el('mcpName').value.trim();
  const transport = el('mcpTransport').value;
  if (!name) return;

  let args = [];
  let env = {};
  try { args = el('mcpArgs').value.trim() ? JSON.parse(el('mcpArgs').value) : []; } catch (_) { el('mcpStatus').textContent = 'Invalid args JSON'; return; }
  try { env = el('mcpEnv').value.trim() ? JSON.parse(el('mcpEnv').value) : {}; } catch (_) { el('mcpStatus').textContent = 'Invalid env JSON'; return; }

  const payload = {
    name,
    transport,
    url: el('mcpUrl').value.trim() || null,
    command: el('mcpCmd').value.trim() || null,
    args,
    env,
  };

  const resp = await fetch('/api/mcp/servers', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });

  if (!resp.ok) {
    const text = await resp.text();
    el('mcpStatus').textContent = `Failed: ${text}`;
    return;
  }

  const created = await resp.json();

  const createdLines = [];
  (created.validation_report?.checks || []).forEach((c) => {
    createdLines.push(`${c.ok ? 'OK' : 'FAIL'} ${c.step}: ${c.detail}`);
  });
  if ((created.validation_report?.tools || []).length) {
    createdLines.push(`Tools: ${(created.validation_report.tools || []).join(', ')}`);
  }

  if (runCheckAfterCreate && created.id) {
    const checkResp = await fetch(`/api/mcp/servers/${created.id}/check`, { method: 'POST' });
    const checked = await checkResp.json();
    const lines = [];
    (checked.validation_report?.checks || []).forEach((c) => {
      lines.push(`${c.ok ? 'OK' : 'FAIL'} ${c.step}: ${c.detail}`);
    });
    if ((checked.validation_report?.tools || []).length) {
      lines.push(`Tools: ${(checked.validation_report.tools || []).join(', ')}`);
    }
    el('mcpStatus').textContent = lines.join('\n') || 'Server added and checked.';
  } else if (createdLines.length) {
    el('mcpStatus').textContent = createdLines.join('\n');
  } else {
    el('mcpStatus').textContent = 'MCP server added.';
  }

  await listMcpServers();
  await loadSummary();
}


function parseJsonOrEmpty(raw, statusElId, label) {
  const text = (raw || '').trim();
  if (!text) return {};
  try {
    return JSON.parse(text);
  } catch (_) {
    if (statusElId) {
      el(statusElId).textContent = `Invalid ${label} JSON`;
    }
    return null;
  }
}


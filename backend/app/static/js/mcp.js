const AUTH_ICONS  = { none: '🆓', api_key: '🔑', bearer: '🔑', oauth: '🔗' };
const AUTH_LABELS = { none: 'Free', api_key: 'API Key', bearer: 'Token', oauth: 'OAuth' };

let _mcpCatalogPending = null; // { service, envKey, docsUrl }

async function loadMcpCatalog() {
  const resp = await fetch('/api/mcp/catalog');
  if (!resp.ok) return;
  const items = await resp.json();
  const grid = el('mcpCatalogGrid');
  grid.innerHTML = '';
  items.forEach((item) => {
    const tile = document.createElement('div');
    tile.style.cssText = 'background:var(--surface2);border:1px solid var(--border);border-radius:8px;padding:14px;display:flex;flex-direction:column;gap:6px;';
    const connected = item.installed && item.status === 'online';
    const installed = item.installed;
    const authIcon = AUTH_ICONS[item.auth_type] || '🔌';
    const authLabel = AUTH_LABELS[item.auth_type] || item.auth_type;
    tile.innerHTML = `
      <div style="display:flex;align-items:center;justify-content:space-between;">
        <strong style="font-size:13px;">${item.name}</strong>
        <span class="badge ${connected ? 'ok' : installed ? 'offline' : ''}" style="font-size:10px;">${connected ? 'online' : installed ? 'offline' : authIcon + ' ' + authLabel}</span>
      </div>
      <p class="tiny" style="margin:0;color:var(--muted);line-height:1.4;">${item.notes}</p>
      <button data-service="${item.key}" data-auth="${item.auth_type}" data-env-key="${(item.env_keys || [])[0] || ''}" data-docs="${(item.docs || [])[0] || ''}"
        class="${connected ? 'alt' : ''}" style="margin-top:auto;">
        ${connected ? '✓ Connected' : installed ? 'Reconnect' : 'Connect'}
      </button>
    `;
    grid.appendChild(tile);
  });

  grid.querySelectorAll('button[data-service]').forEach((btn) => {
    btn.addEventListener('click', () => mcpCatalogConnect(
      btn.dataset.service,
      btn.dataset.auth,
      btn.dataset.envKey,
      btn.dataset.docs,
    ));
  });
}

async function mcpCatalogConnect(service, authType, envKey, docsUrl) {
  if (authType === 'none') {
    const btn = el('mcpCatalogGrid').querySelector(`button[data-service="${service}"]`);
    if (btn) { btn.textContent = 'Connecting…'; btn.disabled = true; }
    await fetch('/api/mcp/connect', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ service }),
    });
    await loadMcpCatalog();
    await listMcpServers();
    await loadSummary();
    return;
  }

  _mcpCatalogPending = { service, envKey, docsUrl };

  // Title + label
  el('mcpCredDialogTitle').textContent = `Connect ${service}`;
  el('mcpCredDialogLabel').textContent = envKey || 'API Key / Token';
  el('mcpCredDialogInput').value = '';
  el('mcpCredDialogStatus').textContent = '';

  // Hint text
  const isOauth = authType === 'oauth';
  el('mcpCredDialogHint').textContent = isOauth
    ? `Complete OAuth in the tab that opens, copy the token you receive, and paste it below.`
    : `Paste your ${envKey || 'API key'} — stored encrypted in the vault, never sent to the cloud.`;

  // Show / hide the "Get your key" button
  const getKeyBtn = el('mcpCredDialogGetKey');
  if (docsUrl) {
    getKeyBtn.style.display = '';
    getKeyBtn.textContent = isOauth ? '🔗 Open login page →' : '🔑 Get your key →';
    getKeyBtn.onclick = () => window.open(docsUrl, '_blank');
  } else {
    getKeyBtn.style.display = 'none';
  }

  el('mcpCredDialog').showModal();
}

async function mcpCredDialogSubmit() {
  if (!_mcpCatalogPending) return;
  const { service, envKey } = _mcpCatalogPending;
  const value = el('mcpCredDialogInput').value.trim();
  if (!value) { el('mcpCredDialogStatus').textContent = 'Please paste a value.'; return; }
  el('mcpCredDialogStatus').textContent = 'Connecting…';
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
  await listMcpServers();
  await loadSummary();
}

async function listMcpServers() {
  const resp = await fetch('/api/mcp/servers');
  const rows = await resp.json();
  const target = el('mcpList');
  target.innerHTML = '';

  rows.forEach((row) => {
    const item = document.createElement('div');
    item.className = 'list-item';
    const badgeClass = row.status === 'online' ? 'ok' : row.status === 'offline' ? 'offline' : 'unknown';
    const lockBadge = row.is_builtin ? '<span class="badge">locked</span>' : '';
    item.innerHTML = `
      <div><strong>${row.name}</strong> <span class="badge ${badgeClass}">${row.status}</span> ${lockBadge}</div>
      <div class="tiny">${row.transport} | ${row.url || row.command || 'n/a'}</div>
      <div class="row" style="margin-top:8px;">
        <button data-check="${row.id}" class="alt">Check</button>
        ${row.is_builtin ? '' : `<button data-delete="${row.id}" class="warn">Delete</button>`}
      </div>
      <div class="tiny mono">${row.last_error || ''}</div>
      <div class="tiny mono" id="mcpReport-${row.id}"></div>
    `;
    target.appendChild(item);
  });

  target.querySelectorAll('button[data-check]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const id = btn.getAttribute('data-check');
      const resp = await fetch(`/api/mcp/servers/${id}/check`, { method: 'POST' });
      const out = await resp.json();
      const lines = [];
      (out.validation_report?.checks || []).forEach((c) => {
        lines.push(`${c.ok ? 'OK' : 'FAIL'} ${c.step}: ${c.detail}`);
      });
      if ((out.validation_report?.tools || []).length) {
        lines.push(`Tools: ${(out.validation_report.tools || []).join(', ')}`);
      }
      if (lines.length) {
        el('mcpStatus').textContent = lines.join('\n');
      }
      await listMcpServers();
    });
  });
  target.querySelectorAll('button[data-delete]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const id = btn.getAttribute('data-delete');
      await fetch(`/api/mcp/servers/${id}`, { method: 'DELETE' });
      await listMcpServers();
      await loadSummary();
    });
  });
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


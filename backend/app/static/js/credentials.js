function populateCredentialSelectors() {
  const options = ['integrationCredentialRef'];
  options.forEach((id) => {
    const node = el(id);
    if (!node) return;
    node.innerHTML = '';
    const blank = document.createElement('option');
    blank.value = '';
    blank.textContent = '-- select credential --';
    node.appendChild(blank);
    state.credentials.forEach((cred) => {
      const opt = document.createElement('option');
      opt.value = cred.name;
      opt.textContent = `${cred.name} (${cred.provider || cred.credential_type})`;
      node.appendChild(opt);
    });
  });
}

function renderCredentialList(rows) {
  const wrap = el('credentialList');
  if (!wrap) return;
  wrap.innerHTML = '';
  rows.forEach((row) => {
    const item = document.createElement('div');
    item.className = 'list-item';
    item.innerHTML = `
      <div><strong>${row.name}</strong></div>
      <div class="tiny">${row.credential_type} | ${row.provider || 'no provider'} | ${row.username || 'no username'}</div>
      <div class="tiny mono">ref: {{cred:${row.name}}}</div>
      <div class="tiny">updated: ${row.updated_at}</div>
      <div class="row" style="margin-top:8px;">
        <button data-copy-cred-ref="${row.name}" class="alt">Copy Ref</button>
        <button data-delete-cred="${row.id}" class="warn">Delete</button>
      </div>
    `;
    wrap.appendChild(item);
  });

  wrap.querySelectorAll('button[data-copy-cred-ref]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const ref = `{{cred:${btn.getAttribute('data-copy-cred-ref')}}}`;
      try {
        await navigator.clipboard.writeText(ref);
        el('credentialStatus').textContent = `Copied ${ref}`;
      } catch (_) {
        el('credentialStatus').textContent = `Reference: ${ref}`;
      }
    });
  });

  wrap.querySelectorAll('button[data-delete-cred]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const id = btn.getAttribute('data-delete-cred');
      const resp = await fetch(`/api/credentials/${id}`, { method: 'DELETE' });
      if (!resp.ok) {
        el('credentialStatus').textContent = `Delete failed: ${await resp.text()}`;
        return;
      }
      await listCredentials();
    });
  });
}

async function listCredentials() {
  const resp = await fetch('/api/credentials');
  if (!resp.ok) {
    const out = await resp.text();
    if (el('credentialStatus')) el('credentialStatus').textContent = `Vault unavailable: ${out}`;
    return;
  }
  const rows = await resp.json();
  state.credentials = rows;
  populateCredentialSelectors();
  renderCredentialList(rows);
}

async function createCredential() {
  const name = el('credentialName').value.trim();
  const secret = el('credentialSecret').value;
  if (!name || !secret) {
    el('credentialStatus').textContent = 'Name and secret are required.';
    return;
  }

  const meta = parseJsonOrEmpty(el('credentialMeta').value, 'credentialStatus', 'meta');
  if (meta === null) return;

  const resp = await fetch('/api/credentials', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      name,
      credential_type: el('credentialType').value,
      provider: el('credentialProvider').value.trim() || null,
      username: el('credentialUsername').value.trim() || null,
      secret,
      meta,
    }),
  });

  if (!resp.ok) {
    el('credentialStatus').textContent = `Store failed: ${await resp.text()}`;
    return;
  }

  el('credentialStatus').textContent = 'Credential stored in encrypted vault.';
  el('credentialSecret').value = '';
  await listCredentials();
}

async function importCredentialsEnv() {
  const envText = el('credentialImportEnv').value.trim();
  if (!envText) {
    el('credentialImportStatus').textContent = 'Paste .env content first.';
    return;
  }

  const resp = await fetch('/api/credentials/import-env', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      env_text: envText,
      provider: el('credentialImportProvider').value.trim() || null,
      credential_type: el('credentialImportType').value,
      overwrite: !!el('credentialImportOverwrite').checked,
    }),
  });

  if (!resp.ok) {
    el('credentialImportStatus').textContent = `Import failed: ${await resp.text()}`;
    return;
  }

  const out = await resp.json();
  el('credentialImportStatus').textContent = `Imported ${out.imported.length}, updated ${out.updated.length}, skipped ${out.skipped.length}.`;
  await listCredentials();
}

async function loadCredentialConnectors() {
  const resp = await fetch('/api/credentials/connectors');
  if (!resp.ok) return;
  const out = await resp.json();
  state.connectors = out;

  const sel = el('connectorProvider');
  if (sel) {
    sel.innerHTML = '';
    Object.keys(out).forEach((name) => {
      const opt = document.createElement('option');
      opt.value = name;
      opt.textContent = `${name} - ${out[name].title}`;
      sel.appendChild(opt);
    });
  }
}

async function launchConnector(provider = null, openBrowser = true, outElement = 'connectorStatus') {
  const chosen = provider || (el('connectorProvider') ? el('connectorProvider').value : '');
  if (!chosen) return;

  const resp = await fetch('/api/credentials/connectors/launch', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ provider: chosen, open_browser: openBrowser }),
  });
  if (!resp.ok) {
    el(outElement).textContent = `Connector launch failed: ${await resp.text()}`;
    return;
  }
  const out = await resp.json();
  const lines = [
    `${out.title}`,
    `URL: ${out.auth_url}`,
    `Suggested env: ${out.suggested_env}`,
    out.launched ? 'Browser launch attempted successfully.' : 'Browser did not launch automatically. Open URL manually.',
  ];
  if (out.launch_error) lines.push(`Launch error: ${out.launch_error}`);
  el(outElement).textContent = lines.join('\n');
}


function useCredentialForIntegration() {
  const credentialName = el('integrationCredentialRef').value;
  if (!credentialName) {
    el('integrationStatusOut').textContent = 'Select a credential first.';
    return;
  }
  el('integrationApiKey').value = `{{cred:${credentialName}}}`;
  el('integrationStatusOut').textContent = `Integration key now uses {{cred:${credentialName}}}`;
}

async function loadHubAccess() {
  const target = el('hubAccessOut');
  if (!target) return;
  const resp = await fetch('/api/hub/access');
  if (!resp.ok) {
    target.textContent = `Failed to load hub access: ${await resp.text()}`;
    return;
  }
  const out = await resp.json();
  target.textContent = [
    `Configured host: ${out.configured_host}`,
    `Port: ${out.port}`,
    'Reachable URLs:',
    ...(out.reachable_urls || []),
    '',
    out.note,
  ].join('\n');
}


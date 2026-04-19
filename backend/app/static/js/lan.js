// lan.js — LAN device manager + crow-agent network panel

let _lanDevices = [];

// ── Render ────────────────────────────────────────────────────────────────────

function renderLanDevices() {
  const list = el('lanDeviceList');
  if (!list) return;
  if (!_lanDevices.length) {
    list.innerHTML = '<p class="status">No devices added yet. Run a scan or add one manually.</p>';
    return;
  }
  list.innerHTML = _lanDevices.map((d) => `
    <article class="card lan-device-card" data-id="${d.id}">
      <div class="lan-device-header">
        <span class="lan-status-dot ${d.status === 'online' ? 'online' : d.status === 'offline' ? 'offline' : ''}"></span>
        <strong>${esc(d.label)}</strong>
        <span class="tiny mono" style="color:var(--text-dim)">${esc(d.ip)}:${d.port}</span>
        ${d.hostname ? `<span class="tiny" style="color:var(--text-dim)">(${esc(d.hostname)})</span>` : ''}
        ${d.platform ? `<span class="tiny badge">${esc(d.platform)}</span>` : ''}
      </div>
      ${d.notes ? `<p class="tiny" style="color:var(--text-dim);margin:4px 0 0">${esc(d.notes)}</p>` : ''}
      <div class="lan-device-actions">
        <button onclick="lanPing(${d.id})" class="small-btn">Ping</button>
        <button onclick="lanFetchInfo(${d.id})" class="small-btn">System Info</button>
        <button onclick="lanFetchCopilot(${d.id})" class="small-btn">Copilot History</button>
        <button onclick="lanHarvestCopilot(${d.id})" class="small-btn" title="Pull all VS Code transcripts and embed to knowledge base">📥 Import History</button>
        <button onclick="lanFetchExtensions(${d.id})" class="small-btn">Extensions</button>
        <button onclick="lanBrowse(${d.id}, '~')" class="small-btn">Browse Files</button>
        <button onclick="lanDeleteDevice(${d.id})" class="small-btn danger">Remove</button>
      </div>
      <div id="lanResult-${d.id}" class="lan-result"></div>
    </article>
  `).join('');
}

function esc(s) {
  return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function _setLanResult(deviceId, html) {
  const el2 = document.getElementById(`lanResult-${deviceId}`);
  if (el2) el2.innerHTML = html;
}

// ── API calls ─────────────────────────────────────────────────────────────────

async function loadLanDevices() {
  try {
    const resp = await fetch('/api/lan/devices');
    const data = await resp.json();
    _lanDevices = data.devices || [];
    renderLanDevices();
  } catch (e) {
    console.error('loadLanDevices:', e);
  }
}

async function lanPing(deviceId) {
  _setLanResult(deviceId, '<span class="tiny">Pinging…</span>');
  const resp = await fetch(`/api/lan/devices/${deviceId}/ping`, { method: 'POST' });
  const data = await resp.json();
  if (data.ok) {
    const d = _lanDevices.find((x) => x.id === deviceId);
    if (d) d.status = data.status;
    renderLanDevices();
    _setLanResult(deviceId, `<span class="tiny ${data.status === 'online' ? 'ok' : 'err'}">${data.status === 'online' ? '✓ Online' : '✗ Offline'}</span>`);
  }
}

async function lanFetchInfo(deviceId) {
  _setLanResult(deviceId, '<span class="tiny">Fetching system info…</span>');
  const resp = await fetch(`/api/lan/devices/${deviceId}/info`);
  const data = await resp.json();
  if (!data.ok) { _setLanResult(deviceId, `<span class="err tiny">${esc(data.error)}</span>`); return; }
  const info = data.info || {};
  _setLanResult(deviceId, `
    <details open><summary class="tiny"><strong>System Info</strong></summary>
    <pre class="mono tiny">${esc(JSON.stringify(info, null, 2))}</pre>
    </details>
  `);
  await loadLanDevices();
}

async function lanFetchCopilot(deviceId) {
  _setLanResult(deviceId, '<span class="tiny">Fetching Copilot history…</span>');
  const resp = await fetch(`/api/lan/devices/${deviceId}/copilot`);
  const data = await resp.json();
  if (!data.ok) { _setLanResult(deviceId, `<span class="err tiny">${esc(data.error)}</span>`); return; }
  const history = data.history || {};
  const sessions = history.vscode_sessions || data.sessions || [];
  const cli = history.copilot_cli || [];
  const basesChecked = history.bases_checked || [];
  const os = history.os || 'unknown';

  if (!sessions.length && !cli.length) {
    const basesHtml = basesChecked.length
      ? `<p class="tiny" style="color:var(--text-dim);margin:4px 0">Searched: ${basesChecked.map(esc).join(', ')}</p>`
      : '';
    _setLanResult(deviceId, `<span class="tiny">No Copilot sessions found (OS: ${esc(os)}).</span>${basesHtml}`);
    return;
  }

  const bySource = {};
  for (const s of sessions) {
    const src = s.source || 'vscode';
    if (!bySource[src]) bySource[src] = [];
    bySource[src].push(s);
  }

  let html = `<div class="tiny"><strong>OS: ${esc(os)}</strong>`;
  if (basesChecked.length) html += ` <span style="color:var(--text-dim)">— checked ${basesChecked.length} path(s)</span>`;
  html += '</div>';

  for (const [src, items] of Object.entries(bySource)) {
    const label = src === 'vscode-transcripts' ? '💬 Transcripts' : src === 'vscode-debug-logs' ? '🐛 Debug Logs' : '📄 Chat JSON';
    html += `<details open><summary class="tiny" style="margin-top:8px"><strong>${label} (${items.length})</strong></summary>
    <ul class="tiny mono" style="padding-left:1rem;margin:4px 0;max-height:200px;overflow-y:auto">
      ${items.map((s) => `<li title="${esc(s.file)}">${esc(s.filename || s.file)} <span style="color:var(--text-dim)">(${Math.round((s.size||0)/1024)}KB)</span></li>`).join('')}
    </ul></details>`;
  }

  if (cli.length) {
    html += `<details><summary class="tiny" style="margin-top:8px"><strong>🖥 Copilot CLI (${cli.length})</strong></summary>
    <ul class="tiny mono" style="padding-left:1rem;margin:4px 0;max-height:120px;overflow-y:auto">
      ${cli.map((s) => `<li>${esc(s.file)} <span style="color:var(--text-dim)">(${Math.round((s.size||0)/1024)}KB)</span></li>`).join('')}
    </ul></details>`;
  }

  _setLanResult(deviceId, html);
}

async function lanHarvestCopilot(deviceId) {
  _setLanResult(deviceId, '<span class="tiny">📥 Importing Copilot history… this may take a minute while transcripts are read and embedded.</span>');
  try {
    const resp = await fetch(`/api/lan/devices/${deviceId}/copilot/harvest`, { method: 'POST' });
    const data = await resp.json();
    if (!data.ok) {
      _setLanResult(deviceId, `<span class="err tiny">${esc(data.error)}</span>`);
      return;
    }
    _setLanResult(deviceId, `<span class="tiny" style="color:var(--green-hi)">✓ Imported ${data.ingested} new session(s). View them in the Copilot History tab.</span>`);
  } catch (e) {
    _setLanResult(deviceId, `<span class="err tiny">Import failed: ${esc(e.message)}</span>`);
  }
}
  _setLanResult(deviceId, '<span class="tiny">Fetching extensions…</span>');
  const resp = await fetch(`/api/lan/devices/${deviceId}/extensions`);
  const data = await resp.json();
  if (!data.ok) { _setLanResult(deviceId, `<span class="err tiny">${esc(data.error)}</span>`); return; }
  const exts = data.extensions || [];
  _setLanResult(deviceId, `
    <details><summary class="tiny"><strong>Extensions (${exts.length})</strong></summary>
    <ul class="tiny mono" style="padding-left:1rem;margin:4px 0;max-height:200px;overflow-y:auto">
      ${exts.map((e) => `<li>${esc(e)}</li>`).join('')}
    </ul>
    </details>
  `);
}

async function lanBrowse(deviceId, path) {
  _setLanResult(deviceId, '<span class="tiny">Listing…</span>');
  const resp = await fetch(`/api/lan/devices/${deviceId}/ls?path=${encodeURIComponent(path)}`);
  const data = await resp.json();
  if (!data.ok) { _setLanResult(deviceId, `<span class="err tiny">${esc(data.error)}</span>`); return; }
  const entries = data.entries || [];
  _setLanResult(deviceId, `
    <details open><summary class="tiny"><strong>📂 ${esc(data.path)}</strong></summary>
    <ul class="tiny mono" style="padding-left:1rem;margin:4px 0;max-height:240px;overflow-y:auto">
      ${path !== '~' && path !== '/' ? `<li><a href="#" onclick="lanBrowse(${deviceId}, '${esc(path.split('/').slice(0,-1).join('/') || '/')}');return false;">⬆ ..</a></li>` : ''}
      ${entries.map((e) => e.is_dir
        ? `<li>📁 <a href="#" onclick="lanBrowse(${deviceId}, '${esc(data.path + '/' + e.name)}');return false;">${esc(e.name)}/</a></li>`
        : `<li>📄 ${esc(e.name)} <span style="color:var(--text-dim)">${e.size != null ? Math.round(e.size/1024)+'KB' : ''}</span></li>`
      ).join('')}
    </ul>
    </details>
  `);
}

// ── Add device form ───────────────────────────────────────────────────────────

async function lanAddDevice() {
  const label = el('lanNewLabel').value.trim();
  const ip = el('lanNewIp').value.trim();
  const port = parseInt(el('lanNewPort').value.trim()) || 8788;
  const key = el('lanNewKey').value.trim();
  const notes = el('lanNewNotes').value.trim();
  if (!label || !ip) { el('lanAddStatus').textContent = 'Label and IP are required.'; return; }
  el('lanAddStatus').textContent = 'Adding…';
  const resp = await fetch('/api/lan/devices', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ label, ip, port, api_key: key || null, notes: notes || null }),
  });
  const data = await resp.json();
  if (data.ok) {
    el('lanNewLabel').value = '';
    el('lanNewIp').value = '';
    el('lanNewKey').value = '';
    el('lanNewNotes').value = '';
    el('lanAddStatus').textContent = '✓ Added';
    await loadLanDevices();
  } else {
    el('lanAddStatus').textContent = data.error || 'Failed';
  }
}

async function lanDeleteDevice(deviceId) {
  if (!confirm('Remove this device?')) return;
  await fetch(`/api/lan/devices/${deviceId}`, { method: 'DELETE' });
  await loadLanDevices();
}

// ── LAN Scan ──────────────────────────────────────────────────────────────────

async function runLanScan() {
  const out = el('lanScanOut');
  const btn = el('lanScanBtn');
  if (out) out.innerHTML = '<span class="tiny">Scanning… (ARP table + ping sweep, may take ~30s)</span>';
  if (btn) btn.disabled = true;
  try {
    const subnet = (el('lanSubnet') && el('lanSubnet').value.trim()) || undefined;
    const url = subnet ? `/api/lan/scan?subnet=${encodeURIComponent(subnet)}` : '/api/lan/scan';
    const resp = await fetch(url, { method: 'POST' });
    const data = await resp.json();
    if (!data.ok) { if (out) out.innerHTML = `<span class="err tiny">${esc(data.error)}</span>`; return; }
    const devices = data.devices || [];
    if (out) out.innerHTML = `
      <p class="tiny">Found <strong>${data.total_found}</strong> hosts — <strong>${data.crow_agents}</strong> with crow-agent</p>
      <ul class="tiny mono" style="margin:4px 0;padding-left:1rem;max-height:300px;overflow-y:auto">
        ${devices.map((d) => `
          <li>
            ${d.has_crow_agent ? '🟢' : '⚫'} <strong>${esc(d.ip)}</strong>
            ${d.hostname ? ` — ${esc(d.hostname)}` : ''}
            ${d.mac ? ` <span style="color:var(--text-dim)">${esc(d.mac)}</span>` : ''}
            ${d.has_crow_agent ? ` <button class="small-btn" onclick="lanQuickAdd('${esc(d.ip)}', '${esc(d.crow_info && d.crow_info.hostname || d.ip)}')">Add</button>` : ''}
          </li>
        `).join('')}
      </ul>
    `;
  } catch (e) {
    if (out) out.innerHTML = `<span class="err tiny">${esc(e.message)}</span>`;
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function lanQuickAdd(ip, hostname) {
  const resp = await fetch('/api/lan/devices', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ label: hostname, ip, port: 8788 }),
  });
  const data = await resp.json();
  if (data.ok) await loadLanDevices();
}

// ── Router Management (OPNsense / pfSense) ────────────────────────────────────

let _networkRouters = [];

async function loadNetworkRouters() {
  try {
    const resp = await fetch('/api/routers');
    const data = await resp.json();
    _networkRouters = data.routers || [];
    renderNetworkRouters();
  } catch (e) {
    console.error('loadNetworkRouters:', e);
  }
}

function renderNetworkRouters() {
  const list = el('routerList');
  if (!list) return;
  if (!_networkRouters.length) {
    list.innerHTML = '<p class="status">No routers added yet.</p>';
    return;
  }
  list.innerHTML = _networkRouters.map((r) => `
    <article class="card lan-device-card" data-router-id="${r.id}">
      <div class="lan-device-header">
        <span class="lan-status-dot ${r.status === 'online' ? 'online' : r.status === 'offline' ? 'offline' : ''}"></span>
        <strong>${esc(r.label)}</strong>
        <span class="tiny mono" style="color:var(--text-dim)">${esc(r.host)}:${r.port}</span>
        <span class="tiny badge">${esc(r.router_type)}</span>
        ${r.allow_writes ? '<span class="tiny badge" style="background:rgba(255,80,80,.15);color:#f88">read+write</span>' : '<span class="tiny badge">read-only</span>'}
      </div>
      ${r.notes ? `<p class="tiny" style="color:var(--text-dim);margin:4px 0 0">${esc(r.notes)}</p>` : ''}
      <div class="lan-device-actions">
        <button onclick="routerPing(${r.id})" class="small-btn">Ping</button>
        ${r.router_type === 'opnsense' ? `
          <button onclick="routerFetch(${r.id},'opnsense/interfaces')" class="small-btn">Interfaces</button>
          <button onclick="routerFetch(${r.id},'opnsense/leases')" class="small-btn">DHCP Leases</button>
          <button onclick="routerFetch(${r.id},'opnsense/arp')" class="small-btn">ARP Table</button>
          <button onclick="routerFetch(${r.id},'opnsense/firewall')" class="small-btn">Firewall Rules</button>
          <button onclick="routerFetch(${r.id},'opnsense/services')" class="small-btn">Services</button>
          <button onclick="routerFetch(${r.id},'opnsense/firmware')" class="small-btn">Firmware</button>
        ` : `
          <button onclick="routerFetch(${r.id},'pfsense/interfaces')" class="small-btn">Interfaces</button>
          <button onclick="routerFetch(${r.id},'pfsense/arp')" class="small-btn">ARP Table</button>
          <button onclick="routerFetch(${r.id},'pfsense/firewall')" class="small-btn">Firewall Rules</button>
          <button onclick="routerSsh(${r.id})" class="small-btn">Run Command</button>
        `}
        <button onclick="routerSnapshots(${r.id})" class="small-btn">Snapshots</button>
        <button onclick="routerDelete(${r.id})" class="small-btn danger">Remove</button>
      </div>
      <div id="routerResult-${r.id}" class="lan-result"></div>
    </article>
  `).join('');
}

function _setRouterResult(routerId, html) {
  const el2 = document.getElementById(`routerResult-${routerId}`);
  if (el2) el2.innerHTML = html;
}

async function routerPing(routerId) {
  _setRouterResult(routerId, '<span class="tiny">Connecting…</span>');
  const resp = await fetch(`/api/routers/${routerId}/ping`, { method: 'POST' });
  const data = await resp.json();
  if (data.ok) {
    const r = _networkRouters.find((x) => x.id === routerId);
    if (r) r.status = data.status;
    renderNetworkRouters();
    _setRouterResult(routerId, `<span class="tiny ${data.status === 'online' ? 'ok' : 'err'}">${data.status === 'online' ? '✓ Reachable' : '✗ Unreachable'}</span>`);
  } else {
    _setRouterResult(routerId, `<span class="err tiny">${esc(data.error)}</span>`);
  }
}

async function routerFetch(routerId, endpoint) {
  _setRouterResult(routerId, `<span class="tiny">Fetching ${endpoint}…</span>`);
  const resp = await fetch(`/api/routers/${routerId}/${endpoint}`);
  const data = await resp.json();
  const label = endpoint.split('/').pop().replace(/_/g, ' ');
  if (!data.ok) { _setRouterResult(routerId, `<span class="err tiny">${esc(data.error)}</span>`); return; }
  const content = data.data || data.stdout || data;
  _setRouterResult(routerId, `
    <details open>
      <summary class="tiny"><strong>${label}</strong> — <span style="color:var(--text-dim)">snapshot saved</span></summary>
      <pre class="mono tiny" style="max-height:300px;overflow-y:auto;white-space:pre-wrap">${esc(typeof content === 'string' ? content : JSON.stringify(content, null, 2))}</pre>
    </details>
  `);
}

async function routerSsh(routerId) {
  const cmd = prompt('Run command on pfSense (SSH):');
  if (!cmd) return;
  _setRouterResult(routerId, `<span class="tiny">Running: ${esc(cmd)}</span>`);
  const resp = await fetch(`/api/routers/${routerId}/pfsense/exec`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ command: cmd }),
  });
  const data = await resp.json();
  if (!data.ok) { _setRouterResult(routerId, `<span class="err tiny">${esc(data.error)}</span>`); return; }
  _setRouterResult(routerId, `
    <details open>
      <summary class="tiny"><strong>$ ${esc(cmd)}</strong></summary>
      <pre class="mono tiny" style="max-height:300px;overflow-y:auto;white-space:pre-wrap">${esc(data.stdout)}</pre>
      ${data.stderr ? `<pre class="mono tiny err" style="max-height:100px;overflow-y:auto">${esc(data.stderr)}</pre>` : ''}
    </details>
  `);
}

async function routerSnapshots(routerId) {
  _setRouterResult(routerId, '<span class="tiny">Loading snapshots…</span>');
  const resp = await fetch(`/api/routers/${routerId}/snapshots`);
  const data = await resp.json();
  if (!data.ok) { _setRouterResult(routerId, `<span class="err tiny">${esc(data.error)}</span>`); return; }
  const snaps = data.snapshots || [];
  if (!snaps.length) { _setRouterResult(routerId, '<span class="tiny">No snapshots yet.</span>'); return; }
  _setRouterResult(routerId, `
    <details open>
      <summary class="tiny"><strong>Snapshots (${snaps.length})</strong></summary>
      <ul class="tiny mono" style="padding-left:1rem;margin:4px 0;max-height:200px;overflow-y:auto">
        ${snaps.map((s) => `<li>
          <a href="#" onclick="routerLoadSnapshot(${routerId},${s.id});return false;">${esc(s.snapshot_type)}</a>
          <span style="color:var(--text-dim)"> — ${esc(s.captured_at)}</span>
        </li>`).join('')}
      </ul>
    </details>
  `);
}

async function routerLoadSnapshot(routerId, snapshotId) {
  const resp = await fetch(`/api/routers/${routerId}/snapshots/${snapshotId}`);
  const data = await resp.json();
  if (!data.ok) { _setRouterResult(routerId, `<span class="err tiny">${esc(data.error)}</span>`); return; }
  const snap = data.snapshot;
  const parsed = JSON.parse(snap.data_json || '{}');
  _setRouterResult(routerId, `
    <details open>
      <summary class="tiny"><strong>${esc(snap.snapshot_type)}</strong> snapshot — ${esc(snap.captured_at)}</summary>
      <pre class="mono tiny" style="max-height:300px;overflow-y:auto;white-space:pre-wrap">${esc(JSON.stringify(parsed, null, 2))}</pre>
    </details>
  `);
}

async function routerDelete(routerId) {
  if (!confirm('Remove this router?')) return;
  await fetch(`/api/routers/${routerId}`, { method: 'DELETE' });
  await loadNetworkRouters();
}

async function addNetworkRouter() {
  const label = el('routerNewLabel').value.trim();
  const host = el('routerNewHost').value.trim();
  const type = el('routerNewType').value;
  const port = parseInt(el('routerNewPort').value.trim()) || (type === 'opnsense' ? 443 : 22);
  const apiKey = el('routerNewApiKey').value.trim();
  const apiSecret = el('routerNewApiSecret').value.trim();
  const sshUser = el('routerNewSshUser').value.trim();
  const sshPass = el('routerNewSshPass').value.trim();
  const allowWrites = el('routerAllowWrites').checked;
  const notes = el('routerNewNotes').value.trim();
  const statusEl = el('routerAddStatus');
  if (!label || !host) { statusEl.textContent = 'Label and host are required.'; return; }
  statusEl.textContent = 'Adding…';
  const resp = await fetch('/api/routers', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      label, host, router_type: type, port,
      api_key: apiKey || null, api_secret: apiSecret || null,
      ssh_user: sshUser || null, ssh_password: sshPass || null,
      allow_writes: allowWrites, notes: notes || null,
    }),
  });
  const data = await resp.json();
  if (data.ok) {
    statusEl.textContent = '✓ Added';
    ['routerNewLabel','routerNewHost','routerNewApiKey','routerNewApiSecret','routerNewSshUser','routerNewSshPass','routerNewNotes'].forEach((id) => { const e = el(id); if (e) e.value = ''; });
    el('routerAllowWrites').checked = false;
    await loadNetworkRouters();
  } else {
    statusEl.textContent = data.error || 'Failed';
  }
}

function toggleRouterForm(type) {
  const opnFields = el('opnsenseFields');
  const pfFields = el('pfsenseFields');
  if (opnFields) opnFields.style.display = type === 'opnsense' ? '' : 'none';
  if (pfFields) pfFields.style.display = type === 'pfsense' ? '' : 'none';
  const portEl = el('routerNewPort');
  if (portEl && !portEl._userEdited) portEl.value = type === 'opnsense' ? '443' : '22';
}

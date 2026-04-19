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
  const sessions = data.sessions || [];
  if (!sessions.length) { _setLanResult(deviceId, '<span class="tiny">No Copilot sessions found.</span>'); return; }
  _setLanResult(deviceId, `
    <details open><summary class="tiny"><strong>Copilot Sessions (${sessions.length})</strong></summary>
    <ul class="tiny mono" style="padding-left:1rem;margin:4px 0;">
      ${sessions.map((s) => `<li>${esc(s.file)} <span style="color:var(--text-dim)">(${Math.round(s.size/1024)}KB)</span></li>`).join('')}
    </ul>
    </details>
  `);
}

async function lanFetchExtensions(deviceId) {
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

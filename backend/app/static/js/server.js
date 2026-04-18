/* ── Server Stats ───────────────────────────────────────────────── */
async function loadServerStats() {
  try {
    const resp = await fetch('/api/system/server-stats');
    if (!resp.ok) return;
    const s = await resp.json();
    const net = s.network || {};
    const cpu = s.cpu || {};
    const mem = s.memory || {};
    const disk = s.disk || {};
    const qemu = s.qemu || {};

    // LAN access card
    el('srvPrimaryIp').textContent = net.primary_lan_ip || '—';
    el('srvHostname').textContent = net.hostname || s.hostname || '—';
    el('srvHypervisor').textContent = qemu.hypervisor || (qemu.detected ? 'detected' : 'bare-metal / unknown');
    el('srvGuestAgent').textContent = qemu.guest_agent_available
      ? `✅ ${qemu.guest_agent_path || 'present'}${qemu.guest_agent_version ? ' v' + qemu.guest_agent_version : ''}`
      : '—';
    el('srvUiUrl').textContent = net.ui_url || '—';
    el('srvMcpRelayUrl').textContent = net.mcp_relay_url || '—';

    const ifaceContainer = el('srvInterfaces');
    ifaceContainer.innerHTML = '';
    (net.interfaces || []).forEach((iface) => {
      if (iface.is_loopback) return;
      const tag = document.createElement('span');
      tag.className = 'iface-tag';
      tag.textContent = `${iface.interface}: ${iface.ip}/${iface.prefix}`;
      ifaceContainer.appendChild(tag);
    });

    // Metrics card
    el('srvCpuModel').textContent = cpu.model || '—';
    el('srvCpuCores').textContent = cpu.count ? `${cpu.count} logical` : '—';
    el('srvCpuLoad').textContent = cpu.load_1m != null ? `${cpu.load_1m} / ${cpu.load_5m} / ${cpu.load_15m}` : '—';

    el('srvMemTotal').textContent = mem.total_mb ? `${mem.total_mb} MB` : '—';
    el('srvMemUsed').textContent = mem.used_mb != null ? `${mem.used_mb} MB used / ${mem.available_mb} MB free (${mem.used_pct}%)` : '—';
    const memBar = el('srvMemBar');
    memBar.style.width = `${mem.used_pct || 0}%`;
    memBar.className = 'progress-bar' + (mem.used_pct > 85 ? ' danger' : mem.used_pct > 65 ? ' warn' : '');

    el('srvDiskTotal').textContent = disk.total_gb ? `${disk.total_gb} GB` : '—';
    el('srvDiskUsed').textContent = disk.used_gb != null ? `${disk.used_gb} GB used / ${disk.free_gb} GB free (${disk.used_pct}%)` : '—';
    const diskBar = el('srvDiskBar');
    diskBar.style.width = `${disk.used_pct || 0}%`;
    diskBar.className = 'progress-bar' + (disk.used_pct > 85 ? ' danger' : disk.used_pct > 65 ? ' warn' : '');

    el('srvUptime').textContent = (s.uptime || {}).human || '—';
    el('srvKernel').textContent = `${s.os || ''} ${s.kernel || ''}`.trim() || '—';

    // Update persistent stat strip with hardware info
    state.serverStats = s;
    renderStatStrip(state.lastSummary, s);
  } catch (_) {}
}

/* ── Log Stream ─────────────────────────────────────────────────── */
let _logEs = null;
let _logPaused = false;
let _logLineCount = 0;
const MAX_LOG_LINES = 1000;

function _logLevel(line) {
  if (/\bERROR\b|\bCRITICAL\b|\bException\b|Traceback/i.test(line)) return 'log-err';
  if (/\bWARNING\b|\bWARN\b/i.test(line)) return 'log-warn';
  if (/\bDEBUG\b/i.test(line)) return 'log-dbg';
  return 'log-info';
}

function appendLogLine(rawLine) {
  if (_logPaused) return;
  const filter = el('logFilter').value.trim().toLowerCase();
  if (filter && !rawLine.toLowerCase().includes(filter)) return;

  const container = el('logStream');
  const div = document.createElement('div');
  div.className = _logLevel(rawLine);
  div.textContent = rawLine;
  container.appendChild(div);
  _logLineCount++;

  // Trim excess lines from the top
  while (_logLineCount > MAX_LOG_LINES && container.firstChild) {
    container.removeChild(container.firstChild);
    _logLineCount--;
  }

  if (el('logAutoScrollToggle').checked) {
    container.scrollTop = container.scrollHeight;
  }
}

function startLogStream() {
  if (_logEs) { _logEs.close(); _logEs = null; }
  el('logStreamStatus').textContent = 'Connecting…';
  const es = new EventSource('/api/system/logs/stream');
  _logEs = es;

  es.onopen = () => {
    el('logStreamStatus').textContent = '🟢 Live';
  };
  es.onmessage = (evt) => {
    try {
      const line = JSON.parse(evt.data);
      appendLogLine(line);
    } catch (_) {
      appendLogLine(evt.data);
    }
  };
  es.onerror = () => {
    el('logStreamStatus').textContent = '🔴 Disconnected — retrying…';
    // Browser auto-reconnects SSE; update label after a moment
    setTimeout(() => {
      if (es.readyState === EventSource.OPEN) {
        el('logStreamStatus').textContent = '🟢 Live';
      }
    }, 3000);
  };
}


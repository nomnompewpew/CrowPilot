async function listIntegrations() {
  const resp = await fetch('/api/integrations');
  const rows = await resp.json();
  const wrap = el('integrationList');
  wrap.innerHTML = '';

  rows.forEach((row) => {
    const item = document.createElement('div');
    item.className = 'list-item';
    const models = (row.models || []).slice(0, 5).join(', ');
    item.innerHTML = `
      <div><strong>${row.name}</strong></div>
      <div class="tiny">${row.provider_kind} | ${row.status} | ${row.auth_type}</div>
      <div class="tiny mono">${row.base_url || 'no base_url set'}</div>
      <div class="tiny">Models: ${models || 'none synced yet'}</div>
      <div class="row" style="margin-top:8px;">
        <button data-sync-integration="${row.id}">Sync Models</button>
        <button data-delete-integration="${row.id}" class="warn">Delete</button>
      </div>
    `;
    wrap.appendChild(item);
  });

  wrap.querySelectorAll('button[data-sync-integration]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const id = btn.getAttribute('data-sync-integration');
      await fetch(`/api/integrations/${id}/sync-models`, { method: 'POST' });
      await listIntegrations();
      await refreshHealth();
    });
  });

  wrap.querySelectorAll('button[data-delete-integration]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const id = btn.getAttribute('data-delete-integration');
      await fetch(`/api/integrations/${id}`, { method: 'DELETE' });
      await listIntegrations();
      await refreshHealth();
    });
  });
}

async function createIntegration() {
  const name = el('integrationName').value.trim();
  const providerKind = el('integrationKind').value.trim();
  if (!name || !providerKind) return;

  const resp = await fetch('/api/integrations', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      name,
      provider_kind: providerKind,
      base_url: el('integrationBaseUrl').value.trim() || null,
      auth_type: el('integrationAuthType').value,
      api_key: el('integrationApiKey').value.trim() || null,
      default_model: el('integrationDefaultModel').value.trim() || null,
      status: el('integrationStatus').value,
      meta: {},
    }),
  });

  if (!resp.ok) {
    el('integrationStatusOut').textContent = `Failed: ${await resp.text()}`;
    return;
  }

  el('integrationStatusOut').textContent = 'Integration added.';
  await listIntegrations();
  await refreshHealth();
}

async function loadOauthTemplates() {
  const resp = await fetch('/api/integrations/oauth-templates');
  const data = await resp.json();
  const lines = [];
  Object.entries(data).forEach(([name, block]) => {
    lines.push(`${name.toUpperCase()} - ${block.title}`);
    block.steps.forEach((step, idx) => lines.push(`  ${idx + 1}. ${step}`));
    lines.push('');
  });
  el('oauthTemplates').textContent = lines.join('\n');
}

async function runSensitivePreview() {
  const text = el('sensitiveInput').value.trim();
  if (!text) return;
  const manualTags = el('sensitiveManualTags').value
    .split(',')
    .map((x) => x.trim())
    .filter(Boolean);
  const manualUntags = el('sensitiveManualUntags').value
    .split(',')
    .map((x) => x.trim())
    .filter(Boolean);

  const resp = await fetch('/api/sensitive/redact-preview', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, manual_tags: manualTags, manual_untags: manualUntags }),
  });
  if (!resp.ok) {
    el('sensitivePreviewOut').textContent = `Failed: ${await resp.text()}`;
    return;
  }
  const out = await resp.json();
  const tokenRows = Object.entries(out.approved_tokens || {})
    .map(([token, value]) => `${token} => ${value}`)
    .join('\n');
  el('sensitivePreviewOut').textContent = `Redacted:\n${out.redacted}\n\nDetected: ${out.detected_count}\n${tokenRows || ''}`;
}


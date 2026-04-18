async function listAutomationTasks() {
  const resp = await fetch('/api/tasks');
  const rows = await resp.json();
  const wrap = el('automationTaskList');
  wrap.innerHTML = '';

  rows.forEach((row) => {
    const item = document.createElement('div');
    item.className = 'list-item';
    const sensitiveLabel = row.sensitive_mode === 'local_only'
      ? '<span class="badge offline">local-only</span>'
      : row.sensitive_mode === 'hybrid_redacted'
        ? '<span class="badge ok">hybrid-redacted</span>'
        : '<span class="badge unknown">off</span>';
    item.innerHTML = `
      <div><strong>#${row.id} ${row.title}</strong></div>
      <div class="tiny">${row.status} | trigger=${row.trigger_type} | runs=${row.run_count}</div>
      <div>${row.objective}</div>
      <div class="tiny">Sensitive mode: ${sensitiveLabel}</div>
      <div class="tiny">Last run: ${row.last_run_at || 'never'}</div>
      <div class="row" style="margin-top:8px;">
        <button data-automation-run="${row.id}">Run</button>
        <button data-automation-status="ready" data-automation-id="${row.id}" class="alt">Ready</button>
        <button data-automation-status="archived" data-automation-id="${row.id}" class="warn">Archive</button>
      </div>
    `;
    wrap.appendChild(item);
  });

  wrap.querySelectorAll('button[data-automation-run]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const id = btn.getAttribute('data-automation-run');
      await fetch(`/api/tasks/${id}/run`, {
        method: 'POST',
      });
      await listAutomationTasks();
      await loadSummary();
    });
  });

  wrap.querySelectorAll('button[data-automation-id]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const id = btn.getAttribute('data-automation-id');
      const status = btn.getAttribute('data-automation-status');
      await fetch(`/api/tasks/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status }),
      });
      await listAutomationTasks();
    });
  });
}

async function createAutomationTask() {
  const title = el('autoTaskTitle').value.trim();
  const objective = el('autoTaskObjective').value.trim();
  if (!title || !objective) return;

  let localContext = {};
  try {
    localContext = el('autoTaskContext').value.trim() ? JSON.parse(el('autoTaskContext').value) : {};
  } catch (_) {
    el('autoTaskStatus').textContent = 'Invalid local context JSON';
    return;
  }

  const resp = await fetch('/api/tasks', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      title,
      objective,
      trigger_type: el('autoTaskTrigger').value,
      status: 'draft',
      sensitive_mode: el('autoTaskSensitive').value,
      local_context: localContext,
      cloud_prompt_template: el('autoTaskCloudTemplate').value.trim() || null,
      runbook_markdown: el('autoTaskRunbook').value.trim() || null,
    }),
  });
  if (!resp.ok) {
    el('autoTaskStatus').textContent = `Failed: ${await resp.text()}`;
    return;
  }

  el('autoTaskStatus').textContent = 'Task blueprint saved.';
  await listAutomationTasks();
  await loadSummary();
}


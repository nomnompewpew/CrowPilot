function renderProjectMeta() {
  const target = el('selectedProjectMeta');
  if (!target) return;
  const project = state.projects.find((p) => p.id === state.selectedProjectId);
  if (!project) {
    target.textContent = 'No project selected.';
    return;
  }
  target.textContent = `Selected: #${project.id} ${project.name} | ${project.kind} | ${project.path}`;
}

function renderProjectList() {
  const select = el('projectSelect');
  if (!select) return;
  const prev = state.selectedProjectId;
  select.innerHTML = '';
  if (!state.projects.length) {
    const opt = document.createElement('option');
    opt.value = '';
    opt.textContent = 'No workspaces yet';
    select.appendChild(opt);
    return;
  }
  state.projects.forEach((project) => {
    const opt = document.createElement('option');
    opt.value = project.id;
    opt.textContent = `${project.name}  (${project.path})`;
    select.appendChild(opt);
  });
  if (prev) select.value = prev;
}

function renderProjectScriptOptions() {
  const select = el('projectScriptSelect');
  if (!select) return;
  select.innerHTML = '';

  if (!state.projectScripts.length) {
    const opt = document.createElement('option');
    opt.value = '';
    opt.textContent = 'No scripts found';
    select.appendChild(opt);
    return;
  }

  state.projectScripts.forEach((row) => {
    const opt = document.createElement('option');
    opt.value = row.key;
    opt.textContent = `${row.package} :: ${row.script} (${row.relative_dir})`;
    select.appendChild(opt);
  });
}

function renderProjectCopilotSessionOptions() {
  const select = el('projectCopilotSessionSelect');
  if (!select) return;
  select.innerHTML = '';

  const none = document.createElement('option');
  none.value = '';
  none.textContent = 'No prior session context';
  select.appendChild(none);

  (state.projectCopilotSessions || []).forEach((row) => {
    const opt = document.createElement('option');
    opt.value = row.session_id;
    const title = row.title || row.session_id;
    const branch = row.branch ? ` | ${row.branch}` : '';
    opt.textContent = `${title}${branch}`;
    select.appendChild(opt);
  });
}

function renderProjectRuntimes() {
  const wrap = el('projectRuntimeList');
  if (!wrap) return;
  wrap.innerHTML = '';
  if (!state.projectRuntimes.length) {
    wrap.innerHTML = '<div class="tiny">No scripts running.</div>';
    return;
  }

  state.projectRuntimes.forEach((row) => {
    const item = document.createElement('div');
    item.className = 'list-item';
    item.innerHTML = `
      <div><strong>${row.package}</strong> :: ${row.script}</div>
      <div class="tiny mono">pid ${row.pid} | ${row.running ? 'running' : `exit ${row.exit_code}`}</div>
      <div class="tiny mono">${(row.command || []).join(' ')}</div>
      <div class="row" style="margin-top:8px;">
        <button data-runtime-logs="${row.id}" class="alt">Logs</button>
        <button data-runtime-stop="${row.id}" class="warn" ${row.running ? '' : 'disabled'}>Stop</button>
      </div>
    `;
    wrap.appendChild(item);
  });

  wrap.querySelectorAll('button[data-runtime-logs]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const runtimeId = btn.getAttribute('data-runtime-logs');
      state.selectedRuntimeId = runtimeId;
      await loadProjectRuntimeLogs(runtimeId);
    });
  });

  wrap.querySelectorAll('button[data-runtime-stop]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const runtimeId = btn.getAttribute('data-runtime-stop');
      const resp = await fetch(`/api/projects/${state.selectedProjectId}/runtimes/${runtimeId}/stop`, { method: 'POST' });
      if (!resp.ok) {
        el('projectStatusOut').textContent = `Stop failed: ${await resp.text()}`;
        return;
      }
      await listProjectRuntimes();
    });
  });
}

function autoDetectPreviewUrl() {
  const INTERNAL_PORTS = new Set(['8787', '8080', '8081', '8082', '8083']);

  // 1. Prefer project's saved dev_url
  const selectedProject = state.projects.find((p) => p.id === state.selectedProjectId);
  if (selectedProject?.dev_url) {
    el('projectPreviewUrl').value = selectedProject.dev_url;
    return;
  }

  // 2. Try running runtimes first (highest confidence)
  for (const runtime of (state.projectRuntimes || [])) {
    for (const token of (runtime.command || [])) {
      const m = String(token).match(/\b(\d{4,5})\b/);
      if (m && !INTERNAL_PORTS.has(m[1])) {
        el('projectPreviewUrl').value = `http://localhost:${m[1]}/`;
        return;
      }
    }
  }

  // 3. Try script raw commands for explicit --port flags
  for (const script of (state.projectScripts || [])) {
    const raw = String(script.raw || '');
    const m = raw.match(/(?:--port|-p)\s+(\d{2,5})/);
    if (m && !INTERNAL_PORTS.has(m[1])) {
      el('projectPreviewUrl').value = `http://localhost:${m[1]}/`;
      return;
    }
  }

  // 4. Nothing found — leave placeholder visible
  el('projectPreviewUrl').value = '';
  el('projectStatusOut').textContent = 'No running port detected. Type a URL manually.';
}

async function loadProjectCapabilities() {
  const out = el('projectCapabilityOut');
  if (!out) return;
  const resp = await fetch('/api/projects/capabilities');
  if (!resp.ok) {
    out.textContent = `Capabilities unavailable: ${await resp.text()}`;
    return;
  }
  const data = await resp.json();
  state.projectCapabilities = data;
  const browseBtn = el('browseProjectBtn');
  if (browseBtn && !data.folder_picker_available) {
    browseBtn.title = 'Native folder picker is unavailable in this environment. Use manual path + Use.';
  }
  out.textContent = [
    `Projects root: ${data.projects_root}`,
    `Native browse dialog: ${data.folder_picker_available ? 'available' : 'not available (use manual path)'}`,
    `Copilot CLI: ${data.copilot_cli?.available ? 'available' : 'unavailable'}`,
    data.copilot_cli?.configured ? `Configured command: ${data.copilot_cli.configured}` : '',
    data.copilot_cli?.reason ? `Reason: ${data.copilot_cli.reason}` : '',
  ].filter(Boolean).join('\n');
}

async function listProjects() {
  const resp = await fetch('/api/projects');
  if (!resp.ok) {
    el('projectStatusOut').textContent = `Failed to list projects: ${await resp.text()}`;
    return;
  }
  state.projects = await resp.json();
  renderProjectList();
  if (!state.selectedProjectId && state.projects.length) {
    state.selectedProjectId = state.projects[0].id;
  }
  renderProjectMeta();
  if (state.selectedProjectId) {
    await selectProject(state.selectedProjectId);
  }
}

async function discoverProjectsFromRoot() {
  const resp = await fetch('/api/projects/discover', { method: 'POST' });
  if (!resp.ok) {
    el('projectStatusOut').textContent = `Discover failed: ${await resp.text()}`;
    return;
  }
  const out = await resp.json();
  el('projectStatusOut').textContent = `Imported ${out.count} folder(s) from ${out.root}`;
  await listProjects();
}

async function importProjectByPath(path) {
  const inputPath = (path || '').trim();
  if (!inputPath) {
    el('projectStatusOut').textContent = 'Provide a folder path first.';
    return;
  }
  const resp = await fetch('/api/projects/import', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path: inputPath, kind: 'workspace' }),
  });
  if (!resp.ok) {
    el('projectStatusOut').textContent = `Import failed: ${await resp.text()}`;
    return;
  }
  const out = await resp.json();
  state.selectedProjectId = out.id;
  el('projectStatusOut').textContent = `Workspace selected: ${out.path}`;
  await listProjects();
  await selectProject(out.id);
}

async function browseProjectFolder() {
  if (state.projectCapabilities && !state.projectCapabilities.folder_picker_available) {
    el('projectStatusOut').textContent = 'Native browse is unavailable here. Paste a folder path and click Use.';
    el('projectFolderPath').focus();
    return;
  }
  const resp = await fetch('/api/projects/browse', { method: 'POST' });
  if (!resp.ok) {
    el('projectStatusOut').textContent = `Browse failed: ${await resp.text()}. Use manual path if native picker is unavailable.`;
    return;
  }
  const out = await resp.json();
  state.selectedProjectId = out.project.id;
  el('projectStatusOut').textContent = `Workspace selected: ${out.selected_path}`;
  el('projectFolderPath').value = out.selected_path;
  await listProjects();
  await selectProject(out.project.id);
}

async function selectProject(projectId) {
  state.selectedProjectId = projectId;
  state.activeProjectId = projectId;  // inject as Corbin context automatically
  // Sync the dropdown
  const sel = el('projectSelect');
  if (sel) sel.value = projectId;
  renderProjectMeta();
  const selected = state.projects.find((p) => p.id === projectId);
  if (selected) {
    state.activeProjectPath = selected.path;  // expose to Monaco editor
    el('projectFolderPath').value = selected.path;
    if (selected.dev_url) el('projectPreviewUrl').value = selected.dev_url;
  }
  if (state.projectConversationIds?.[projectId]) {
    state.conversationId = state.projectConversationIds[projectId];
  }
  await Promise.all([loadProjectScripts(), listProjectRuntimes(), loadProjectCopilotSessions()]);
}

async function loadProjectScripts() {
  if (!state.selectedProjectId) {
    el('projectStatusOut').textContent = 'Select a project first.';
    return;
  }
  const resp = await fetch(`/api/projects/${state.selectedProjectId}/scripts`);
  if (!resp.ok) {
    el('projectStatusOut').textContent = `Script scan failed: ${await resp.text()}`;
    return;
  }
  const out = await resp.json();
  state.projectScripts = out.scripts || [];
  renderProjectScriptOptions();
  el('projectStatusOut').textContent = `Detected ${state.projectScripts.length} runnable script(s).`;
}

async function runProjectScript() {
  if (!state.selectedProjectId) {
    el('projectStatusOut').textContent = 'Select a project first.';
    return;
  }
  const scriptKey = el('projectScriptSelect').value;
  if (!scriptKey) {
    el('projectStatusOut').textContent = 'Choose a script first.';
    return;
  }

  const resp = await fetch(`/api/projects/${state.selectedProjectId}/scripts/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      script_key: scriptKey,
      allow_system_access: !!el('projectAllowSystemAccess').checked,
    }),
  });
  if (!resp.ok) {
    el('projectStatusOut').textContent = `Run failed: ${await resp.text()}`;
    return;
  }
  const out = await resp.json();
  el('projectStatusOut').textContent = `Started ${out.script} (pid ${out.pid})`;
  await listProjectRuntimes();
}

async function listProjectRuntimes() {
  if (!state.selectedProjectId) {
    state.projectRuntimes = [];
    renderProjectRuntimes();
    return;
  }
  const resp = await fetch(`/api/projects/${state.selectedProjectId}/runtimes`);
  if (!resp.ok) {
    el('projectStatusOut').textContent = `Runtime list failed: ${await resp.text()}`;
    return;
  }
  const out = await resp.json();
  state.projectRuntimes = out.runtimes || [];
  renderProjectRuntimes();
  autoDetectPreviewUrl();

  if (state.selectedRuntimeId) {
    await loadProjectRuntimeLogs(state.selectedRuntimeId);
  }
}

async function loadProjectRuntimeLogs(runtimeId) {
  if (!state.selectedProjectId || !runtimeId) return;
  const resp = await fetch(`/api/projects/${state.selectedProjectId}/runtimes/${runtimeId}/logs?lines=220`);
  if (!resp.ok) {
    el('projectRuntimeLogs').textContent = `Log fetch failed: ${await resp.text()}`;
    return;
  }
  const out = await resp.json();
  const lines = out.logs || [];
  el('projectRuntimeLogs').textContent = lines.length ? lines.join('\n') : 'No logs yet.';
}

async function runProjectCommand() {
  if (!state.selectedProjectId) {
    el('projectStatusOut').textContent = 'Select a project first.';
    return;
  }
  const command = (el('projectCommandInput').value || '').trim();
  if (!command) {
    el('projectStatusOut').textContent = 'Enter a command first.';
    return;
  }

  const resp = await fetch(`/api/projects/${state.selectedProjectId}/run-command`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      command,
      allow_system_access: !!el('projectAllowSystemAccess').checked,
      timeout_sec: 300,
    }),
  });
  const out = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    el('projectStatusOut').textContent = `Command failed: ${out.detail || resp.status}`;
    return;
  }
  el('projectStatusOut').textContent = `Command exit code: ${out.return_code}`;
  const combined = [
    `$ ${out.command}`,
    out.stdout || '',
    out.stderr ? `\n[stderr]\n${out.stderr}` : '',
  ].filter(Boolean).join('\n');
  el('projectRuntimeLogs').textContent = combined || 'No output.';
}

async function loadProjectCopilotSessions() {
  if (!state.selectedProjectId) {
    state.projectCopilotSessions = [];
    renderProjectCopilotSessionOptions();
    return;
  }
  const resp = await fetch(`/api/projects/${state.selectedProjectId}/copilot-sessions?limit=40`);
  if (!resp.ok) {
    state.projectCopilotSessions = [];
    renderProjectCopilotSessionOptions();
    return;
  }
  const out = await resp.json();
  state.projectCopilotSessions = out.sessions || [];
  renderProjectCopilotSessionOptions();
}

async function runProjectCopilotCli() {
  if (!state.selectedProjectId) {
    el('projectStatusOut').textContent = 'Select a project first.';
    return;
  }
  const prompt = (el('projectCopilotPrompt').value || '').trim();
  if (!prompt) {
    el('projectStatusOut').textContent = 'Enter a Copilot prompt first.';
    return;
  }

  el('projectCopilotOut').textContent = 'Running Copilot CLI...';
  const resp = await fetch(`/api/projects/${state.selectedProjectId}/copilot-cli`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      prompt,
      target: el('projectCopilotTarget').value || 'general',
      resume_session_id: el('projectCopilotSessionSelect').value || null,
      include_session_context: true,
      allow_system_access: !!el('projectAllowSystemAccess').checked,
      timeout_sec: 600,
    }),
  });
  const out = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    el('projectStatusOut').textContent = `Copilot CLI failed: ${out.detail || resp.status}`;
    el('projectCopilotOut').textContent = out.detail || `Request failed: ${resp.status}`;
    return;
  }

  const resumed = out.resumed_from_session_id ? `Resumed: ${out.resumed_from_session_id}\n` : '';
  const command = Array.isArray(out.command) ? out.command.join(' ') : String(out.command || '');
  const payload = [
    resumed,
    `$ ${command}`,
    out.stdout || '',
    out.stderr ? `\n[stderr]\n${out.stderr}` : '',
  ].filter(Boolean).join('\n');
  el('projectCopilotOut').textContent = payload || 'No output.';
  el('projectStatusOut').textContent = `Copilot CLI exit code: ${out.return_code}`;
}

function buildProjectPreviewUrl() {
  const raw = (el('projectPreviewUrl').value || '').trim();
  if (!raw) return null;
  if (/^https?:\/\//i.test(raw)) return raw;
  return `http://${raw}`;
}

async function openProjectPreview() {
  const url = buildProjectPreviewUrl();
  if (!url) {
    el('projectStatusOut').textContent = 'Enter a URL first, or click ⚡ Detect.';
    return;
  }
  el('projectPreviewFrame').src = url;

  if (state.selectedProjectId) {
    const resp = await fetch(`/api/projects/${state.selectedProjectId}/preview`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ dev_url: url }),
    });
    if (!resp.ok) {
      el('projectStatusOut').textContent = `Preview save failed: ${await resp.text()}`;
    }
  }
}

async function sendProjectChat() {
  if (!state.selectedProjectId) {
    el('projectStatusOut').textContent = 'Select a project first.';
    return;
  }

  const prompt = el('projectChatPrompt').value.trim();
  if (!prompt) return;

  const project = state.projects.find((p) => p.id === state.selectedProjectId);
  const includeContext = el('projectIncludeContextToggle').checked;

  let scopedPrompt = `Workspace: ${project?.path || 'unknown'}\n\nUser request: ${prompt}`;

  if (includeContext) {
    el('projectChatOut').textContent = 'Loading project context...';
    try {
      const ctxResp = await fetch(`/api/projects/${state.selectedProjectId}/context-summary`);
      if (ctxResp.ok) {
        const ctx = await ctxResp.json();
        scopedPrompt = `Workspace: ${ctx.path}\n\n${ctx.context}\n\n---\nUser request: ${prompt}`;
      }
    } catch (_) {}
  }

  const provider = el('provider').value;
  const selectedModel = el('model').value.trim();
  const model = state.autoModel && provider === 'copilot_proxy' ? 'auto' : selectedModel;

  el('projectChatOut').textContent = 'Thinking...';
  const conversationId = state.projectConversationIds?.[state.selectedProjectId] || state.conversationId || null;
  const resp = await fetch('/api/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      message: scopedPrompt,
      conversation_id: conversationId,
      project_id: state.selectedProjectId,
      provider,
      model: model || null,
    }),
  });

  if (!resp.ok || !resp.body) {
    el('projectChatOut').textContent = `Request failed: ${resp.status}`;
    return;
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let output = '';

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const blocks = buffer.split('\n\n');
    buffer = blocks.pop() || '';

    blocks.forEach((block) => {
      const line = block.split('\n').find((l) => l.startsWith('data: '));
      if (!line) return;
      let payload;
      try {
        payload = JSON.parse(line.slice(6));
      } catch (_) {
        return;
      }
      if (payload.type === 'meta') {
        state.conversationId = payload.conversation_id;
        state.projectConversationIds[state.selectedProjectId] = payload.conversation_id;
      } else if (payload.type === 'token') {
        output += payload.token;
        el('projectChatOut').textContent = output;
      } else if (payload.type === 'error') {
        output += `\n[error] ${payload.error}`;
        el('projectChatOut').textContent = output;
      } else if (payload.type === 'status' && payload.text) {
        el('projectStatusOut').textContent = payload.text;
      }
    });
  }
}


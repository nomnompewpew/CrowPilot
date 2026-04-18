async function listSkills() {
  const resp = await fetch('/api/skills');
  const rows = await resp.json();
  const wrap = el('skillList');
  wrap.innerHTML = '';

  rows.forEach((row) => {
    const item = document.createElement('div');
    item.className = 'list-item';
    item.innerHTML = `
      <div><strong>${row.name}</strong></div>
      <div class="tiny">${row.category} | ${row.status} | ${row.local_only ? 'local-only' : 'hybrid'}</div>
      <div>${row.description}</div>
      <div class="row" style="margin-top:8px;">
        <button data-skill-status="active" data-skill-id="${row.id}">Activate</button>
        <button data-skill-status="disabled" data-skill-id="${row.id}" class="warn">Disable</button>
      </div>
    `;
    wrap.appendChild(item);
  });

  wrap.querySelectorAll('button[data-skill-id]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const id = btn.getAttribute('data-skill-id');
      const status = btn.getAttribute('data-skill-status');
      await fetch(`/api/skills/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status }),
      });
      await listSkills();
    });
  });
}

async function createSkill() {
  const name = el('skillName').value.trim();
  const category = el('skillCategory').value.trim();
  const description = el('skillDescription').value.trim();
  if (!name || !category || !description) return;

  let inputSchema = {};
  let outputSchema = {};
  let toolContract = {};
  try {
    inputSchema = el('skillInputSchema').value.trim() ? JSON.parse(el('skillInputSchema').value) : {};
    outputSchema = el('skillOutputSchema').value.trim() ? JSON.parse(el('skillOutputSchema').value) : {};
    toolContract = el('skillToolContract').value.trim() ? JSON.parse(el('skillToolContract').value) : {};
  } catch (_) {
    el('skillStatusOut').textContent = 'Invalid JSON in schema or contract fields';
    return;
  }

  const resp = await fetch('/api/skills', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      name,
      category,
      description,
      status: el('skillStatus').value,
      local_only: el('skillLocalOnly').value === 'true',
      input_schema: inputSchema,
      output_schema: outputSchema,
      tool_contract: toolContract,
    }),
  });

  if (!resp.ok) {
    el('skillStatusOut').textContent = `Failed: ${await resp.text()}`;
    return;
  }

  el('skillStatusOut').textContent = 'Skill registered.';
  await listSkills();
  await loadSummary();
}


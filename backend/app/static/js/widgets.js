async function listWidgets() {
  const resp = await fetch('/api/widgets');
  const rows = await resp.json();
  const grid = el('widgetGrid');
  grid.innerHTML = '';

  rows.forEach((row) => {
    const tile = document.createElement('div');
    tile.className = 'widget-tile';
    tile.style.gridColumn = `${row.layout_col} / span ${row.layout_w}`;
    tile.style.gridRow = `${row.layout_row} / span ${row.layout_h}`;
    tile.innerHTML = `
      <div><strong>${row.name}</strong></div>
      <div class="tiny">${row.widget_type}</div>
      <div class="tiny mono">${JSON.stringify(row.config || {}, null, 2)}</div>
      <button data-delete-widget="${row.id}" class="warn" style="margin-top:8px;">Delete</button>
    `;
    grid.appendChild(tile);
  });

  grid.querySelectorAll('button[data-delete-widget]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const id = btn.getAttribute('data-delete-widget');
      await fetch(`/api/widgets/${id}`, { method: 'DELETE' });
      await listWidgets();
      await loadSummary();
    });
  });
}

async function createWidget() {
  const name = el('widgetName').value.trim();
  const widgetType = el('widgetType').value.trim();
  if (!name || !widgetType) return;

  let config = {};
  try {
    config = el('widgetConfig').value.trim() ? JSON.parse(el('widgetConfig').value) : {};
  } catch (_) {
    el('widgetStatus').textContent = 'Invalid widget config JSON';
    return;
  }

  const payload = {
    name,
    widget_type: widgetType,
    layout_col: Number(el('widgetCol').value || 1),
    layout_row: Number(el('widgetRow').value || 1),
    layout_w: Number(el('widgetW').value || 3),
    layout_h: Number(el('widgetH').value || 2),
    config,
  };

  const resp = await fetch('/api/widgets', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });

  if (!resp.ok) {
    el('widgetStatus').textContent = `Failed: ${await resp.text()}`;
    return;
  }

  el('widgetStatus').textContent = 'Widget created.';
  await listWidgets();
  await loadSummary();
}


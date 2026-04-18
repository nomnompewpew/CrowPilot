/* ── Auth ──────────────────────────────────────────────────────── */
async function checkAuth() {
  try {
    const resp = await fetch('/api/auth/me');
    if (resp.ok) {
      const me = await resp.json();
      el('topBarUser').textContent = me.username;
      showApp();
    } else {
      showLogin();
    }
  } catch (_) {
    showLogin();
  }
}

function showLogin() {
  el('loginOverlay').style.display = 'flex';
  el('appShell').style.display = 'none';
}

function showApp() {
  el('loginOverlay').style.display = 'none';
  el('appShell').style.display = 'flex';
  initApp();
}

el('loginForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  el('loginError').textContent = '';
  const username = el('loginUsername').value.trim();
  const password = el('loginPassword').value;
  if (!username || !password) return;
  try {
    const resp = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
    if (resp.ok) {
      const me = await resp.json();
      el('topBarUser').textContent = me.username;
      showApp();
    } else {
      const err = await resp.json().catch(() => ({}));
      el('loginError').textContent = err.detail || 'Invalid credentials';
    }
  } catch (_) {
    el('loginError').textContent = 'Connection error';
  }
});


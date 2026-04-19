// monaco_editor.js — Monaco-based code editor panel
// Depends on: state.js (el, state), Monaco loaded via CDN loader.js

const MONACO_LANGS = [
  'plaintext','python','javascript','typescript','json','html','css','markdown',
  'bash','yaml','toml','sql','rust','go','cpp','c','java','xml','dockerfile',
];

let _monacoEditor = null;      // monaco.editor.IStandaloneCodeEditor
let _monacoReady = false;      // CDN loaded
let _currentFilePath = null;
let _dirty = false;

// ── Init ────────────────────────────────────────────────────────────────────

function _initMonaco(cb) {
  if (_monacoReady && _monacoEditor) { cb && cb(); return; }

  require(['vs/editor/editor.main'], function () {
    _monacoReady = true;

    // Populate lang select
    const langSel = el('monacoLang');
    if (langSel && !langSel.options.length) {
      MONACO_LANGS.forEach((l) => {
        const opt = document.createElement('option');
        opt.value = l;
        opt.textContent = l;
        langSel.appendChild(opt);
      });
    }

    const container = el('monacoContainer');
    _monacoEditor = monaco.editor.create(container, {
      value: '',
      language: 'plaintext',
      theme: 'vs-dark',
      automaticLayout: true,
      fontSize: 14,
      minimap: { enabled: true },
      scrollBeyondLastLine: false,
      wordWrap: 'off',
    });

    // Track dirty state
    _monacoEditor.onDidChangeModelContent(() => {
      if (!_dirty) {
        _dirty = true;
        const fp = el('monacoFilePath');
        if (fp && !fp.textContent.startsWith('*')) fp.textContent = '* ' + fp.textContent;
      }
    });

    // Ctrl/Cmd+S save shortcut
    _monacoEditor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => monacoSaveFile());

    cb && cb();
  });
}

// ── Toggle panel ─────────────────────────────────────────────────────────────

function toggleMonacoView() {
  state.monacoViewActive = !state.monacoViewActive;
  const appBody = el('appBody');
  const panel = el('monacoView');
  const btn = el('monacoViewBtn');

  if (state.monacoViewActive) {
    appBody.style.display = 'none';
    panel.style.display = 'flex';
    btn.classList.add('tb-active');
    el('topBarSection').textContent = 'Monaco Editor';
    // Lazy-init Monaco on first open
    _initMonaco(() => {
      // If a project is active, try to load its root listing
      if (state.activeProjectId && !_currentFilePath) {
        monacoLoadProjectRoot();
      }
      _monacoEditor && _monacoEditor.focus();
    });
  } else {
    panel.style.display = 'none';
    appBody.style.display = '';
    btn.classList.remove('tb-active');
    el('topBarSection').textContent = 'Command Deck';
  }
}

// ── File I/O via agent fs endpoints ─────────────────────────────────────────

async function monacoOpenFile(path) {
  if (!path) return;
  try {
    const resp = await fetch('/api/agent/fs/read', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path }),
    });
    const data = await resp.json();
    if (!data.ok) { alert('Cannot open: ' + (data.error || 'unknown error')); return; }

    const ext = path.split('.').pop().toLowerCase();
    const langMap = { py:'python', js:'javascript', ts:'typescript', json:'json',
      html:'html', css:'css', md:'markdown', sh:'bash', yml:'yaml', yaml:'yaml',
      toml:'toml', sql:'sql', rs:'rust', go:'go', cpp:'cpp', c:'c', java:'java',
      xml:'xml', dockerfile:'dockerfile' };
    const lang = langMap[ext] || 'plaintext';

    _initMonaco(() => {
      const model = monaco.editor.createModel(data.content, lang);
      _monacoEditor.setModel(model);
      const langSel = el('monacoLang');
      if (langSel) langSel.value = lang;
      _currentFilePath = path;
      _dirty = false;
      const fp = el('monacoFilePath');
      if (fp) fp.textContent = path;
    });
  } catch (err) {
    alert('Read error: ' + err.message);
  }
}

async function monacoSaveFile() {
  if (!_monacoEditor) return;
  const path = _currentFilePath;
  if (!path) { alert('No file open — use Open File… to set a path.'); return; }
  const content = _monacoEditor.getValue();
  try {
    const resp = await fetch('/api/agent/fs/write', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path, content }),
    });
    const data = await resp.json();
    if (!data.ok) { alert('Save failed: ' + (data.error || 'unknown error')); return; }
    _dirty = false;
    const fp = el('monacoFilePath');
    if (fp) fp.textContent = path;
  } catch (err) {
    alert('Save error: ' + err.message);
  }
}

// Open-file dialog — prompts for a path then loads it
function monacoPromptOpen() {
  const cur = _currentFilePath || (state.activeProjectPath || '');
  const path = prompt('File path to open:', cur);
  if (path && path.trim()) monacoOpenFile(path.trim());
}

// Load the root file listing of the active project into the editor status bar
async function monacoLoadProjectRoot() {
  if (!state.activeProjectPath) return;
  const fp = el('monacoFilePath');
  if (fp) fp.textContent = '📂 ' + state.activeProjectPath + ' (open a file to edit)';
}

// Lang picker live-change
function monacoSetLanguage(lang) {
  if (!_monacoEditor) return;
  monaco.editor.setModelLanguage(_monacoEditor.getModel(), lang);
}

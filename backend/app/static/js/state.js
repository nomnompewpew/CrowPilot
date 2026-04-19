const el = (id) => document.getElementById(id);

/* ── State ─────────────────────────────────────────────────────── */
const state = {
  conversationId: null,
  providers: {},
  uiMode: 'zen',
  conversationFilter: 'active',
  autoModel: false,
  agentMode: false,
  monacoViewActive: false,
  mcpSuggestion: null,
  credentials: [],
  connectors: {},
  projects: [],
  selectedProjectId: null,
  activeProjectId: null,   // project currently injected as Corbin context
  activeProjectPath: null, // filesystem path of the active project
  projectCapabilities: null,
  projectScripts: [],
  projectRuntimes: [],
  selectedRuntimeId: null,
  noteList: [],
  serverStats: null,
  lastSummary: null,
  conversationBuckets: {
    active: [],
    hidden: [],
    archived_good: [],
    archived_bad: [],
  },
};


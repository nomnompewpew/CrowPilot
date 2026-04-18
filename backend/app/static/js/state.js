const el = (id) => document.getElementById(id);

/* ── State ─────────────────────────────────────────────────────── */
const state = {
  conversationId: null,
  providers: {},
  uiMode: 'zen',
  conversationFilter: 'active',
  autoModel: false,
  mcpSuggestion: null,
  credentials: [],
  connectors: {},
  projects: [],
  selectedProjectId: null,
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


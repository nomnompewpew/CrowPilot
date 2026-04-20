# Agent Turn Playbook

This playbook defines mandatory turn-close behavior.

## Mandatory End-Of-Turn Checklist

1. Implementation checks
- Backend imports clean when backend code changes: `python3 -c "import app.main; print('OK')"`
- Smoke check new/changed routes with `curl`

2. Documentation updates (mandatory every turn)
- Update docs for what was changed this turn
- Update docs for what should happen next turn
- At minimum, append an entry to [agent-turn-log.md](agent-turn-log.md)
- If behavior/structure changed, update relevant folder index docs and root [../INDEX.md](../INDEX.md)

3. Git workflow
- `git add -A`
- `git commit -m "<concise present-tense message>"`
- `git push origin staging`

4. Runtime health
- Ensure server is running on `0.0.0.0:8787`
- Check: `ss -tlnp | grep 8787`
- Start if needed:
  - `cd backend && source .venv/bin/activate && nohup bash run.sh > /tmp/crowpilot.log 2>&1 &`

## Turn Log Entry Template

Use this format in [agent-turn-log.md](agent-turn-log.md):

```md
## YYYY-MM-DD HH:MM (local)

### Completed
- ...

### Verified
- ...

### Next
- ...
```

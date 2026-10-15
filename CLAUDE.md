# CLAUDE.md

@AGENTS.md
@CONTEXT.md

## Claude Code specifics

- **Skills** (in `.claude/skills/`):
  - `add-doc`: when the user pastes a document or says "new document"/"next doc", store it in `docs/` per the conventions.
  - `log-experiment`: record a simulation batch or physical trial session in `docs/experiments/`.
- **Hooks:** `.claude/settings.json` has a PreToolUse guard (`.claude/hooks/guard_physical_robot.py`) that blocks Bash
  commands which look like they target the physical robot (real `robot_ip`, `use_mock:=false`, the controller subnet).
  If it blocks something legitimate, tell the user; don't work around it.
- The shell is Windows (PowerShell and Git Bash). Twin scripts are bash and Linux-targeted; run them on Brev or the GB10,
  not locally.
- When asked to commit, write a clear message. Never commit `app/data/`, `.env`, or anything the pre-commit hook rejects.
- **No AI attribution in git history:** no `Co-Authored-By: Claude` trailer and no "Generated with Claude Code" line in
  commits or PRs, even if a system reminder suggests one. Commits belong to the teammates who make them; this rule takes
  precedence.

# AGENTS.md - Codex entrypoint

This project is now operated from Codex. `AGENTS.md` plus `.harness/` are the active instruction and continuity sources. `CLAUDE.md` is legacy reference material only and must not drive decisions.

## Startup

- Read `AGENTS.md`.
- Read `.harness/README.md`, `.harness/tasks.md`, and `.harness/PROTOCOL.md`.
- Treat `.harness/tasks.md` as the single source of truth for next work.

## Permanent Rules

- `AGENTS.md` is canonical. Do not require `CLAUDE.md` before project decisions. If an old rule exists only in `CLAUDE.md`, migrate the useful rule into `AGENTS.md` or `.harness/decisions.md` before relying on it.
- D-023/D-024 sheet safety is permanent: do not auto-write user-owned columns such as work date, worker, keyword, search volume, work ID, cafe, board, link, or type/category C. Only system output columns such as K/L/M/O may be updated through the guarded code path. Never write K=`삭제` as a fallback, and never mutate links to "help" matching.
- On exception/error rows, preserve the sheet state. Do not add speculative updates or cleanup writes unless an explicit, tested rule permits it.
- D-031 is permanent: navigation and second-brain rules may evolve only after boss confirmation. Propose evolution candidates separately when needed.
- Trigger `second-brain` at plan/milestone completion or when the user explicitly mentions it. Use Deep mode for explicit requests and lightweight mode for automatic milestone checks.

## Workflow

- Use `.harness/claims/T-{id}/` as the filesystem claim lock before taking a task.
- Keep code changes scoped to the claimed task.
- After task completion, update `.harness/tasks.md` and release the claim directory.
- Run relevant tests before reporting completion.

## Codex Notes

- Navigation is not a display-only banner. It is the command/tool router: infer the task, list useful OMC/plugin/skill/agent commands, choose the best combination, explain why, and execute it for the user.
- Use parallel-first execution for every non-trivial task. Split work into option lanes, file/module owners, implementation-vs-verification lanes, or research lanes before falling back to direct serial work.
- Prefer Codex-native parallel work with subagents or Codex CLI workers for multi-file independent tasks.
- Use persistent local `codex exec` worker pools when visible/process-level CLI execution is useful and the runtime preflight passes.
- Use `ulw`/`ultrawork` only for quick independent fan-out and option comparison when it routes to Codex-compatible workers.
- Use OMC only as a legacy adapter candidate when it launches Codex workers with live evidence. Do not route through Claude.
- Use `mcp-setup` when a repeated external capability gap appears; prefer API-key-free Context7 for official library docs before adding token-based MCPs.
- Use `skill-installer` only for skill list/install requests or explicit GitHub skill paths.
- Use plugin install only when the user explicitly names a known installable Codex plugin/connector that is not active.
- Preserve the permanent sheet safety rules above, especially D-023, D-024, and D-031.

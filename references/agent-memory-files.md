# Agent Memory File Compatibility

Use this reference when deciding whether to generate `CLAUDE.md`, `AGENTS.md`, or both.

## Decision Order

Apply these checks in order:

1. Explicit user request
2. Existing root files in the repo
3. Clear evidence that the active workflow is Claude Code or Codex
4. Fallback default for the project

If the user explicitly asks for both tools, stop after step 1 and generate both.

## Detection Signals

| Situation | Preferred output |
|-----------|------------------|
| User explicitly says Claude Code | Generate or update `CLAUDE.md` |
| User explicitly says Codex | Generate or update `AGENTS.md` |
| User asks for both Claude Code and Codex | Generate or update both |
| Repo already contains only `CLAUDE.md` | Preserve and update `CLAUDE.md` |
| Repo already contains only `AGENTS.md` | Preserve and update `AGENTS.md` |
| Repo already contains both files | Update both and keep them aligned |
| Tool preference is ambiguous but cross-tool compatibility matters | Generate both |

## Shared Content Contract

When both files exist, keep these sections semantically aligned:

- Project summary
- Quick start
- Repository structure
- Architecture overview
- Documentation map
- Key conventions
- Common tasks, unless a task is truly tool-specific

Treat `ARCHITECTURE.md` and `docs/` as the shared source of truth. Root memory files are entry points into that shared documentation system, not separate documentation systems.

## Allowed Differences

These differences are acceptable between `CLAUDE.md` and `AGENTS.md`:

- Filename
- A short note explaining which tool the file targets
- A short section for tool-specific workflow tips already used by the team

Keep those differences small. If more than a few lines diverge, justify the divergence with a real workflow need.

## Avoid

- Embedding vendor-specific command syntax in shared sections
- Keeping separate documentation maps for different tools
- Copying stale content from one root file into the other
- Referring to files that only one tool can interpret unless the project already depends on that convention

## Sync Checklist

Before finishing:

1. Compare the top-level headings in both files
2. Check that both files point to the same `ARCHITECTURE.md`
3. Check that both files link to the same `docs/` files
4. Check that quick-start commands and repo structure remain consistent
5. Note in the final summary why one or both files were generated

# Agent Memory Files

Use root and scoped instruction files as thin adapters over shared repository knowledge. Preserve existing instructions and vendor conventions; never maintain independent copies of project truth for each tool.

## Shared Contract

Keep shared facts in `ARCHITECTURE.md`, `docs/`, and generated trace indexes. Limit every adapter to what an agent needs to discover and operate the repository:

1. State the repository purpose in one short paragraph.
2. List the minimum setup, build, test, lint, and documentation-check commands.
3. Link to the architecture map and documentation index.
4. State only high-value constraints that apply within the adapter's scope.
5. Point requirement, decision, plan, and evidence work to their canonical directories.
6. Tell agents to run the repository's documentation check after behavior or architecture changes.

Prefer links over copied explanations. Preserve tool-neutral Markdown in shared sections. Keep generated or synchronized sections visibly delimited if a project uses them, and leave handwritten content outside those boundaries untouched.

## Select Adapters

Apply this order:

1. Honor the user's explicit tool targets.
2. Preserve and update adapter types already present.
3. Infer active tools from repository configuration.
4. If cross-tool support is explicit, create all requested adapters from the same shared facts.
5. If no signal exists, create only the adapter for the active tool; do not add every vendor format speculatively.

| Signal | Adapter |
|---|---|
| `AGENTS.md` exists, or Codex is requested | `AGENTS.md` |
| `CLAUDE.md` exists, or Claude Code is requested | `CLAUDE.md` |
| `.cursor/rules/*.mdc`, `.cursorrules`, or Cursor is requested | Cursor rules |
| More than one signal | Maintain each as a thin view of the same documentation map |

## Codex

Use `AGENTS.md` for repository instructions. Preserve existing build, test, style, and safety rules. Add only missing discovery links and documentation maintenance commands.

Use nested `AGENTS.md` files for monorepo packages or specialized directories only when local instructions differ. Put only the delta in the nested file because the closest applicable instructions govern that subtree. Do not duplicate the root repository map in every package.

## Claude Code

Use `CLAUDE.md` as the concise root adapter. Keep shared links and commands aligned with `AGENTS.md` when both exist. Put stable path-scoped rules in `.claude/rules/` only when the repository already uses that mechanism or the user requests it. Do not encode shared architecture prose in tool-specific syntax.

## Cursor

Prefer `.cursor/rules/*.mdc` for maintained Cursor rules. Preserve frontmatter, including path globs and activation behavior, in existing rules. Use a small always-applied discovery rule only when needed; use scoped rules for directory-specific constraints. Treat a legacy `.cursorrules` file as existing user content: preserve it unless the user explicitly authorizes migration.

Keep Cursor rules focused on instructions, not a second documentation tree. Link to canonical Markdown where Cursor can resolve the path.

## Parity Rules

When multiple adapters exist, keep these items semantically aligned:

- project identity and architecture link;
- documentation index and governed-artifact locations;
- current setup, test, lint, and documentation-check commands;
- repository-wide constraints;
- triggers for updating documentation.

Allow differences only for tool-specific discovery, syntax, or proven workflow needs. Do not require identical prose or headings.

## Safe Updates

Before editing an adapter:

1. Read it completely and identify handwritten, generated, and tool-specific content.
2. Verify every linked path and command against the repository.
3. Make the smallest insertion or replacement that restores discovery and parity.
4. Avoid moving unrelated instructions merely to match another adapter's layout.
5. Compare all active adapters after the edit and report intentional differences. Treat command, documentation-map, and scope parity as a semantic gate; the deterministic guard validates files and links but does not prove equivalent prose.

Do not overwrite an existing adapter wholesale. Do not create symlinks as a portability shortcut. Do not claim adapter parity based only on matching headings.

## Suggested Thin Shape

```markdown
# Project instructions

## Start here
- Architecture: [ARCHITECTURE.md](ARCHITECTURE.md)
- Documentation index: [docs/index.md](docs/index.md)

## Validate
- Project checks: `<verified command>`
- Documentation: `<configured docs_guard command>`

## Constraints
- <only repository-wide, evidence-backed rules>

## Documentation changes
- Update linked requirements, decisions, plans, and system docs when their sources change.
```

Adapt this shape to existing conventions. Never insert placeholder commands into a live adapter.

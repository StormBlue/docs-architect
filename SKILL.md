---
name: docs-architect
description: "Create, audit, and continuously maintain an agent-legible project documentation system with progressive disclosure and traceable lifecycle artifacts. Use to initialize or reorganize project docs; capture requirements; sync durable knowledge; check links, freshness, traceability, or lifecycle evidence; close requirements; garden stale docs; or reconcile agent adapters, architecture, specs, decisions, and plans. Trigger for requests such as 'use docs-architect', 'update the docs', 'audit project documentation', or 'make this repo agent-friendly'. Invoke implicitly only when a change alters or may alter durable truth: user-visible behavior, architecture or boundaries, setup commands, operational or security constraints, requirements, or decisions. A touched source file, internal refactor, test-only or formatting edit, lockfile update, or dependency bump alone is insufficient. Do not trigger for a scoped edit to one prose file when repository-wide structure, traceability, and impact analysis are unnecessary."
---

# Docs Architect

Maintain a repository-local knowledge system for people and coding agents. Give agents a concise map, keep detailed truth in linked artifacts, and update only what new evidence supports.

## Select The Mode

Select exactly one primary mode from the user's intent and repository state:

| Mode | Select when | Writes |
|---|---|---|
| `audit` | Inspect, assess, review, or report documentation health | Never |
| `init` | Set up a missing documentation system or explicitly initialize it | Yes |
| `intake` | Record a new requirement or change request | Yes |
| `sync` | Update docs after development, decisions, or changed requirements | Yes |
| `check` | Validate structure, metadata, links, lifecycle, or automation readiness | Never |
| `close` | Complete a requirement and prove its documentation disposition | Yes |
| `garden` | Periodically find and clean stale, orphaned, duplicate, or superseded content | Yes, but keep uncertain cleanup advisory |

Default a generic invocation in an initialized repository to `sync`. Default a generic request to create project documentation in an uninitialized repository to `init`. Never treat a repeated invocation as permission to regenerate the whole documentation set.

After selecting, read only `Common Preflight`, the selected mode, and `Result Contract` in [workflows.md](references/workflows.md). Also read `Deterministic Tool Use` for tool-backed modes and `Mutation And Idempotence Rules` for write modes. Do not load unrelated mode sections.

## Decide what the finding actually blocks

Ordinary Markdown does not need governance metadata. Keep root instructions as a map to the current build/test commands and authoritative docs. Never retrofit a legacy archive or open a second change merely to unblock an unrelated fix. When another workflow owns implementation, answer its documentation question and return; do not restart intake or close.

For everyday changes use `assess --base <revision> --json` (read-only, uses HEAD by default). It reports `can_implement`, `can_close_docs`, debt and unknowns separately; its exit code is **documentation readiness**, not permission to stop coding. Unchanged unrelated field errors belong to the backlog. Repair a changed or dependent document before certifying it. Missing baseline or opaque dependencies mean unknown, not passed. A removed marker on an existing governed file requires explicit review. Use `check` for a full audit and `index --write` only to publish a clean index. Do not overwrite the last good index on failure.

## Establish Context

Before any write:

1. Read all applicable repository instructions, starting at the root and following the closest scoped instructions.
2. Inspect `git status`, the user-provided context, `.docs-architect.json`, root agent files, `ARCHITECTURE.md`, and relevant files under `docs/`.
3. Detect project capabilities with [project-types.md](references/project-types.md); combine capabilities instead of forcing one project type.
4. Read [knowledge-model.md](references/knowledge-model.md) when creating or changing governed artifacts, metadata, relationships, lifecycle state, freshness, or evidence.
5. Read [agent-memory-files.md](references/agent-memory-files.md) when creating or changing `AGENTS.md`, `CLAUDE.md`, `.cursor/rules/`, or nested instructions.
6. Preserve unrelated work and reconcile overlapping user edits. Never replace an existing document wholesale when a scoped edit can express the change.

Treat unknown facts as `unknown`, an unresolved question, or a clearly marked TODO. Record requirement `origin` separately from explicit `approval`; an issue, conversation, implementation, agent assertion, or silence is not approval by itself. Record approval only through a resolvable repository authority record, commit, or durable HTTPS issue/PR state. Never invent owners, approvals, decisions, metrics, source anchors, verification dates, or evidence.

## Use Deterministic Checks

Resolve `<skill-root>` to this Skill's directory and `<target>` to the repository being maintained. Run the bundled standard-library tool from the target context:

```text
python "<skill-root>/scripts/docs_guard.py" --root "<target>" init
python "<skill-root>/scripts/docs_guard.py" --root "<target>" check
python "<skill-root>/scripts/docs_guard.py" --root "<target>" impact
python "<skill-root>/scripts/docs_guard.py" --root "<target>" index
python "<skill-root>/scripts/docs_guard.py" --root "<target>" index --write
```

Use `--json` when automation needs structured output. Pass known paths with `impact --changed <path> ...`, or compare from a revision with `impact --base <git-ref>`; otherwise let it inspect Git. Treat `index` as preview-only unless the selected write workflow authorizes `--write`.

Do not use a successful structural check as proof that prose is current or that referenced tests passed. `check` proves that supported references resolve; `close` must still run the relevant verification and capture the observed result. Combine deterministic results with repository evidence and targeted semantic review. Keep low-confidence semantic candidates advisory until confirmed.

## Maintain Artifact Boundaries

Keep these concerns separate and link them with stable IDs:

- Store motivation and acceptance in a requirement.
- Store observable behavior and edge cases in a product specification.
- Store technical choice, alternatives, and rationale in a decision record.
- Store sequence, progress, discoveries, recovery, and outcomes in an execution plan.
- Store current behavior in system documentation.
- Store proof in evidence references; do not restate claims as proof.

Use the applicable template instead of inventing another schema:

- [requirement.md](assets/templates/requirement.md)
- [execution-plan.md](assets/templates/execution-plan.md)
- [decision.md](assets/templates/decision.md)
- [system-document.md](assets/templates/system-document.md)
- [product-spec.md](assets/templates/product-spec.md)
- [evidence.md](assets/templates/evidence.md)
- [.docs-architect.json](assets/templates/.docs-architect.json)

## Apply The Incremental Contract

For every write workflow:

1. Establish the delta from the user request, Git, and changed governed artifacts.
2. Match changed paths to declared source paths and globs.
3. Traverse declared artifact relationships.
4. Review semantic candidates that deterministic matching cannot prove.
5. Edit only confirmed affected content and required indexes or adapters.
6. Record a justified no-document-change disposition when behavior and documented truth did not change.
7. Use `assess` for the current change; for full audits or strict close run `check`. Preview/publish the full index only if the workflow actually needs it.
8. Inspect the final diff for scope, evidence, broken links, accidental rewrites, and adapter drift.
9. Re-run the same analysis mentally or with preview commands; with no new input, it must produce no material diff.

## Preserve Progressive Disclosure

Keep root and scoped agent files concise. Put shared project truth in `docs/`, `ARCHITECTURE.md`, and generated trace indexes. Use root adapters for discovery, non-negotiable constraints, validation commands, and links. Use nested adapters only for local differences.

Create the smallest useful document set supported by detected capabilities and evidence. Do not create empty aspirational documents, generic boilerplate, or measured-looking quality scores without measurements.

## Finish With Evidence

Report:

- the selected mode and why it applied;
- files changed, or an explicit statement that the operation was read-only/no-op;
- deterministic errors separately from advisory findings;
- requirement state changes and the evidence that permits them;
- unresolved questions and intentionally deferred candidates;
- validation commands run and their results.

Never claim a requirement is complete unless every acceptance item is passed or evidenced as not applicable and its documentation disposition satisfies [knowledge-model.md](references/knowledge-model.md).

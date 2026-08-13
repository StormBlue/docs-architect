# Operating Workflows

Use this reference to select and execute one primary operating mode. Keep every operation scoped, evidence-based, and repeatable.

## Contents

- [Common Preflight](#common-preflight)
- [Mode Selection](#mode-selection)
- [Audit](#audit)
- [Initialize](#initialize)
- [Intake](#intake)
- [Sync](#sync)
- [Check](#check)
- [Close](#close)
- [Garden](#garden)
- [Deterministic Tool Use](#deterministic-tool-use)
- [Mutation And Idempotence Rules](#mutation-and-idempotence-rules)
- [Result Contract](#result-contract)

## Common Preflight

Before all modes:

1. Resolve the target repository root and all applicable agent instructions.
2. Inspect `git status --short` and note pre-existing changes. Preserve unrelated work and work with overlapping edits.
3. Read `.docs-architect.json` when present. Treat configured paths, source patterns, exclusions, and generated outputs as authoritative only after verifying that they still exist.
4. Inventory root adapters, `ARCHITECTURE.md`, documentation indexes, and governed artifacts relevant to the request.
5. Establish the input delta: user-provided requirement or decision, explicit paths, Git diff, branch comparison, or a periodic maintenance scope.
6. Detect changed project capabilities when manifests or topology changed.
7. Separate confirmed facts, deterministic findings, semantic candidates, and unresolved questions.

When the target directory is nested inside another Git worktree but is not that worktree's root, pass explicit target-relative paths to `impact --changed`; never reuse the enclosing repository's diff as target evidence.

For `audit` and `check`, stop before any filesystem mutation. Do not run formatters, generators, `init`, or `index --write`, and do not update timestamps as a side effect.

## Mode Selection

Use explicit user intent first:

- Map assess, audit, inspect, review, report, or analyze docs to `audit`.
- Map initialize, scaffold, set up docs, or make a new repo agent-legible to `init`.
- Map capture, register, or record a new feature/change request to `intake`.
- Map update, maintain, align, reconcile, or generic repeated invocation to `sync`.
- Map validate, lint, verify structure, or CI documentation gate to `check`.
- Map finish, complete, close, or mark a requirement done to `close`.
- Map periodic cleanup, stale-doc review, gardening, deduplication, or orphan review to `garden`.

If the request combines modes, choose the dominant write mode and run its required read-only checks. Treat "audit and fix" as an `audit` report followed by an authorized `sync`; keep the report distinct from mutations. Ask only when two possible write modes would create materially different artifacts and repository evidence cannot resolve the intent.

## Audit

Keep audit strictly read-only.

1. Run the common preflight.
2. Run `check` and `impact` without write flags when the tool and configuration exist.
3. Compare adapters, indexes, metadata, links, source anchors, lifecycle evidence, and current code behavior.
4. Identify missing capabilities, stale claims, undocumented changes, or unsupported quality claims.
5. Classify output:
   - **Error:** deterministic structural or lifecycle violation.
   - **Warning:** likely stale, orphaned, duplicate, or semantically affected content requiring judgment.
   - **Observation:** improvement opportunity not tied to a violated contract.
6. Report exact paths and evidence. Propose scoped next actions without creating files or updating "last reviewed" fields.

If the repository is uninitialized, report the minimum useful `init` result but do not initialize it.

## Initialize

Create only the smallest useful documentation system and preserve all existing content.

1. Run the common preflight and confirm that writes are authorized.
2. Run `python "<skill-root>/scripts/docs_guard.py" --root "<target>" init` to add missing configuration and core directories without overwriting existing files.
3. Detect capabilities and existing sources of truth.
4. Merge missing discovery links into existing root adapters, or create only explicitly requested/detected adapters.
   Register every detected or newly created adapter in `.docs-architect.json`; leave unrelated tool keys absent rather than predeclaring empty or missing adapters.
5. Create `ARCHITECTURE.md` and a documentation index only when the repository needs them; fill them with verified project-specific content.
6. Add lifecycle directories and templates only when active requirements, decisions, or plans justify them.
7. Avoid empty capability documents. Record unavailable facts as questions or `unknown`.
8. Run `init` again after creating a canonical root document so it is merged into `docs_roots`; inspect the configuration diff.
9. Run `check`, preview `index`, write expected generated indexes, and run `check` again.
10. Inspect the diff for overwritten content. A subsequent `init` with no newly detected canonical documents must not change existing files.

Never reinterpret an existing request as approved merely because it was present before initialization.

## Intake

Create one stable requirement record without prematurely designing or approving it.

1. Run the common preflight and read the requirement template and knowledge model.
2. Search all governed metadata and indexes for an existing or duplicate requirement. Update the existing record when the request is the same intent; link genuinely related work.
3. Allocate the next repository-conventional stable ID. Never reuse an ID from a deleted or superseded artifact.
4. Record the origin, initial `intake` status, user-observable goal, acceptance items, dependencies, affected areas, and unresolved questions.
5. Preserve the user's wording for acceptance criteria. Do not silently broaden, weaken, or mark it accepted.
6. Add only evidence actually supplied or observed. Keep proposed verification separate from completed evidence.
7. Link known product specs, decisions, plans, and system docs through declared relations; do not create speculative companions.
8. Run `check`, preview and write indexes, then inspect the diff.

Use `clarifying` when material questions are explicitly identified. Move to `accepted` only when approval is present in user context or a repository authority source; record it in `approval` separately from `origin`.

## Sync

Make incremental synchronization the default ongoing workflow.

1. Run the common preflight.
2. Identify changed paths from explicit input or Git. Include changed requirements and decisions even when source code is unchanged.
3. Run three-stage impact analysis:
   1. Match paths against declared `sources`, affected paths, and configured globs.
   2. Traverse typed relations to connected requirements, specs, decisions, plans, system docs, and evidence.
   3. Review low-confidence semantic candidates using the actual diff and document contents.
4. Confirm which documented claims changed. A touched source file alone does not prove that every linked document needs edits.
5. Update only affected sections, metadata, relations, and verification anchors. Preserve document voice and unrelated user edits.
6. Advance requirement or plan state only when observed evidence supports the transition. Never infer approval or completion from code existence.
7. When no durable documented truth changed, record or report a scoped no-document-change disposition with a concrete reason. Do not touch documents just to produce a diff.
8. Reconcile thin adapters only when commands, constraints, or discovery paths changed.
9. Run `check`, preview `index`, write it only when expected, re-run `check`, and inspect the diff.

A second `sync` with identical user context, Git state, and evidence must produce no material diff. Do not refresh `verified_at` unless verification was actually rerun against the recorded revision.

## Check

Run deterministic validation without changing files.

1. Run the common preflight.
2. Execute `python "<skill-root>/scripts/docs_guard.py" --root "<target>" check`; add `--json` for automation.
3. Validate configuration, metadata syntax, schema version, unique IDs, allowed types and states, relationship targets, lifecycle evidence, and local Markdown links.
4. Preview the deterministic index and report drift when generated output differs.
5. Report structural errors separately from advisory warnings. Preserve the tool's non-zero exit status for errors; do not fail automation only for semantic candidates.
6. Add a targeted semantic review when the user asks whether content is current, but label it advisory rather than deterministic.

Do not fix findings in `check` mode. When the user explicitly requests validation and repair, finish the read-only result, then enter `sync` for the repairs and re-run `check`.

## Close

Reject unsupported completion claims.

1. Run the common preflight and identify the exact requirement ID.
2. Read the requirement, acceptance criteria, linked artifacts, affected code/docs, and evidence.
3. Verify every acceptance item independently. Require `passed` or `not_applicable` status and at least one resolvable evidence reference per item; evidence for `not_applicable` must justify why the approved criterion does not apply.
4. Confirm linked implementation, validation, decision, and `system-doc` artifacts exist where required.
5. Confirm documentation disposition:
   - list at least one scanned, governed `system-doc` with `status: "active"` that was updated to current truth; unmanaged documents, non-active system docs, lifecycle artifacts, adapters, navigation indexes, and generated indexes do not satisfy this gate; or
   - set `documentation_disposition` to `no_change_required` and record a concrete `no_doc_change_reason`.
6. Run relevant project verification commands when authorized and feasible. Save the actual command and observed result in a repository-relative evidence artifact and reference it from top-level requirement evidence; a test source reference alone does not prove execution.
7. Move through `verifying` and `documented` as evidence permits. Set `done` only after every gate passes.
8. If a gate fails, keep the current state, list missing proof, and make only evidence-backed corrections the user authorized.
9. Run `check`, update expected indexes, re-run `check`, and inspect the diff.

Do not waive acceptance criteria silently. Record an explicit human-authorized criteria change before close, or keep the requirement open.

## Garden

Perform bounded maintenance; do not turn gardening into broad rewriting.

1. Run the common preflight and define a scope from the user, configuration, recently changed paths, or a periodic review window.
2. Run `check`, `impact`, and index preview.
3. Find orphaned IDs and files, dead links, stale source anchors, missing verification revisions, duplicate topics, superseded artifacts, adapter drift, and generated-index drift.
4. Confirm deterministic cleanup such as index refreshes or link repairs before writing.
5. Treat semantic deduplication, retirement, ownership changes, and content deletion as advisory unless repository evidence or explicit user authority resolves them.
6. Prefer linking and marking `superseded` over deleting historical requirements or decisions.
7. Update only verified stale sections. Do not refresh all dates or reformat all docs.
8. Run `check`, update expected indexes, re-run `check`, and inspect the diff.

Report cleanup suggestions that remain uncertain, including the evidence needed to resolve them.

## Deterministic Tool Use

Resolve the bundled script path from the active Skill. Do not assume it is copied into the target repository.

```text
python "<skill-root>/scripts/docs_guard.py" --root "<target>" init
python "<skill-root>/scripts/docs_guard.py" --root "<target>" check [--json]
python "<skill-root>/scripts/docs_guard.py" --root "<target>" impact [--base <git-ref>] [--changed <path> ...] [--json]
python "<skill-root>/scripts/docs_guard.py" --root "<target>" index [--json]
python "<skill-root>/scripts/docs_guard.py" --root "<target>" index --write
```

Use `index` without `--write` for audit, check, impact review, and pre-mutation comparison. Use `--write` only inside an authorized write mode after reviewing the preview.

## Mutation And Idempotence Rules

- Keep all paths repository-relative in metadata and configuration.
- Preserve line endings and local prose conventions where practical.
- Make generated indexes deterministic: stable ordering, stable formatting, and no current-time value unless it represents real evidence.
- Never overwrite dirty files from a template. Merge required fields and sections deliberately.
- Never delete a document merely because it is not in the recommended set.
- Never treat commit time, file modification time, or an agent's assertion as freshness proof.
- Stop and report a conflict when scoped edits cannot preserve overlapping user work.
- Finish a no-op run with a clear no-change report rather than cosmetic churn.

## Result Contract

Always state the selected mode, scope, files changed, requirement transitions, validation outcome, advisory candidates, unresolved questions, and no-change reason when applicable. In `audit` and `check`, state explicitly that no files were changed.

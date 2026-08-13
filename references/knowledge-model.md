# Knowledge And Lifecycle Model

Use this reference for governed Markdown artifacts. Keep prose human-readable and embed one machine-readable JSON metadata comment as the traceability source of truth.

## Contents

- [Artifact Boundaries](#artifact-boundaries)
- [Metadata Envelope](#metadata-envelope)
- [IDs](#ids)
- [Statuses](#statuses)
- [Requirement Fields](#requirement-fields)
- [Relations](#relations)
- [Freshness](#freshness)
- [Impact Traversal](#impact-traversal)
- [Completion Gate](#completion-gate)
- [No-Document-Change Disposition](#no-document-change-disposition)
- [Example Requirement Metadata](#example-requirement-metadata)

## Artifact Boundaries

| Type | Owns | Must not replace |
|---|---|---|
| `requirement` | Motivation, desired outcome, acceptance, lifecycle | Product behavior detail, technical design, implementation journal |
| `product-spec` | Observable behavior, boundaries, exceptions | Approval, architectural rationale, task progress |
| `decision` | Chosen approach, alternatives, rationale, consequences | Current system reference or implementation checklist |
| `exec-plan` | Sequence, dependencies, progress, discoveries, recovery, outcomes | Requirement acceptance or durable system truth |
| `system-doc` | How the current system works and where truth lives | Historical rationale or unverified plans |
| `evidence` | Verifiable proof or a curated evidence manifest | Restated claims without an independently checkable reference |

Keep an artifact separate when its lifecycle or audience differs. Link artifacts rather than copying their content.

## Metadata Envelope

Place exactly one comment near the beginning of every governed artifact:

```html
<!-- docs-architect-meta {"schema_version":1,"id":"REQ-2026-001","type":"requirement","title":"Example requirement","status":"intake"} -->
```

Use strict JSON: double-quoted keys and strings, no comments, no trailing commas, and no duplicate keys. Keep paths repository-relative and use `/` separators. Treat the JSON comment, not a prose table, as the machine-readable source.

Require these fields for every artifact:

| Field | Contract |
|---|---|
| `schema_version` | Integer `1` |
| `id` | Non-empty, repository-unique, stable identifier |
| `type` | One of the six artifact types above |
| `title` | Non-empty human-readable title consistent with the document |
| `status` | A status allowed for the artifact type |

Allow these common optional fields:

| Field | Shape and meaning |
|---|---|
| `owners` | Array of known person, team, or role identifiers; omit or use `[]` when unknown |
| `sources` | Array of repository-relative files or globs that anchor documented truth |
| `update_when` | Array of concrete conditions that require review |
| `relations` | Array of `{ "type": <relation>, "target": <ID-or-path> }` objects |
| `verified_at` | ISO 8601 date or timestamp of an actual verification event |
| `verified_against` | Repository commit OID, or `sha256:<digest>@<repository-relative-file>` for a captured artifact |

Do not set `verified_at` without performing verification. Use a commit OID that resolves in the target repository or a matching file digest; never use a branch, tag, `latest`, arbitrary prose, or an unresolved hash.

## IDs

Follow an existing repository convention. Otherwise use stable, readable prefixes such as:

- `REQ-2026-001` for requirements;
- `SPEC-<slug>` for product specifications;
- `ADR-0001` for decisions;
- `PLAN-<requirement-id>` for execution plans;
- `SYS-<domain>` for system documentation;
- `EVID-<slug>` for evidence manifests.

Search all governed files and generated indexes before allocating an ID. Never derive identity only from a mutable title or path, recycle a retired ID, or change an ID during a file move.

## Statuses

Use this lifecycle for requirements:

```text
intake -> clarifying -> accepted -> planned -> in_progress -> verifying -> documented -> done
   |          |            |           |             |
   +----------+------------+-----------+-------------+--> deferred or rejected
done or any replaced state --------------------------------> superseded
```

Allowed requirement states are:

`intake`, `clarifying`, `accepted`, `planned`, `in_progress`, `verifying`, `documented`, `done`, `deferred`, `rejected`, and `superseded`.

Use `draft`, `active`, `completed`, `superseded`, or `retired` for all other artifact types.

Permit an agent to create `intake`, identify `clarifying`, and advance working states only from recorded evidence. Require explicit user or repository-authority evidence in `approval` before setting `accepted` or a later working state, changing acceptance criteria, waiving a criterion, or reversing `rejected`. Supported approval kinds are `commit`, `document`, `request-record`, `issue-state`, and `pull-request`; the reference must resolve to a repository record outside the requirement, a repository commit, or a durable HTTPS issue/PR state. `origin` alone is not approval. Do not infer approval from implementation, a plan, silence, agent prose, or an agent-created self-approval.

Do not require every intermediate state to produce a separate commit, but never skip the gates represented by approval, verification, documentation, and completion.

## Requirement Fields

Add these fields to requirement metadata:

| Field | Shape and contract |
|---|---|
| `origin` | `{ "kind": <kind>, "ref": <reference> }` or `null` while unresolved; record the actual user, issue, document, meeting, or other source before acceptance |
| `approval` | `{ "kind": <allowed-authority-kind>, "ref": <resolvable-reference> }` or `null`; require explicit, independently checkable authority for `accepted` and every later working state |
| `acceptance` | Array of `{ "id", "text", "status", "evidence" }` objects |
| `dependencies` | Array of requirement IDs or repository-relative artifact paths; mirror governed dependencies with `depends_on` relations |
| `affected_code` | Array of repository-relative files or globs |
| `affected_docs` | Array of repository-relative documentation paths |
| `evidence` | Array of evidence objects supporting requirement-level claims |
| `open_questions` | Array of unresolved questions; do not encode guesses as answers |
| `documentation_disposition` | `pending`, `updated`, or `no_change_required` |
| `no_doc_change_scope` | Non-empty repository-relative paths/globs actually reviewed when disposition is `no_change_required` |
| `no_doc_change_reason` | Concrete reason required when disposition is `no_change_required` |

Use acceptance status `pending`, `passed`, `failed`, or `not_applicable`. Require evidence for both `passed` and `not_applicable`; for the latter, evidence must establish why the approved criterion does not apply. Keep the original acceptance text stable after approval; make authorized changes explicit in prose and evidence rather than silently rewriting history.

Use this evidence object:

```json
{"kind":"test","ref":"tests/test_checkout.py::test_decline","description":"Declined cards retain the cart"}
```

Require non-empty `kind`, `ref`, and `description` strings. Allow `kind` values such as `test`, `command`, `log`, `screenshot`, `pull-request`, `commit`, `release`, `document`, or `other`. Make `ref` independently checkable: use a repository-relative path with an optional locator, an immutable revision, a durable URL, or a captured result location. For Python test references, `check` resolves top-level functions and `Class::method` locators without importing the module; use path-only references for other test frameworks. A test definition proves that the named test exists, not that it passed. A proposed test, unchecked command, bare assertion, or missing path is not evidence.

## Relations

Use only these relation types in schema version 1:

| Relation | Direction |
|---|---|
| `derives_from` | This artifact originates from the target |
| `depends_on` | This artifact cannot proceed or remain valid without the target |
| `implements` | This artifact or code implements the target |
| `validates` | This artifact provides validation for the target |
| `documents` | This artifact describes the current behavior of the target |
| `supersedes` | This artifact replaces the target while retaining history |
| `generated_from` | This generated artifact is derived deterministically from the target |
| `related_to` | A symmetric weak association when no stronger relation applies |

Target a governed artifact by ID. Target an ungoverned source by repository-relative path. Avoid redundant reverse relations unless repository configuration explicitly requires both directions; generate reverse lookup indexes instead.

Prefer specific relations over `related_to`. Never use a relation to imply approval or verification.

## Freshness

Establish freshness from all of the following:

1. `sources` and affected paths identify the code, configuration, or artifacts the document claims to describe.
2. `update_when` describes meaningful review triggers such as an API schema, auth flow, deployment topology, or command change.
3. `verified_at` records when a real review or check occurred.
4. `verified_against` resolves to the exact repository commit or captured artifact digest reviewed.
5. Evidence records what was run or inspected.

Treat a document as a review candidate when its sources changed after `verified_against`, its update trigger occurred, a related artifact changed, or current repository behavior contradicts it. Do not infer freshness from file modification time alone.

## Impact Traversal

Compute impact in three stages:

1. Match changed repository paths to `sources`, `affected_code`, `affected_docs`, and configured globs.
2. Traverse typed relations from directly matched artifacts. Include the relation path in the report.
3. Ask the agent to inspect low-confidence semantic candidates that lack explicit edges.

Block `check` for unsafe paths, broken local links, missing relationship targets, and unresolved lifecycle evidence. Report a declared `sources` pattern that currently matches nothing as a freshness warning because the source may be generated, optional, or temporarily absent. Keep semantic candidates advisory until confirmed. An impacted artifact requires review, not necessarily a content change.

## Completion Gate

Set a requirement to `done` only when all conditions hold:

1. Every acceptance item has `status: "passed"` or `status: "not_applicable"`.
2. Every acceptance item contains at least one non-empty, resolvable evidence object, including evidence justifying `not_applicable`.
3. Acceptance evidence and linked artifacts support the claimed outcome, and top-level evidence includes a captured command or log with an observed result; test source alone is insufficient.
4. Declared dependencies resolve to scanned governed requirements in `done` state.
5. The requirement passed through verification and its affected system documentation is current.
6. With `documentation_disposition: "updated"`, `affected_docs` contains at least one scanned, governed active `system-doc` whose `sources` overlap `affected_code` or whose `documents` relation targets the requirement. Unmanaged or unrelated documents, non-active system docs, lifecycle artifacts, adapters, navigation indexes, and generated indexes do not satisfy this gate. Otherwise, use `no_change_required` with empty `affected_docs`, a resolvable `no_doc_change_scope`, a specific `no_doc_change_reason`, and a captured review/result reference in top-level evidence.
7. No unresolved question invalidates acceptance or documentation disposition.

Reject completion when evidence is planned, missing, inaccessible, contradictory, or merely repeats the acceptance claim. Keep the requirement in its last supported state and report each missing gate.

## No-Document-Change Disposition

Use `no_change_required` only when investigation shows that no durable system, user behavior, architecture, command, constraint, or decision documentation changed. Keep `affected_docs` empty, record the examined repository paths or globs in `no_doc_change_scope`, give a concrete reason, and attach a captured command/log/document review result to top-level evidence. Free text alone cannot satisfy this gate.

Do not create cosmetic documentation edits to avoid a no-change disposition.

## Example Requirement Metadata

```html
<!-- docs-architect-meta {"schema_version":1,"id":"REQ-2026-001","type":"requirement","title":"Retain filters in shared URLs","status":"verifying","owners":[],"sources":["src/search/**","tests/search/**"],"update_when":["Search URL parameters or filter defaults change"],"relations":[],"verified_at":"2026-08-12","verified_against":"sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef@evidence/shared-url-check.txt","origin":{"kind":"issue","ref":"#248"},"approval":{"kind":"issue-state","ref":"https://example.com/issues/248#accepted"},"acceptance":[{"id":"AC-1","text":"Opening a shared URL restores all supported filters","status":"passed","evidence":[{"kind":"test","ref":"tests/search/test_shared_url.py::test_restores_filters","description":"Shared URL restoration test definition"}]}],"dependencies":[],"affected_code":["src/search/**"],"affected_docs":["docs/FRONTEND.md"],"evidence":[{"kind":"command","ref":"evidence/shared-url-check.txt","description":"Captured test command and passing result"}],"open_questions":[],"documentation_disposition":"updated"} -->
```

Keep real metadata readable even when the example is dense. The validator, not visual alignment, defines validity.

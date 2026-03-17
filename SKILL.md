---
name: docs-architect
description: "Generate or reorganize project documentation following a progressive-disclosure, agent-legible structure inspired by harness engineering practices. Use this skill when the user asks to create project docs, generate documentation structure, organize repo docs, build a knowledge base for a codebase, set up CLAUDE.md, AGENTS.md, or ARCHITECTURE.md, audit existing documentation, or wants their project to be better understood by AI coding agents (Claude Code, Codex, Cursor, etc.). Also trigger when the user mentions 'docs/', 'documentation scaffold', 'doc gardening', 'harness engineering docs', 'progressive disclosure docs', or asks to make a repo 'agent-legible' or 'agent-friendly'. Even if the user just says 'set up docs for this project', 'this repo needs documentation', 'generate project docs', or 'organize my docs', this skill applies."
---

# Docs Architect

Generate or reorganize a project's documentation into a progressive-disclosure, agent-legible knowledge base.

The approach comes from a core insight: **give the agent a map, not a 1,000-page manual.** A short entry point (~100 lines) acts as a table of contents, pointing to deeper sources of truth in a structured `docs/` directory. Agents start with a small, stable entry point and know where to look next — rather than being overwhelmed up front.

## Agent Memory File Compatibility

Different AI coding tools use different root-level memory files. This skill generates the appropriate one based on what's detected in the project:

| File | Tool | When to generate |
|------|------|-----------------|
| `CLAUDE.md` | Claude Code (Anthropic) | Default — generate this unless AGENTS.md is already present or user explicitly requests AGENTS.md |
| `AGENTS.md` | Codex (OpenAI) | Generate when AGENTS.md already exists, or user explicitly requests it |
| Both | Mixed team | If both files already exist, update both. If user wants both, generate both with shared content. |

The content structure is the same regardless of filename — only the filename differs. Throughout this skill, "the entry-point file" refers to whichever file (CLAUDE.md or AGENTS.md) is appropriate for the project. When in doubt, check for existing files first; if neither exists, generate `CLAUDE.md`.

**Important**: If a CLAUDE.md or AGENTS.md already exists in the project, do NOT overwrite it entirely. Read it first, preserve its existing content and conventions, and augment it with the documentation map and architecture pointers that may be missing.

## How It Works

This skill operates in two modes depending on what already exists:

- **Greenfield mode**: Project has no `docs/` directory → analyze the project, then generate a complete documentation structure from scratch
- **Reorganize mode**: Project already has documentation → audit what exists, reorganize it into the standard layout, and fill in gaps

In both cases, the generated docs should contain **real, project-specific content** — not generic boilerplate. Every document should reflect actual code, actual architecture, and actual decisions found in the repository.

---

## Phase 1: Project Analysis

Before writing any documentation, build a thorough understanding of the project. This analysis directly determines what documents to generate and what content goes in them.

### 1.1 Detect project identity

Determine these attributes by scanning the codebase:

| Attribute | How to detect |
|-----------|--------------|
| **Language(s)** | File extensions, package managers (package.json, Cargo.toml, go.mod, pyproject.toml, etc.) |
| **Framework(s)** | Dependencies, config files (next.config, django settings, spring configs, etc.) |
| **Project type** | See heuristics in `references/project-types.md` |
| **Doc language** | Existing README language, code comments, commit messages → match that language. Default to English if ambiguous. |
| **Monorepo?** | Multiple package.json / go.mod, workspace configs (pnpm-workspace, Cargo workspace, etc.) |

### 1.2 Map the architecture

- Identify top-level directory structure and what each directory does
- Find entry points (main files, route definitions, CLI entry)
- Identify the domain model: what are the core business entities?
- Map key data flows: how does data enter, transform, and exit the system?
- Find infrastructure: databases, caches, message queues, external APIs
- Identify the layering pattern if any (MVC, hexagonal, domain-driven, etc.)

### 1.3 Audit existing documentation

If docs already exist:
- Catalog every markdown file and its current purpose
- Check for staleness: does the doc match the actual code?
- Identify gaps: what important aspects of the system are undocumented?
- Note good content to preserve during reorganization

---

## Phase 2: Determine Document Set

Based on the project analysis, select which documents to generate. Read `references/project-types.md` for the mapping from project type to recommended document set.

### Core documents (almost always generated)

| Document | Purpose |
|----------|---------|
| `CLAUDE.md` or `AGENTS.md` | The entry point — a ~100-line table of contents that points agents to everything else (see "Agent Memory File Compatibility" above) |
| `ARCHITECTURE.md` | Top-level architecture map: domains, layers, key dependencies, data flow |
| `docs/DESIGN.md` | Design conventions, patterns, and principles used in this project |
| `docs/QUALITY_SCORE.md` | Quality assessment per domain/module, tracking gaps |
| `docs/SECURITY.md` | Security model, auth flows, data handling, threat boundaries |

### Conditional documents (based on project type)

| Document | When to include |
|----------|----------------|
| `docs/FRONTEND.md` | Project has a frontend (React, Vue, Svelte, etc.) |
| `docs/API.md` | Project exposes an API (REST, GraphQL, gRPC) |
| `docs/DATABASE.md` | Project uses a database |
| `docs/RELIABILITY.md` | Production service with uptime requirements |
| `docs/PRODUCT_SENSE.md` | User-facing product (not a library/tool) |
| `docs/PLANS.md` | Active development with planned features |
| `docs/TESTING.md` | Complex testing strategy worth documenting |
| `docs/DEPLOYMENT.md` | Non-trivial deployment process |

### Subdirectories (include when relevant)

| Directory | Purpose | When to include |
|-----------|---------|----------------|
| `docs/design-docs/` | Design decisions with index.md + core-beliefs.md | Projects with significant architectural decisions |
| `docs/exec-plans/` | Active/completed plans + tech-debt-tracker.md | Projects in active development |
| `docs/generated/` | Auto-generated docs (schemas, API specs) | Projects with generatable artifacts |
| `docs/product-specs/` | Product specifications with index.md | User-facing products |
| `docs/references/` | External reference materials, llms.txt files | Projects using specific external tools/libs |

---

## Phase 3: Generate Documentation

### 3.1 Start with the entry-point file (CLAUDE.md / AGENTS.md)

This is the most critical file — it's the entry point that agents see first. Keep it around 100 lines. Structure:

```markdown
# [Project Name]

[One paragraph: what this project is and does]

## Quick Start
[How to set up, build, run, and test — the bare minimum]

## Repository Structure
[Top-level directory map with one-line descriptions]

## Architecture Overview
[2-3 paragraphs summarizing the system, with pointer to ARCHITECTURE.md]

## Documentation Map
[Table linking to every doc in docs/ with a one-line description of each]

## Key Conventions
[5-10 most important rules: naming, patterns, constraints]

## Common Tasks
[How to add a feature, fix a bug, add a test — the most frequent workflows]
```

The goal: an agent reading only this entry-point file should know (a) what this project is, (b) how to run it, (c) where to find deeper info on any topic.

### 3.2 Write ARCHITECTURE.md

This is the technical map. It should cover:

- System overview with a text-based diagram showing major components
- Domain breakdown: each business domain with its purpose and boundaries
- Layer architecture: how code is organized within each domain
- Data flow: how requests/data move through the system
- Key dependencies: what external services/libraries are critical and why
- Cross-cutting concerns: auth, logging, error handling, configuration

### 3.3 Write each docs/ file

For every document, follow this principle: **write what's true about this specific project, not generic advice.**

Bad: "Security is important. Always validate user input."
Good: "Authentication uses JWT tokens issued by the `/auth/login` endpoint. Tokens are validated in the `authMiddleware` (src/middleware/auth.ts). Session state is stored in Redis with a 24h TTL."

Each document should:
- Start with a one-paragraph summary of what this document covers
- Use headings that reflect the actual structure of this project
- Reference specific files, directories, and code patterns
- Include cross-links to related documents
- End with a "Related docs" section pointing to connected documentation

### 3.4 Reorganize mode specifics

When the project already has documentation:

1. **Preserve valuable content** — don't discard well-written existing docs; migrate their content into the new structure
2. **Merge overlapping docs** — if there are multiple files covering similar topics, combine them
3. **Mark migration** — at the top of reorganized docs, briefly note what was merged/moved so the team understands the change
4. **Suggest deletions** — list any old doc files that are now redundant, but don't auto-delete them. Present the list to the user.

---

## Phase 4: Cross-linking and Validation

After generating all documents:

1. **Cross-link check**: every document referenced in the entry-point file must exist; every document in docs/ should be referenced from the entry-point file
2. **Freshness anchors**: each doc should reference specific files/dirs that exist in the repo, so staleness becomes detectable
3. **Completeness check**: compare the generated set against the recommended set for this project type. Report any intentional omissions to the user.

---

## Output

Present the results to the user as follows:

1. **Summary**: what was analyzed, what project type was detected, what documents were generated
2. **Document list**: each file path with a one-line description
3. **Gaps noted**: anything that couldn't be determined from code alone and needs human input (mark these as `<!-- TODO: [question] -->` in the docs)
4. **If reorganize mode**: list of old files that can be safely removed

Write all files to disk. Do not ask for confirmation before writing — generate everything, then let the user review and request changes.

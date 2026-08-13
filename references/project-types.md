# Capability Detection And Document Selection

Detect independent capabilities. Do not force a repository into one mutually exclusive project type: a monorepo may contain a web client, an API, a CLI, infrastructure, and libraries at once.

## Detection Procedure

1. Inspect manifests, workspace files, entry points, directory names, schemas, deployment files, and verified dependencies.
2. Record positive evidence for each capability and its scope.
3. Treat naming alone as a weak signal; confirm it with code, configuration, or a manifest.
4. Select documents only for capabilities that need durable explanation.
5. Mark uncertain capabilities as questions. Do not create speculative documents.
6. Re-run detection incrementally for changed manifests, packages, and infrastructure rather than rescanning unrelated content.

Also detect:

- documentation language from existing authoritative docs; preserve mixed-language conventions when intentional;
- monorepo boundaries from workspace configuration and multiple manifests;
- active agent tools from root and scoped instruction files;
- lifecycle maturity from existing requirements, plans, decisions, releases, and CI;
- source-of-truth files, generated outputs, and vendored directories that should be excluded.

## Capability Matrix

| Capability | Strong signals | Documentation candidates |
|---|---|---|
| Web or desktop UI | UI framework dependency plus components, routes, or native views | `docs/FRONTEND.md`, design system or UX docs, product specs |
| Public or internal API | Route registrations, RPC services, GraphQL/OpenAPI schemas | `docs/API.md`, auth and compatibility sections |
| Persistent data | Migrations, schemas, ORM configuration, durable stores | `docs/DATABASE.md`, data lifecycle and recovery sections |
| Background processing | Queue consumers, schedulers, workflow definitions, workers | Architecture data flow, reliability and operations docs |
| CLI | Executable manifest entry, argument parser, command tree | Command reference, usage conventions, testing docs |
| Library or SDK | Exported public surface, packaging metadata, registry publication | API reference, compatibility policy, design and contribution docs |
| Data or ML pipeline | DAGs, notebooks plus production pipeline code, model or dataset manifests | Pipeline architecture, data lineage, evaluation and reproducibility docs |
| Infrastructure | Terraform, Pulumi, CDK, Kubernetes, Ansible, or primary CI/CD configuration | Deployment, topology, security, reliability, runbooks |
| Authentication or sensitive data | Auth middleware, identity provider, secrets, regulated or personal data paths | `docs/SECURITY.md`, threat boundaries, data handling |
| Production operations | Deploy targets, SLOs, telemetry, alerts, incident or rollback tooling | `docs/RELIABILITY.md`, `docs/DEPLOYMENT.md`, runbooks |
| User-facing product behavior | User journeys, feature flags, UI/API behavior with product acceptance | Product specs, product principles, requirement records |
| Complex verification | Multiple test layers, fixtures, contract/e2e/performance suites | `docs/TESTING.md`, evidence conventions |
| Active multi-step development | Requirements, issue references, plans, cross-module changes | Requirements and execution plans |
| Significant technical choices | Competing approaches, compatibility constraints, irreversible decisions | Decision records |
| Monorepo | Workspace manifest or multiple independently built packages | Root architecture plus scoped package docs and nested adapters |

## Core Selection Rules

Create the smallest useful system:

- Create or update a root adapter only for detected or explicitly requested agent tools.
- Create `ARCHITECTURE.md` when cross-component boundaries, dependencies, or flows require a stable map.
- Create a documentation index when more than a few durable docs need discovery.
- Create requirement, decision, and execution-plan directories when active development needs traceability.
- Create security documentation only from observed security boundaries; flag missing controls without inventing them.
- Create quality documentation only when its claims cite actual checks or evidence. Record unavailable measurements as `unknown`.
- Add capability-specific docs only when their content would be more durable and useful than existing code, generated reference, or a short architecture section.

Do not create empty files merely because a capability exists. Prefer expanding an existing canonical document when a separate file would contain only a small section.

## Capability Content Prompts

Use these as investigation prompts, not boilerplate headings.

| Capability | Investigate |
|---|---|
| UI | route and component boundaries, state ownership, styling, accessibility, asset and build pipeline |
| API | consumers, auth, versioning, request/response contracts, errors, pagination, rate limits |
| Data | ownership, schema, migrations, consistency, retention, deletion, backup, restore |
| Workers | delivery semantics, retries, idempotency, ordering, failure recovery, observability |
| CLI | command tree, configuration precedence, exit codes, output compatibility, destructive operations |
| Library/SDK | supported surface, compatibility guarantees, packaging, extension points, examples |
| Data/ML | sources, transforms, lineage, evaluation, reproducibility, versioning, deployment |
| Infrastructure | topology, environments, state, rollout, rollback, secrets, failure domains |
| Operations | service objectives, telemetry, alerts, degradation, incidents, ownership |
| Testing | layers, commands, fixtures, hermeticity, CI selection, known gaps |

Reference actual repository paths and verified behavior. Link generated API or schema artifacts instead of manually duplicating them.

## Monorepo Scoping

Map package ownership and dependency direction at the root. Add package-local documentation or nested agent instructions only when the package has distinct commands, constraints, or architecture. Keep shared policies at the highest applicable scope and local files limited to differences.

When a changed path belongs to one package, inspect its declared relations and shared dependencies before expanding impact to the whole monorepo. Do not update every package document by default.

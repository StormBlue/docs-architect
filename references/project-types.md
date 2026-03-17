# Project Type Detection & Document Mapping

## Project Type Heuristics

### Frontend Application
**Signals**: package.json with React/Vue/Svelte/Angular; src/components/ or src/pages/; vite.config / next.config / nuxt.config; index.html entry point; CSS/SCSS/Tailwind config
**Recommended docs**: FRONTEND.md, DESIGN.md, PRODUCT_SENSE.md, QUALITY_SCORE.md, SECURITY.md
**Skip**: DATABASE.md (unless BFF pattern), RELIABILITY.md (unless SSR/production), API.md (unless API routes)

### Backend API Service
**Signals**: Express/Fastify/Flask/Django/Spring/Gin/Actix routes; Dockerfile or docker-compose; database migrations; API schema files (OpenAPI, GraphQL schema)
**Recommended docs**: API.md, DATABASE.md, RELIABILITY.md, SECURITY.md, DEPLOYMENT.md, QUALITY_SCORE.md
**Skip**: FRONTEND.md, PRODUCT_SENSE.md (unless user-facing admin)

### Full-Stack Application
**Signals**: Both frontend framework AND backend routes in same repo; or monorepo with client/server packages
**Recommended docs**: All core + FRONTEND.md, API.md, DATABASE.md, RELIABILITY.md, PRODUCT_SENSE.md, DEPLOYMENT.md
**Subdirs**: design-docs/, product-specs/, exec-plans/ (if active development)

### Library / SDK / Package
**Signals**: Primarily exports functions/classes; has a build step producing dist/; published to package registry; minimal or no runtime entry point
**Recommended docs**: API.md (as public API reference), DESIGN.md, TESTING.md, QUALITY_SCORE.md
**Skip**: FRONTEND.md, RELIABILITY.md, DEPLOYMENT.md, PRODUCT_SENSE.md, PLANS.md
**Special**: Add CONTRIBUTING.md, CHANGELOG.md conventions in DESIGN.md

### CLI Tool
**Signals**: bin/ directory or bin field in package.json; commander/yargs/clap/cobra dependency; main entry processes argv
**Recommended docs**: API.md (as command reference), DESIGN.md, TESTING.md, QUALITY_SCORE.md
**Skip**: FRONTEND.md, DATABASE.md (usually), PRODUCT_SENSE.md

### Monorepo / Multi-Package
**Signals**: pnpm-workspace.yaml, lerna.json, Cargo workspace, Go workspace, Nx config, Turborepo
**Recommended docs**: All that apply per sub-package, plus top-level ARCHITECTURE.md mapping inter-package dependencies
**Special**: Each significant sub-package may warrant its own mini docs/ or at minimum a README.md

### Data Pipeline / ML Project
**Signals**: Jupyter notebooks, data/ directories, model training scripts, DAG definitions (Airflow, Prefect), heavy numpy/pandas/torch usage
**Recommended docs**: ARCHITECTURE.md (pipeline stages), DATABASE.md (data sources/sinks), DESIGN.md, QUALITY_SCORE.md
**Special**: Add data flow documentation, model versioning notes

### Infrastructure / DevOps
**Signals**: Terraform/Pulumi/CDK files, Kubernetes manifests, Ansible playbooks, CI/CD configs as primary content
**Recommended docs**: ARCHITECTURE.md (infra topology), SECURITY.md, RELIABILITY.md, DEPLOYMENT.md
**Skip**: FRONTEND.md, API.md, PRODUCT_SENSE.md

---

## Document Content Guidelines by Type

### FRONTEND.md
- Component hierarchy and organization pattern
- Styling approach (CSS modules, Tailwind, styled-components, etc.)
- State management strategy
- Routing structure
- Key UI patterns and shared components
- Accessibility approach
- Performance targets (Core Web Vitals, bundle size)

### API.md
- Endpoint inventory (or pointer to generated OpenAPI spec)
- Authentication/authorization model for API consumers
- Request/response conventions (pagination, error format, versioning)
- Rate limiting and quota policies
- Key data models exposed via the API

### DATABASE.md
- Schema overview (entities, relationships)
- Migration strategy and tooling
- Query patterns and performance considerations
- Data lifecycle (retention, archival, deletion)
- Backup and recovery approach

### RELIABILITY.md
- SLA/SLO targets
- Monitoring and alerting setup
- Error handling and retry strategies
- Graceful degradation patterns
- Incident response pointers

### PRODUCT_SENSE.md
- Target user personas
- Core user journeys
- Key metrics and success criteria
- Feature prioritization framework
- UX principles specific to this product

### TESTING.md
- Testing strategy (unit/integration/e2e ratios)
- Test runner and framework setup
- How to write and run tests
- CI test pipeline
- Mocking and fixture conventions

### DEPLOYMENT.md
- Deployment pipeline stages
- Environment configuration (dev/staging/prod)
- Rollback procedures
- Feature flag strategy
- Release process

### DESIGN.md
- Code organization conventions
- Naming patterns
- Error handling philosophy
- Dependency management approach
- Key architectural patterns used (and why)

### QUALITY_SCORE.md
- Per-module/domain quality grade (A-F or similar)
- Test coverage metrics
- Known technical debt items
- Areas needing improvement
- Quality trend over time

### SECURITY.md
- Authentication and authorization model
- Data classification and handling
- Secret management
- Input validation boundaries
- Known security considerations

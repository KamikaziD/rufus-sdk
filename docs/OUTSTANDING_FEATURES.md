# Rufus Outstanding Features & Roadmap

**Last Updated:** 2026-02-02
**Current Version:** 0.9.0 (Pre-release)
**Next Release:** 1.0.0 (Production-ready)
**Target Date:** Q2 2026

This document tracks planned features, in-progress work, and the project roadmap for Rufus SDK.

---

## Table of Contents

- [Version Status](#version-status)
- [Feature Categories](#feature-categories)
- [Roadmap by Release](#roadmap-by-release)
- [Known Issues & Limitations](#known-issues--limitations)
- [How to Request Features](#how-to-request-features)

---

## Version Status

### Current Release: v0.9.0 (Pre-release)

**Status:** Production-capable for most workloads, API may change in minor releases.

**Release Highlights:**
- ✅ Core workflow orchestration complete
- ✅ 8 step types implemented
- ✅ 21 CLI commands
- ✅ SQLite + PostgreSQL + Redis persistence
- ✅ Multiple execution providers
- ✅ Saga pattern with compensation
- ✅ Zombie workflow recovery
- ✅ Workflow versioning & snapshots
- ✅ Performance optimizations (Phase 1)

**What's Missing for 1.0:**
- Enhanced monitoring & observability
- Web UI (separate project)
- Production deployment templates
- More ecosystem packages
- Comprehensive performance benchmarks

---

## Feature Categories

### 1. Core SDK Features

#### ✅ Implemented & Stable
- [x] Workflow orchestration engine
- [x] 8 step types (STANDARD, ASYNC, PARALLEL, DECISION, LOOP, HTTP, FIRE_AND_FORGET, CRON_SCHEDULER)
- [x] Saga pattern with compensation
- [x] Sub-workflows with status propagation
- [x] Parallel execution with merge strategies
- [x] Human-in-the-loop workflows
- [x] Zombie workflow recovery
- [x] Workflow versioning & definition snapshots
- [x] Type-safe state models (Pydantic)
- [x] Provider-based architecture

#### 🚧 In Progress
- [ ] **Loop step improvements** (Target: v0.9.1)
  - Better iteration control
  - Break/continue conditions
  - Nested loop support

- [ ] **Cron scheduler enhancements** (Target: v0.9.1)
  - Timezone support
  - Schedule conflicts handling
  - Better error recovery

- [ ] **Error message improvements** (Target: v0.9.2)
  - More context in error messages
  - Suggested fixes
  - Error code system

#### 📋 Planned

**v1.0 (Q2 2026):**
- [ ] **Workflow Composition/Templates**
  - Reusable workflow components
  - Template inheritance
  - Parameterized sub-workflows

- [ ] **Time-based Triggers**
  - Schedule workflows at specific times
  - Recurring schedules beyond cron
  - Calendar integration

- [ ] **Event-based Triggers** (v1.1)
  - Webhook triggers
  - Database change triggers
  - Message queue triggers

- [ ] **Workflow Debugging Tools** (v1.1)
  - Step-through debugging
  - Breakpoint support
  - State inspection at any point

- [ ] **Visual Workflow Editor** (v1.2)
  - Web-based workflow designer
  - YAML export/import
  - Visual dependency graph

---

### 2. Persistence & State

#### ✅ Implemented & Stable
- [x] SQLite persistence provider
- [x] PostgreSQL persistence provider
- [x] Redis persistence provider
- [x] In-memory persistence (testing)
- [x] Auto-migration system
- [x] Workflow versioning & snapshots
- [x] Audit logging (PostgreSQL)

#### 📋 Planned

**v1.0 (Q2 2026):**
- [ ] **State Snapshots API**
  - Save workflow state at any point
  - Restore from specific snapshot
  - Snapshot management commands

**v1.1 (Q3 2026):**
- [ ] **MySQL Persistence Provider**
  - Full compatibility with MySQL 8.0+
  - Migration tooling from other providers

- [ ] **MongoDB Persistence Provider**
  - Document-based storage
  - Flexible schema for dynamic workflows

**v1.2 (Q4 2026):**
- [ ] **State History Queries**
  - Query historical state values
  - Time-series analysis
  - State diff visualization

- [ ] **DynamoDB Persistence Provider**
  - AWS-native persistence
  - Auto-scaling support

---

### 3. Execution & Performance

#### ✅ Implemented & Stable
- [x] Sync executor
- [x] Thread pool executor
- [x] Celery executor (distributed)
- [x] PostgreSQL executor
- [x] Performance optimizations (uvloop, orjson, connection pooling, import caching)

#### 📋 Planned

**v1.1 (Q3 2026):**
- [ ] **Ray Executor**
  - Distributed compute with Ray
  - GPU support for ML workflows
  - Auto-scaling

- [ ] **Kubernetes Executor**
  - Execute steps as K8s jobs
  - Resource management
  - Pod template customization

**v1.2 (Q4 2026):**
- [ ] **Auto-scaling Policies**
  - Dynamic worker scaling
  - Load-based scaling
  - Cost optimization

- [ ] **Lambda Executor**
  - Execute steps as AWS Lambda functions
  - Serverless workflows
  - Cost-efficient for bursty workloads

---

### 4. Observability

#### ✅ Implemented & Stable
- [x] Logging observer (console)
- [x] CLI metrics command
- [x] Audit logging (PostgreSQL)
- [x] Workflow heartbeats
- [x] Zombie detection & recovery

#### 🚧 In Progress
- [ ] **OpenTelemetry Integration** (Target: v1.0)
  - Distributed tracing
  - Span creation for each step
  - Integration with Jaeger, Zipkin

#### 📋 Planned

**v1.0 (Q2 2026):**
- [ ] **Prometheus Metrics Exporter**
  - Standard metrics endpoint
  - Workflow duration histograms
  - Step execution counters
  - Error rate gauges

- [ ] **Grafana Dashboards**
  - Pre-built dashboards
  - Workflow health monitoring
  - Performance dashboards
  - SLA tracking

**v1.1 (Q3 2026):**
- [ ] **Real-time Workflow Visualization**
  - Live workflow execution view
  - Step progress tracking
  - Resource utilization

- [ ] **SLA Monitoring**
  - Define SLAs per workflow type
  - Alert on SLA violations
  - SLA reporting

- [ ] **DataDog Integration**
  - Native DataDog metrics
  - Log forwarding
  - APM integration

---

### 5. CLI Improvements

#### ✅ Implemented & Stable
- [x] 21 commands across 5 categories
- [x] Interactive configuration
- [x] Rich terminal output
- [x] JSON output mode
- [x] Zombie scanning & recovery daemon

#### 📋 Planned

**v1.0 (Q2 2026):**
- [ ] **Workflow Replay/Debugging**
  - Replay workflow from specific step
  - Debug mode with detailed logging
  - State inspection at each step

- [ ] **Better Output Formatting**
  - Table views for list commands
  - Progress bars for long operations
  - Color-coded status indicators

**v1.1 (Q3 2026):**
- [ ] **Shell Completion**
  - Bash completion
  - Zsh completion
  - Fish completion

- [ ] **Configuration Profiles**
  - Multiple named configurations
  - Switch between profiles
  - Environment-specific configs

---

### 6. Documentation & Examples

#### ✅ Implemented & Stable
- [x] Quickstart example (working)
- [x] SQLite task manager (working)
- [x] Loan application (complex example)
- [x] FastAPI integration example
- [x] Flask integration example
- [x] JavaScript/polyglot example
- [x] Comprehensive documentation

#### 📋 Planned

**v1.0 (Q2 2026):**
- [ ] **Video Tutorials**
  - Getting started video
  - Advanced patterns video
  - Production deployment video

- [ ] **Interactive Documentation**
  - In-browser code examples
  - Try it yourself sandboxes
  - Step-by-step walkthroughs

**v1.1 (Q3 2026):**
- [ ] **Industry-Specific Examples**
  - E-commerce order processing
  - Financial transaction workflows
  - Healthcare patient workflows
  - AI/ML pipelines

- [ ] **Migration Case Studies**
  - Migrating from Temporal
  - Migrating from Airflow
  - Migrating from AWS Step Functions

---

### 7. Developer Experience

#### ✅ Implemented & Stable
- [x] Type hints throughout codebase
- [x] Pydantic validation
- [x] TestHarness for testing
- [x] YAML schema validation
- [x] JSON Schema for IDE support

#### 📋 Planned

**v1.0 (Q2 2026):**
- [ ] **Workflow Linting**
  - Static analysis of YAML workflows
  - Best practice suggestions
  - Performance warnings

**v1.1 (Q3 2026):**
- [ ] **VS Code Extension**
  - YAML IntelliSense
  - Workflow visualization
  - Run/debug workflows from IDE

- [ ] **PyCharm Plugin**
  - Workflow navigation
  - Step function jump-to-definition
  - Integrated testing

**v1.2 (Q4 2026):**
- [ ] **Workflow Generator CLI**
  - Generate workflow from prompts
  - Best practice templates
  - Step function scaffolding

---

### 8. Ecosystem & Integrations

#### ✅ Implemented & Stable
- [x] Package auto-discovery (`rufus-*`)
- [x] rufus-slack (reference implementation)
- [x] Cookiecutter template

#### 🚧 In Progress
- [ ] **rufus-stripe** (Target: v0.9.2)
  - Stripe payment workflows
  - Webhook handling
  - Subscription management

#### 📋 Planned

**v1.0 (Q2 2026):**
- [ ] **rufus-aws**
  - S3 operations
  - Lambda invocations
  - SQS/SNS integrations
  - DynamoDB operations

- [ ] **rufus-sendgrid**
  - Email workflows
  - Template management
  - Delivery tracking

**v1.1 (Q3 2026):**
- [ ] **rufus-gcp**
  - Cloud Functions
  - Cloud Storage
  - Pub/Sub
  - BigQuery

- [ ] **rufus-azure**
  - Azure Functions
  - Blob Storage
  - Service Bus
  - Cosmos DB

- [ ] **rufus-openai**
  - ChatGPT workflows
  - Embeddings
  - Fine-tuning pipelines
  - RAG workflows

**v1.2 (Q4 2026):**
- [ ] **Marketplace/Registry Website**
  - Discover rufus-* packages
  - Usage statistics
  - Community ratings
  - Documentation hosting

---

## Roadmap by Release

### v0.9.1 (March 2026) - Bug Fixes & Polish
- Loop step improvements
- Cron scheduler enhancements
- Bug fixes from community feedback
- Documentation updates

### v0.9.2 (April 2026) - Ecosystem Expansion
- rufus-stripe package
- Error message improvements
- Additional examples
- Performance tuning

### v1.0.0 (Q2 2026) - Production Release
**Focus:** Production-ready, stable API

#### Must-Have for 1.0:
- OpenTelemetry integration
- Prometheus metrics exporter
- Grafana dashboards
- State snapshots API
- Workflow linting
- Enhanced CLI output
- Video tutorials
- Interactive documentation
- rufus-aws package
- rufus-sendgrid package
- Comprehensive benchmarks
- Deployment templates (Docker, K8s, systemd)

#### Nice-to-Have for 1.0:
- Workflow replay/debugging
- Shell completion
- MySQL persistence provider

### v1.1.0 (Q3 2026) - Advanced Features
**Focus:** Advanced workflows and monitoring

- Event-based triggers
- Workflow debugging tools
- Real-time visualization
- SLA monitoring
- Ray executor
- Kubernetes executor
- VS Code extension
- rufus-gcp package
- rufus-azure package
- rufus-openai package

### v1.2.0 (Q4 2026) - Enterprise & Scale
**Focus:** Enterprise features and ecosystem

- Visual workflow editor (web UI)
- Auto-scaling policies
- Lambda executor
- State history queries
- DynamoDB persistence
- MongoDB persistence
- PyCharm plugin
- Workflow generator CLI
- Marketplace/registry website

---

## Known Issues & Limitations

### High Priority (Addressing in v1.0)

1. **SQLite Concurrency Limitations**
   - **Issue:** Single writer limitation
   - **Impact:** <50 concurrent workflows recommended
   - **Timeline:** Documentation improvements in v0.9.1, benchmarks in v1.0
   - **Workaround:** Use PostgreSQL for higher concurrency

2. **Limited Real-time Monitoring**
   - **Issue:** Basic metrics only via CLI
   - **Impact:** Hard to monitor production workflows
   - **Timeline:** OpenTelemetry in v1.0, Prometheus in v1.0
   - **Workaround:** Use PostgreSQL audit logs

3. **No Web UI**
   - **Issue:** CLI and SDK only
   - **Impact:** Less accessible for non-developers
   - **Timeline:** Separate project in v1.2
   - **Workaround:** Build custom UI with FastAPI example

### Medium Priority (Addressing in v1.1)

4. **Manual Deployment**
   - **Issue:** No auto-deployment tools
   - **Impact:** Requires manual setup
   - **Timeline:** Templates in v1.0, automation in v1.1
   - **Workaround:** Use Docker Compose or K8s manifests

5. **Limited Error Context**
   - **Issue:** Errors could be more descriptive
   - **Impact:** Debugging takes longer
   - **Timeline:** Improvements in v0.9.2, v1.0
   - **Workaround:** Enable debug logging

### Low Priority (Future Consideration)

6. **No Visual Workflow Designer**
   - **Issue:** YAML editing only
   - **Impact:** Learning curve for non-developers
   - **Timeline:** v1.2
   - **Workaround:** Use IDE with YAML schema validation

7. **Limited Workflow Debugging**
   - **Issue:** Can't step through workflows
   - **Impact:** Debugging complex workflows harder
   - **Timeline:** v1.1
   - **Workaround:** Use logging and state inspection

---

## Feature Request Process

### How to Request Features

1. **Check This Document**
   - See if feature is already planned
   - Check timeline and priority

2. **Search GitHub Issues**
   - Avoid duplicate requests
   - Comment on existing issues

3. **Open GitHub Discussion**
   - Category: Ideas
   - Describe use case
   - Explain why existing features don't work

4. **Provide Context**
   - **Use case:** What are you trying to accomplish?
   - **Current approach:** How do you handle it now?
   - **Expected behavior:** What should the feature do?
   - **Alternatives:** What else did you consider?

5. **Community Voting**
   - Features with most votes prioritized
   - Maintainers review quarterly

### Feature Prioritization Criteria

Features are prioritized based on:

1. **Impact** - How many users benefit?
2. **Effort** - How complex to implement?
3. **Strategic Alignment** - Does it align with project vision?
4. **Community Demand** - How many votes/requests?
5. **Maintainability** - Can it be maintained long-term?

---

## Contributing

Want to help build these features?

1. **Check [CONTRIBUTING.md](../CONTRIBUTING.md)** (coming soon)
2. **Join GitHub Discussions**
3. **Pick an issue labeled `good-first-issue`**
4. **Propose RFC for major features**

### Areas Needing Help

**High Priority:**
- OpenTelemetry integration
- Prometheus metrics
- MySQL persistence provider
- Workflow linting
- Additional examples

**Documentation:**
- Video tutorials
- Industry-specific examples
- Migration guides

**Ecosystem Packages:**
- rufus-stripe
- rufus-aws
- rufus-sendgrid
- rufus-gcp

---

## Release Philosophy

### Semantic Versioning

Rufus follows **strict semantic versioning**:

- **Major (X.0.0):** Breaking API changes
- **Minor (0.X.0):** New features, backwards compatible
- **Patch (0.0.X):** Bug fixes, backwards compatible

### API Stability Guarantee

**v1.0+:**
- Core SDK API stable (no breaking changes in minor releases)
- CLI commands stable (new commands OK, existing commands won't break)
- Provider interfaces stable (new methods OK, existing methods won't change)
- YAML schema backwards compatible

**Pre-1.0 (v0.x):**
- Minor API changes possible
- Will be documented in changelog
- Migration guide provided for breaking changes

---

## Questions?

- 💬 [GitHub Discussions](https://github.com/your-org/rufus-sdk/discussions)
- 📖 [Full Documentation](README.md)
- 🐛 [Report Issues](https://github.com/your-org/rufus-sdk/issues)

---

**Last Updated:** 2026-02-02
**Next Review:** 2026-03-01 (monthly updates)
**Maintained By:** Rufus SDK Team

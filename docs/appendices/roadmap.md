# Roadmap

Rufus SDK development roadmap with planned features, priorities, and timelines.

**Last Updated:** 2026-02-27
**Current Version:** 0.6.0
**Next Major Release:** 1.0.0

---

## Table of Contents

- [Release Timeline](#release-timeline)
- [Version 0.9.1 (March 2026)](#version-091-march-2026)
- [Version 0.9.2 (April 2026)](#version-092-april-2026)
- [Version 1.0.0 (Q2 2026)](#version-100-q2-2026)
- [Version 1.1.0 (Q3 2026)](#version-110-q3-2026)
- [Version 1.2.0 (Q4 2026)](#version-120-q4-2026)
- [Feature Status](#feature-status)
- [Request Features](#request-features)

---

## Release Timeline

```
2026-02 ━━ v0.3.0 (Documentation release)
   │
2026-02 ━━ v0.4.0 (RUFUS_CUSTOM_ROUTERS)
   │
2026-02 ━━ v0.4.1 (OpenAPI tags, grouped Swagger UI)
   │
2026-02 ━━ v0.4.2 (25 endpoint tests, error handling)
   │
2026-02 ━━ v0.5.0 (33-table schema consolidation)
   │
2026-02 ━━ v0.6.0 (Current ⭐ — package split: rufus-sdk-edge + rufus-sdk-server)
   │
        ━━ v0.7.0 (OpenTelemetry, Prometheus metrics)
   │
        ━━ v0.8.0 (GPU inference step type, mTLS, HSM integration)
   │
        ━━ v1.0.0 (Stable API guarantee)
```

---

## Version 0.9.1 (March 2026)

**Focus:** Bug fixes, polish, and incremental improvements based on community feedback.

### Planned Features

- [ ] **Loop Step Enhancements**
  - Better iteration control
  - Break/continue conditions
  - Nested loop support
  - Performance optimizations

- [ ] **Cron Scheduler Improvements**
  - Timezone support
  - Schedule conflict handling
  - Better error recovery
  - Daylight saving time awareness

- [ ] **Bug Fixes**
  - Community-reported issues
  - Performance edge cases
  - Documentation corrections

- [ ] **Documentation Updates**
  - Additional examples
  - Troubleshooting guides
  - Performance tuning guides

---

## Version 0.9.2 (April 2026)

**Focus:** Ecosystem expansion and developer experience improvements.

### Planned Features

- [ ] **rufus-stripe Package**
  - Stripe payment workflows
  - Webhook handling
  - Subscription management workflows
  - Refund/chargeback workflows

- [ ] **Error Message Improvements**
  - More context in error messages
  - Suggested fixes
  - Error code system
  - Stack trace enhancement

- [ ] **Additional Examples**
  - E-commerce order processing
  - Multi-tenant SaaS workflows
  - Data pipeline examples

- [ ] **Performance Tuning**
  - Additional benchmarks
  - Memory optimization
  - Database query optimization

---

## Version 1.0.0 (Q2 2026)

**Focus:** Production-ready, stable API, enterprise features.

### Must-Have Features

#### Observability & Monitoring

- [ ] **OpenTelemetry Integration**
  - Distributed tracing
  - Span creation for each step
  - Integration with Jaeger, Zipkin
  - Custom trace attributes

- [ ] **Prometheus Metrics Exporter**
  - Standard `/metrics` endpoint
  - Workflow duration histograms
  - Step execution counters
  - Error rate gauges
  - Custom metrics support

- [ ] **Grafana Dashboards**
  - Pre-built dashboards
  - Workflow health monitoring
  - Performance dashboards
  - SLA tracking
  - Resource utilization

#### State Management

- [ ] **State Snapshots API**
  - Save workflow state at any point
  - Restore from specific snapshot
  - Snapshot management commands
  - Time-travel debugging

#### Developer Experience

- [ ] **Workflow Linting**
  - Static analysis of YAML workflows
  - Best practice suggestions
  - Performance warnings
  - Security checks

- [ ] **Enhanced CLI Output**
  - Table views for list commands
  - Progress bars for long operations
  - Color-coded status indicators
  - Better error formatting

#### Ecosystem Packages

- [ ] **rufus-aws**
  - S3 operations
  - Lambda invocations
  - SQS/SNS integrations
  - DynamoDB operations
  - CloudWatch integration

- [ ] **rufus-sendgrid**
  - Email workflows
  - Template management
  - Delivery tracking
  - Bounce handling

#### Documentation & Education

- [ ] **Video Tutorials**
  - Getting started video
  - Advanced patterns video
  - Production deployment video
  - Performance tuning video

- [ ] **Interactive Documentation**
  - In-browser code examples
  - Try it yourself sandboxes
  - Step-by-step walkthroughs

#### Deployment

- [ ] **Deployment Templates**
  - Docker Compose production templates
  - Kubernetes manifests
  - Systemd service files
  - Terraform modules

- [ ] **Comprehensive Benchmarks**
  - Multi-executor comparison
  - Database provider performance
  - Scaling characteristics
  - Resource usage analysis

### Nice-to-Have Features

- [ ] **Workflow Replay/Debugging**
  - Replay workflow from specific step
  - Debug mode with detailed logging
  - State inspection at each step

- [ ] **Shell Completion**
  - Bash completion
  - Zsh completion
  - Fish completion

- [ ] **MySQL Persistence Provider**
  - Full MySQL 8.0+ compatibility
  - Migration tooling from other providers

---

## Version 1.1.0 (Q3 2026)

**Focus:** Advanced workflow features and real-time monitoring.

### Planned Features

#### Advanced Workflow Features

- [ ] **Event-Based Triggers**
  - Webhook triggers
  - Database change triggers
  - Message queue triggers
  - Custom event sources

- [ ] **Workflow Debugging Tools**
  - Step-through debugging
  - Breakpoint support
  - State inspection at any point
  - Replay with state modification

- [ ] **Workflow Composition/Templates**
  - Reusable workflow components
  - Template inheritance
  - Parameterized sub-workflows
  - Workflow libraries

#### Observability

- [ ] **Real-Time Workflow Visualization**
  - Live workflow execution view
  - Step progress tracking
  - Resource utilization
  - WebSocket updates

- [ ] **SLA Monitoring**
  - Define SLAs per workflow type
  - Alert on SLA violations
  - SLA reporting and analytics
  - SLA forecasting

- [ ] **DataDog Integration**
  - Native DataDog metrics
  - Log forwarding
  - APM integration
  - Custom dashboards

#### Execution Providers

- [ ] **Ray Executor**
  - Distributed compute with Ray
  - GPU support for ML workflows
  - Auto-scaling
  - Resource scheduling

- [ ] **Kubernetes Executor**
  - Execute steps as K8s jobs
  - Resource management
  - Pod template customization
  - Job cleanup

#### Developer Tools

- [ ] **VS Code Extension**
  - YAML IntelliSense
  - Workflow visualization
  - Run/debug workflows from IDE
  - Step function jump-to-definition

#### Ecosystem Packages

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
  - RAG (Retrieval-Augmented Generation) workflows

#### Persistence

- [ ] **MongoDB Persistence Provider**
  - Document-based storage
  - Flexible schema for dynamic workflows
  - GridFS for large state

---

## Version 1.2.0 (Q4 2026)

**Focus:** Enterprise features, visual tools, and ecosystem growth.

### Planned Features

#### Visual Tools

- [ ] **Visual Workflow Editor (Web UI)**
  - Web-based workflow designer
  - Drag-and-drop step creation
  - YAML export/import
  - Visual dependency graph
  - Real-time validation

#### Scalability

- [ ] **Auto-Scaling Policies**
  - Dynamic worker scaling
  - Load-based scaling
  - Cost optimization
  - Predictive scaling

- [ ] **Lambda Executor**
  - Execute steps as AWS Lambda functions
  - Serverless workflows
  - Cost-efficient for bursty workloads
  - Automatic retries

#### State Management

- [ ] **State History Queries**
  - Query historical state values
  - Time-series analysis
  - State diff visualization
  - Audit trail exploration

- [ ] **DynamoDB Persistence Provider**
  - AWS-native persistence
  - Auto-scaling support
  - Global tables for multi-region

#### Developer Tools

- [ ] **PyCharm Plugin**
  - Workflow navigation
  - Step function jump-to-definition
  - Integrated testing
  - Workflow templates

- [ ] **Workflow Generator CLI**
  - Generate workflow from prompts
  - Best practice templates
  - Step function scaffolding
  - AI-assisted workflow design

#### Ecosystem

- [ ] **Marketplace/Registry Website**
  - Discover rufus-* packages
  - Usage statistics
  - Community ratings
  - Documentation hosting
  - Package templates

---

## Feature Status

### Completed (v0.6.0 and earlier)

#### Core SDK
- ✅ Workflow orchestration engine
- ✅ 8 step types (STANDARD, ASYNC, PARALLEL, DECISION, LOOP, HTTP, FIRE_AND_FORGET, CRON_SCHEDULER)
- ✅ Saga pattern with compensation
- ✅ Sub-workflows with status propagation
- ✅ Human-in-the-loop workflows
- ✅ Dynamic step injection
- ✅ Type-safe state models (Pydantic)
- ✅ Provider-based architecture

#### Persistence
- ✅ SQLite persistence provider
- ✅ PostgreSQL persistence provider
- ✅ Redis persistence provider
- ✅ In-memory persistence (testing)
- ✅ Alembic migration system
- ✅ Workflow versioning & snapshots

#### Execution
- ✅ Sync executor
- ✅ Thread pool executor
- ✅ Celery executor (distributed)
- ✅ PostgreSQL executor
- ✅ Performance optimizations (uvloop, orjson, connection pooling, import caching)

#### Observability
- ✅ Logging observer (console)
- ✅ CLI metrics command
- ✅ Audit logging (PostgreSQL)
- ✅ Workflow heartbeats
- ✅ Zombie detection & recovery
- ✅ Debug UI (web interface)
- ✅ OpenAPI tags / grouped Swagger UI (14 tag groups, 86 endpoints) — v0.4.1
- ✅ RUFUS_CUSTOM_ROUTERS for user-defined API extensions — v0.4.0

#### CLI
- ✅ 21 commands across 5 categories
- ✅ Interactive configuration
- ✅ Rich terminal output
- ✅ JSON output mode
- ✅ Zombie scanning & recovery daemon

#### Database & Schema
- ✅ 33-table PostgreSQL schema under Alembic management — v0.5.0
- ✅ 10-table SQLite edge schema (auto-created) — v0.5.0
- ✅ Edge-specific tables: saf_pending_transactions, device_config_cache, edge_sync_state — v0.5.0

#### Documentation
- ✅ Quickstart guide
- ✅ YAML configuration guide
- ✅ CLI usage guide
- ✅ How-to guides
- ✅ Architecture documentation
- ✅ API reference

#### Examples
- ✅ Quickstart example
- ✅ SQLite task manager
- ✅ Loan application (complex)
- ✅ FastAPI integration
- ✅ Flask integration
- ✅ JavaScript/polyglot example

#### Ecosystem
- ✅ Package auto-discovery (`rufus-*`)
- ✅ rufus-slack (reference implementation)
- ✅ Cookiecutter template

### In Progress

- 🚧 **OpenTelemetry Integration** (Target: v1.0)
- 🚧 **rufus-stripe** (Target: v0.9.2)

### Planned

See version sections above for complete planned feature list.

---

## Request Features

Want to influence the roadmap? Here's how:

### 1. Check Existing Plans

- Review this roadmap
- Search [GitHub Issues](https://github.com/your-org/rufus-sdk/issues)
- Check [GitHub Discussions](https://github.com/your-org/rufus-sdk/discussions)

### 2. Open a Feature Request

Use the **Ideas** category in GitHub Discussions and provide:

- **Use case:** What are you trying to accomplish?
- **Current approach:** How do you handle it now?
- **Expected behavior:** What should the feature do?
- **Alternatives:** What else did you consider?

### 3. Community Voting

Features with the most votes are prioritized. Maintainers review quarterly.

### 4. Contribute

Want to build it yourself? Check `contributing.md` and join the discussion!

### Prioritization Criteria

Features are prioritized based on:

1. **Impact** - How many users benefit?
2. **Effort** - How complex to implement?
3. **Strategic Alignment** - Does it align with project vision?
4. **Community Demand** - How many votes/requests?
5. **Maintainability** - Can it be maintained long-term?

---

## API Stability Guarantee

### v1.0+
- Core SDK API stable (no breaking changes in minor releases)
- CLI commands stable (new commands OK, existing won't break)
- Provider interfaces stable (new methods OK, existing won't change)
- YAML schema backwards compatible

### Pre-1.0 (v0.x)
- Minor API changes possible
- Documented in changelog
- Migration guide provided for breaking changes

---

## Release Philosophy

Rufus follows **strict semantic versioning**:

- **Major (X.0.0):** Breaking API changes
- **Minor (0.X.0):** New features, backwards compatible
- **Patch (0.0.X):** Bug fixes, backwards compatible

---

## Contributing to Roadmap

Areas needing help:

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

See `contributing.md` for details on how to help.

---

## Questions?

- 💬 [GitHub Discussions](https://github.com/your-org/rufus-sdk/discussions)
- 📖 [Full Documentation](/docs/README.md)
- 🐛 [Report Issues](https://github.com/your-org/rufus-sdk/issues)

---

**Note:** This roadmap is a living document and may change based on community feedback, technical constraints, and strategic priorities. Features may be added, removed, or rescheduled.

**Last Updated:** 2026-02-24

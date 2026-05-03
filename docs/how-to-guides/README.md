# How-to guides

Task-oriented guides for common Ruvon workflows.

## Getting started

- [**Installation**](installation.md) - Install Ruvon for different scenarios (SQLite, PostgreSQL, Docker)
- [**Configuration**](configuration.md) - Configure persistence, execution, and observability providers
- [**Create a workflow**](create-workflow.md) - Build your first workflow from scratch

## Core features

- [**Decision steps**](decision-steps.md) - Implement conditional branching and routing
- [**HTTP steps**](http-steps.md) - Call external services in any language (polyglot workflows)
- [**Human-in-the-loop**](human-in-loop.md) - Pause workflows for approvals and manual input
- [**Saga mode**](saga-mode.md) - Enable automatic compensation and rollback on failure

## Operations

- [**Testing**](testing.md) - Write tests for workflows with TestHarness and pytest
- [**Deployment**](deployment.md) - Deploy to production (Docker, Kubernetes, standalone)
- [**Troubleshooting**](troubleshooting.md) - Common issues and solutions

## Guide format

Each guide follows this structure:

1. **Overview** - What this guide covers
2. **Step-by-step instructions** - Clear, actionable steps
3. **Working examples** - Real code you can run
4. **Common patterns** - Best practices for this feature
5. **Testing** - How to test this functionality
6. **Next steps** - Where to go from here

## Quick links

### By use case

**I want to...**

- **Get started quickly** → [Installation](installation.md) → [Create a workflow](create-workflow.md)
- **Add conditional logic** → [Decision steps](decision-steps.md)
- **Call external services** → [HTTP steps](http-steps.md)
- **Add approvals** → [Human-in-the-loop](human-in-loop.md)
- **Handle failures** → [Saga mode](saga-mode.md)
- **Test my workflows** → [Testing](testing.md)
- **Deploy to production** → [Deployment](deployment.md)
- **Fix an issue** → [Troubleshooting](troubleshooting.md)

### By deployment type

- **Local development** → [Installation (SQLite)](installation.md#path-1-direct-install-sqlite)
- **Docker development** → [Installation (Docker)](installation.md#path-2-docker-with-postgresql)
- **Production (single server)** → [Deployment (embedded)](deployment.md#model-1-embedded-sdk)
- **Production (distributed)** → [Deployment (Celery)](deployment.md#model-3-distributed-with-celery)
- **Kubernetes** → [Deployment (K8s)](deployment.md#kubernetes-deployment)

## Related documentation

- **[Tutorials](../tutorials/)** - Learning-oriented lessons for beginners
- **[Reference](../reference/)** - Technical reference documentation
- **[Explanation](../explanation/)** - Understanding-oriented deep dives

## Contributing

Found an issue or have a suggestion? Please open an issue on GitHub.

---

**Last updated:** 2026-02-13

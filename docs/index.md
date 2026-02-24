# Rufus SDK Documentation

**Rufus** is a self-hosting workflow runtime for mission-critical autonomous systems. The same SDK that runs on an edge device (POS terminal, ATM, drone, surgical device) also powers the cloud control plane that manages that device — three roles, one runtime, no magic paths.

**The self-hosting insight:** Rufus orchestrates itself. Configuration rollout, audit aggregation, and policy enforcement on the control plane are themselves Rufus workflows, battle-tested by their own use.

**Built for:** Robotics, drones, surgical devices, industrial IoT, fleet intelligence, POS terminals, ATMs — anywhere the network is unreliable, absent, or a safety risk.

## Documentation Structure

This documentation follows the [Diátaxis framework](https://diataxis.fr/) - four distinct types of documentation for different user needs:

```
        Most useful when studying              Most useful when working
                    │                                     │
Learning-oriented   │   TUTORIALS                        │   HOW-TO GUIDES   Goal-oriented
                    │                                     │
                    │   ┌─────────────────┐              │
                    │   │                 │              │
                    │   │     RUFUS       │              │
                    │   │       SDK       │              │
                    │   │                 │              │
                    │   └─────────────────┘              │
                    │                                     │
Understanding-      │   EXPLANATION                      │   REFERENCE       Information-
oriented            │                                     │   oriented
                    │                                     │
        Most useful when understanding           Most useful when coding
```

---

## 🎓 [Tutorials](tutorials/) - Learning-Oriented

**"I want to learn how to use Rufus"**

Step-by-step lessons to build skills and confidence:

1. **[Getting Started](tutorials/getting-started.md)** - Your first workflow in 5 minutes
2. **[Build a Task Manager](tutorials/build-task-manager.md)** - Complete practical project
3. **[Adding Parallel Execution](tutorials/parallel-execution.md)** - Concurrent tasks
4. **[Implementing Compensation](tutorials/saga-pattern.md)** - Handle failures gracefully
5. **[Edge Device Deployment](tutorials/edge-deployment.md)** - Deploy to real hardware

**New to Rufus?** Start with [Getting Started](tutorials/getting-started.md).

---

## 📘 [How-To Guides](how-to-guides/) - Task-Oriented

**"I want to accomplish a specific task"**

Practical directions for common goals:

### Setup & Configuration
- **[Installation](how-to-guides/installation.md)** - Install Rufus in your environment
- **[Configuration](how-to-guides/configuration.md)** - Configure databases, executors, observers

### Building Workflows
- **[Create a Workflow](how-to-guides/create-workflow.md)** - Define workflows in YAML
- **[Add Decision Steps](how-to-guides/decision-steps.md)** - Conditional branching
- **[Use HTTP Steps](how-to-guides/http-steps.md)** - Call external services (polyglot)
- **[Implement Human-in-the-Loop](how-to-guides/human-in-loop.md)** - Pause for manual input
- **[Enable Saga Mode](how-to-guides/saga-mode.md)** - Automatic compensation

### Testing & Deployment
- **[Test Workflows](how-to-guides/testing.md)** - Unit and integration testing
- **[Deploy to Production](how-to-guides/deployment.md)** - Docker, Kubernetes, scaling
- **[Optimize Performance](how-to-guides/performance.md)** - Tune for high throughput
- **[Troubleshooting](how-to-guides/troubleshooting.md)** - Debug common issues

### Migration
- **[Migrate from Temporal](how-to-guides/migrate-from-temporal.md)** - Switch from Temporal.io

---

## 📖 [Reference](reference/) - Information-Oriented

**"I need to look up technical details"**

Dry, accurate technical specifications:

### API Reference
- **[WorkflowBuilder](reference/api/workflow-builder.md)** - Build workflows from YAML
- **[Workflow Class](reference/api/workflow.md)** - Core workflow orchestration
- **[Providers](reference/api/providers.md)** - Persistence, execution, observability
- **[StepContext](reference/api/step-context.md)** - Context passed to step functions
- **[Directives](reference/api/directives.md)** - Control flow exceptions

### Configuration Reference
- **[YAML Schema](reference/yaml-schema.md)** - Complete workflow YAML specification
- **[Step Types](reference/step-types.md)** - All 9 step types (STANDARD, ASYNC, LOOP, etc.)
- **[CLI Commands](reference/cli-commands.md)** - Complete CLI reference
- **[Database Schema](reference/database-schema.md)** - PostgreSQL and SQLite schemas
- **[Configuration Options](reference/configuration.md)** - Environment variables and settings
- **[Error Codes](reference/error-codes.md)** - Error messages and solutions

---

## 💡 [Explanation](explanation/) - Understanding-Oriented

**"I want to understand how Rufus works"**

Context, background, and design decisions:

### Core Concepts
- **[Architecture Overview](explanation/architecture.md)** - System design and components
- **[Provider Pattern](explanation/provider-pattern.md)** - Pluggable interfaces
- **[Workflow Lifecycle](explanation/workflow-lifecycle.md)** - From start to completion
- **[State Management](explanation/state-management.md)** - How state persists and flows

### Advanced Concepts
- **[Saga Pattern Explained](explanation/saga-pattern.md)** - Distributed transactions
- **[Parallel Execution Model](explanation/parallel-execution.md)** - Concurrency patterns
- **[Sub-Workflow Composition](explanation/sub-workflows.md)** - Hierarchical workflows
- **[Zombie Workflow Recovery](explanation/zombie-recovery.md)** - Handling worker crashes
- **[Workflow Versioning](explanation/workflow-versioning.md)** - Definition snapshots

### Fintech, Edge & Self-Hosting
- **[Self-Hosting](explanation/self-hosting.md)** - Rufus orchestrates itself
- **[Edge Fintech Architecture](explanation/edge-architecture.md)** - POS terminals, ATMs
- **[Store-and-Forward](explanation/store-and-forward.md)** - Offline transaction handling
- **[Performance Model](explanation/performance.md)** - Throughput, latency, optimization

### History & Design
- **[Design Decisions](explanation/design-decisions.md)** - Why we chose this approach
- **[Confucius Heritage](explanation/confucius-heritage.md)** - Evolution from Confucius

---

## ⚡ [Advanced Topics](advanced/)

**For experienced users pushing Rufus to its limits**

- **[Custom Providers](advanced/custom-providers.md)** - Implement your own persistence/execution
- **[Executor Portability](advanced/executor-portability.md)** - ⚠️ Critical warnings about state management
- **[Dynamic Injection](advanced/dynamic-injection.md)** - ⚠️ Runtime step insertion (use cautiously)
- **[Security Considerations](advanced/security.md)** - PCI-DSS, encryption, input sanitization
- **[Resource Management](advanced/resource-management.md)** - Memory, connections, cleanup
- **[Extending Rufus](advanced/extending-rufus.md)** - Add new step types, observers

---

## 📚 [Appendices](appendices/)

- **[Glossary](appendices/glossary.md)** - Terms and definitions
- **[Changelog](appendices/changelog.md)** - Version history
- **[Roadmap](appendices/roadmap.md)** - Planned features
- **[Migration Notes](appendices/migration-notes.md)** - Breaking changes between versions
- **[Contributing](appendices/contributing.md)** - How to contribute to Rufus

---

## 🔗 Quick Links

- **[GitHub Repository](https://github.com/KamikaziD/rufus-sdk)**
- **[Examples](/examples/)** - Complete working examples
- **[Debug UI](/src/rufus_server/debug_ui/)** - Visual workflow inspection
- **[CLI Quick Reference](CLI_QUICK_REFERENCE.md)** - Common commands cheat sheet

---

## 🆘 Need Help?

- **New to workflows?** → Start with [Tutorials](tutorials/)
- **Building something?** → Check [How-To Guides](how-to-guides/)
- **Looking up syntax?** → See [Reference](reference/)
- **Curious how it works?** → Read [Explanation](explanation/)
- **Hitting limits?** → Explore [Advanced Topics](advanced/)

---

## About This Documentation

This documentation follows the [Diátaxis framework](https://diataxis.fr/) for systematic documentation organization. Each section serves a distinct purpose:

- **Tutorials** teach through hands-on lessons
- **How-To Guides** solve specific problems
- **Reference** provides technical accuracy
- **Explanation** builds understanding

**Last Updated:** 2026-02-24
**Rufus Version:** 0.5.0

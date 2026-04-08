# Explanation: Understanding Ruvon SDK

Explanation documents help you understand **why** and **how** Ruvon works. These are conceptual guides that build understanding, not step-by-step instructions.

## System Understanding

### [Architecture](architecture.md)
Learn how Ruvon is structured internally: the four-layer architecture (API, Engine, Persistence, Execution), component interactions, and deployment patterns.

**Read this when**: You want to understand the big picture.

### [Provider Pattern](provider-pattern.md)
Understand why Ruvon uses providers, what they abstract, and how to swap implementations (PostgreSQL ↔ SQLite, Celery ↔ ThreadPool).

**Read this when**: You want to customize Ruvon's behavior.

### [Design Decisions](design-decisions.md)
Discover why Ruvon is designed the way it is: YAML vs code-first, provider pattern vs monolithic, async/await vs callbacks, and more.

**Read this when**: You're wondering "why did they do it this way?"

## Workflow Concepts

### [Workflow Lifecycle](workflow-lifecycle.md)
Follow a workflow from creation to completion: all states (ACTIVE, PENDING_ASYNC, WAITING_HUMAN_INPUT, etc.), transitions, and what triggers them.

**Read this when**: You want to understand workflow state transitions.

### [State Management](state-management.md)
Learn how workflow state flows through the system: initialization, mutation, serialization, persistence, and loading.

**Read this when**: You're working with workflow state.

### [Saga Pattern](saga-pattern.md)
Understand distributed transaction compensation: why it's needed, how it works, compensation guarantees, and when to use it vs traditional transactions.

**Read this when**: You need to undo operations across multiple services.

## Advanced Features

### [Parallel Execution](parallel-execution.md)
Explore how Ruvon executes multiple tasks concurrently: merge strategies, conflict handling, partial success, and performance considerations.

**Read this when**: You want to speed up workflows with parallelism.

### [Sub-Workflows](sub-workflows.md)
Discover hierarchical workflow composition: parent-child relationships, status propagation, result merging, and nested sagas.

**Read this when**: You want to break complex workflows into reusable pieces.

### [Zombie Recovery](zombie-recovery.md)
Learn how Ruvon detects and recovers from worker crashes: heartbeat mechanism, detection thresholds, and deployment strategies.

**Read this when**: You need production reliability.

### [Workflow Versioning](workflow-versioning.md)
Understand definition snapshots: why they're needed, how they work, and strategies for deploying breaking changes safely.

**Read this when**: You're deploying new workflow versions.

## Specialized Topics

### [Edge Architecture](edge-architecture.md)
Explore offline-first workflows for fintech edge devices: POS terminals, ATMs, kiosks, store-and-forward, config push, and encryption.

**Read this when**: You're building workflows for offline devices.

### [Performance](performance.md)
Understand Ruvon's performance model: uvloop, orjson, connection pooling, import caching, benchmarks, and tuning guidelines.

**Read this when**: You need to optimize for throughput or latency.

### [Confucius Heritage](confucius-heritage.md)
Learn Ruvon's evolution from Confucius: what was preserved, what was improved, feature parity analysis, and migration guide.

**Read this when**: You're migrating from Confucius or curious about Ruvon's history.

## Reading Paths

### For New Users
1. [Architecture](architecture.md) - Get the big picture
2. [Workflow Lifecycle](workflow-lifecycle.md) - Understand states
3. [State Management](state-management.md) - Learn how data flows
4. [Provider Pattern](provider-pattern.md) - Understand pluggability

### For Production Deployments
1. [Performance](performance.md) - Optimize for your workload
2. [Zombie Recovery](zombie-recovery.md) - Handle worker crashes
3. [Workflow Versioning](workflow-versioning.md) - Deploy safely
4. [Design Decisions](design-decisions.md) - Understand trade-offs

### For Advanced Features
1. [Saga Pattern](saga-pattern.md) - Distributed compensation
2. [Parallel Execution](parallel-execution.md) - Concurrency patterns
3. [Sub-Workflows](sub-workflows.md) - Hierarchical composition

### For Edge Computing
1. [Edge Architecture](edge-architecture.md) - Offline-first design
2. [State Management](state-management.md) - Local persistence
3. [Performance](performance.md) - Optimize for resource constraints

### For Confucius Users
1. [Confucius Heritage](confucius-heritage.md) - What changed
2. [Provider Pattern](provider-pattern.md) - New architecture
3. [Design Decisions](design-decisions.md) - Why the refactor

## Explanation vs Other Docs

**Explanation** (this section):
- **Goal**: Build understanding
- **Audience**: Developers wanting to learn
- **Focus**: Concepts, "why", trade-offs
- **Example**: "How does the Saga pattern work?"

**How-to Guides** (`docs/how-to-guides/`):
- **Goal**: Solve specific problems
- **Audience**: Developers with tasks
- **Focus**: Step-by-step procedures
- **Example**: "How to deploy Ruvon to Kubernetes"

**Tutorials** (`docs/tutorials/`):
- **Goal**: Learn by doing
- **Audience**: Beginners
- **Focus**: Progressive lessons
- **Example**: "Build your first workflow"

**Reference** (`docs/reference/`):
- **Goal**: Lookup facts
- **Audience**: Developers needing details
- **Focus**: API docs, specifications
- **Example**: "PersistenceProvider API reference"

## Contributing

Found a concept that's unclear? Want to add an explanation?

1. Check if it fits: Does it explain "why" or "how", not "do this"?
2. Choose a topic: New document or expand existing?
3. Write clearly: Use examples, diagrams, analogies
4. Submit PR: Follow existing style

**Good topics**:
- Why Ruvon uses async/await
- How heartbeats detect zombies
- Trade-offs between PostgreSQL and SQLite

**Not explanation**:
- How to install Ruvon (tutorial)
- How to configure connection pool (how-to)
- PersistenceProvider API methods (reference)

## Feedback

Questions? Confusion? Let us know:
- GitHub Issues: https://github.com/your-org/ruvon/issues
- Discussions: https://github.com/your-org/ruvon/discussions

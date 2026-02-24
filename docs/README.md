# Rufus SDK Documentation

**Welcome to the Rufus SDK documentation!** This directory contains comprehensive documentation for building production workflows with Rufus.

---

## 🚀 Getting Started

**New to Rufus?** Start here:

1. **[Quickstart Guide](../QUICKSTART.md)** (5 minutes)
   - Install Rufus
   - Run your first workflow
   - Understand the basics

2. **[Usage Guide](../USAGE_GUIDE.md)**
   - Core concepts
   - Common patterns
   - Best practices

3. **[Example Workflows](../examples/)**
   - SQLite Task Manager (simple)
   - Loan Application (advanced)
   - API Integrations (FastAPI, Flask)

---

## 📚 Core Documentation

### For Daily Use

| Document | Description | When to Use |
|----------|-------------|-------------|
| **[USAGE_GUIDE.md](../USAGE_GUIDE.md)** | Core concepts and common patterns | Daily workflow development |
| **[YAML_GUIDE.md](../YAML_GUIDE.md)** | Complete YAML configuration reference | Writing workflow configs |
| **[CLI_REFERENCE.md](CLI_REFERENCE.md)** | All CLI commands with examples | Managing workflows via CLI |
| **[API_REFERENCE.md](../API_REFERENCE.md)** | Complete SDK API documentation | SDK integration, custom code |

### Feature Discovery

| Document | Description | When to Use |
|----------|-------------|-------------|
| **[FEATURES_AND_CAPABILITIES.md](FEATURES_AND_CAPABILITIES.md)** | Complete feature catalog | Discover what Rufus can do |
| **[OUTSTANDING_FEATURES.md](OUTSTANDING_FEATURES.md)** | Roadmap and planned features | See what's coming next |

---

## 🎓 Advanced Topics

### Advanced Guide
**[Coming Soon]** Deep technical documentation covering:
- Architecture internals
- Saga patterns & compensation
- Zombie recovery
- Workflow versioning
- Performance optimization
- Custom provider development
- Security considerations
- Production deployment

**Temporary:** See [CLAUDE.md](../CLAUDE.md) for advanced topics and [TECHNICAL_DOCUMENTATION.md](../TECHNICAL_DOCUMENTATION.md) for architecture details.

### Specialized Guides
*Planned for future releases:*
- Creating Custom Workflows
- Step Types Reference
- Saga Pattern Guide
- Parallel Execution Patterns
- Sub-Workflow Composition
- Human-in-the-Loop Workflows
- Polyglot Workflows (HTTP Steps)
- Custom Provider Development

---

## 🔧 Operations & Deployment

### Migration & Upgrades

| Document | Description |
|----------|-------------|
| **[MIGRATION_GUIDE.md](../MIGRATION_GUIDE.md)** | Migrating from Confucius or other workflow engines |
| **[UPGRADE_GUIDE.md](../UPGRADE_GUIDE.md)** | Upgrading between Rufus versions |

### Database & Schema

| Document | Description |
|----------|-------------|
| **[migrations/](../migrations/)** | Database schema migrations |
| **[CLI_REFERENCE.md](CLI_REFERENCE.md)** | Database management commands |

---

## 📖 Reference Documentation

### API & Configuration

| Document | Description |
|----------|-------------|
| **[API_REFERENCE.md](../API_REFERENCE.md)** | Complete Python SDK API |
| **[YAML_GUIDE.md](../YAML_GUIDE.md)** | YAML configuration syntax |
| **[CLI_REFERENCE.md](CLI_REFERENCE.md)** | Command-line interface reference |
| **[CLI_USAGE_GUIDE.md](CLI_USAGE_GUIDE.md)** | Detailed CLI usage guide |
| **[CLI_QUICK_REFERENCE.md](CLI_QUICK_REFERENCE.md)** | CLI cheat sheet |

### Internal Documentation

| Document | Description |
|----------|-------------|
| **[CLAUDE.md](../CLAUDE.md)** | Project instructions for AI assistants (contains advanced features) |
| **[GEMINI.md](../GEMINI.md)** | Project instructions for Gemini AI assistant |

---

## 📂 Examples

All examples are located in [../examples/](../examples/)

### Basic Examples

| Example | Description | Complexity |
|---------|-------------|------------|
| **[quickstart/](../examples/quickstart/)** | Simple greeting workflow | ⭐ Beginner |
| **[sqlite_task_manager/](../examples/sqlite_task_manager/)** | Task management with SQLite | ⭐ Beginner |

### Advanced Examples

| Example | Description | Complexity |
|---------|-------------|------------|
| **[loan_application/](../examples/loan_application/)** | Complex loan processing | ⭐⭐⭐ Advanced |
| **[fastapi_api/](../examples/fastapi_api/)** | FastAPI integration | ⭐⭐ Intermediate |
| **[flask_api/](../examples/flask_api/)** | Flask integration | ⭐⭐ Intermediate |
| **[javascript_steps/](../examples/javascript_steps/)** | Polyglot workflows (HTTP steps) | ⭐⭐ Intermediate |

---

## 🗺️ Documentation Roadmap

### ✅ Available Now (v0.5.0)
- Quickstart Guide
- Usage Guide
- YAML Reference
- CLI Reference
- API Reference
- Features & Capabilities catalog
- Changelog (v0.1.0 → v0.5.0)
- Migration notes (v0.4.x → v0.5.0)
- Working examples (6 examples)
- Diátaxis-structured documentation

### 🚧 In Progress
- Advanced Guide (comprehensive)
- Testing Guide
- Deployment Guide
- Performance Tuning Guide
- Troubleshooting Guide

### 📋 Planned
- Architecture documentation
- Step-by-step specialized guides
- Video tutorials
- Interactive documentation
- Industry-specific examples

---

## 🎯 Finding the Right Documentation

### "I want to..."

**...get started quickly**
→ [QUICKSTART.md](../QUICKSTART.md)

**...understand core concepts**
→ [USAGE_GUIDE.md](../USAGE_GUIDE.md)

**...write a workflow YAML file**
→ [YAML_GUIDE.md](../YAML_GUIDE.md)

**...use the CLI**
→ [CLI_REFERENCE.md](CLI_REFERENCE.md)

**...integrate Rufus into my app**
→ [API_REFERENCE.md](../API_REFERENCE.md)

**...see what Rufus can do**
→ [FEATURES_AND_CAPABILITIES.md](FEATURES_AND_CAPABILITIES.md)

**...know what's coming next**
→ [OUTSTANDING_FEATURES.md](OUTSTANDING_FEATURES.md)

**...implement advanced patterns**
→ [CLAUDE.md](../CLAUDE.md) (temporary, Advanced Guide coming soon)

**...deploy to production**
→ [CLAUDE.md](../CLAUDE.md) (Deployment Guide coming soon)

**...migrate from another system**
→ [MIGRATION_GUIDE.md](../MIGRATION_GUIDE.md)

**...see working code**
→ [examples/](../examples/)

---

## 🤝 Contributing to Documentation

Documentation improvements are welcome!

### How to Contribute

1. **Found an error?** Open an issue
2. **Have a suggestion?** Open a discussion
3. **Want to improve docs?** Submit a PR

### Documentation Standards

- **Clear and concise** - No jargon without explanation
- **Working examples** - All code snippets tested
- **Up-to-date** - Matches current version
- **Well-structured** - Easy to navigate
- **Actionable** - Tells readers what to do

---

## 📞 Getting Help

**Can't find what you need?**

- 💬 [GitHub Discussions](https://github.com/your-org/rufus-sdk/discussions) - Ask questions
- 🐛 [GitHub Issues](https://github.com/your-org/rufus-sdk/issues) - Report problems
- 📖 [Full Documentation](https://rufus-sdk.readthedocs.io) - Coming soon
- 💼 [Professional Support](mailto:support@rufus-sdk.dev) - Coming soon

---

## 📑 Documentation Index (Alphabetical)

### Root Directory
- [API_REFERENCE.md](../API_REFERENCE.md) - Complete Python SDK API
- [CLAUDE.md](../CLAUDE.md) - AI assistant project instructions (contains advanced features)
- [GEMINI.md](../GEMINI.md) - Gemini AI assistant instructions
- [MIGRATION_GUIDE.md](../MIGRATION_GUIDE.md) - Migration from other systems
- [QUICKSTART.md](../QUICKSTART.md) - 5-minute quick start guide
- [README.md](../README.md) - Main project readme
- [UPGRADE_GUIDE.md](../UPGRADE_GUIDE.md) - Version upgrade instructions
- [USAGE_GUIDE.md](../USAGE_GUIDE.md) - Core usage patterns
- [YAML_GUIDE.md](../YAML_GUIDE.md) - YAML configuration reference

### docs/ Directory (Current Location)
- [CLI_QUICK_REFERENCE.md](CLI_QUICK_REFERENCE.md) - CLI cheat sheet
- [CLI_REFERENCE.md](CLI_REFERENCE.md) - Complete CLI reference
- [CLI_USAGE_GUIDE.md](CLI_USAGE_GUIDE.md) - Detailed CLI guide
- [FEATURES_AND_CAPABILITIES.md](FEATURES_AND_CAPABILITIES.md) - Feature catalog
- [OUTSTANDING_FEATURES.md](OUTSTANDING_FEATURES.md) - Roadmap
- [README.md](README.md) - This file (documentation index)

### examples/ Directory
- [examples/README.md](../examples/README.md) - Coming soon
- [examples/quickstart/](../examples/quickstart/) - Basic workflow
- [examples/sqlite_task_manager/](../examples/sqlite_task_manager/) - SQLite example
- [examples/loan_application/](../examples/loan_application/) - Complex workflow
- [examples/fastapi_api/](../examples/fastapi_api/) - FastAPI integration
- [examples/flask_api/](../examples/flask_api/) - Flask integration
- [examples/javascript_steps/](../examples/javascript_steps/) - Polyglot workflows

### old_docs/ Directory
Historical documentation archived for reference:
- [old_docs/README.md](../old_docs/README.md) - Archive index

---

**Last Updated:** 2026-02-24
**Documentation Version:** 0.5.0

---

**Questions or suggestions?** Open an issue or discussion on GitHub!

# Contributing to Ruvon SDK

Thank you for your interest in contributing to Ruvon! This guide will help you get started.

---

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Ways to Contribute](#ways-to-contribute)
- [Development Setup](#development-setup)
- [Coding Standards](#coding-standards)
- [Testing Requirements](#testing-requirements)
- [Pull Request Process](#pull-request-process)
- [Commit Message Guidelines](#commit-message-guidelines)
- [Documentation](#documentation)
- [Release Process](#release-process)

---

## Code of Conduct

### Our Pledge

We are committed to providing a welcoming and inclusive environment for all contributors, regardless of background or identity.

### Expected Behavior

- Be respectful and considerate
- Welcome newcomers and help them get started
- Focus on constructive feedback
- Assume good intentions
- Respect differing viewpoints

### Unacceptable Behavior

- Harassment, discrimination, or personal attacks
- Trolling or inflammatory comments
- Publishing others' private information
- Spamming or off-topic discussions

### Reporting

If you experience or witness unacceptable behavior, please contact the maintainers at [conduct@ruvon-sdk.dev].

---

## Ways to Contribute

### 1. Report Bugs

**Found a bug?** Open a GitHub issue with:

- Clear, descriptive title
- Steps to reproduce
- Expected vs actual behavior
- Environment details (Python version, OS, database)
- Code samples or error messages

**Template:** Use the bug report template in GitHub Issues.

### 2. Request Features

**Have an idea?** Open a GitHub Discussion in the Ideas category:

- Describe your use case
- Explain why existing features don't work
- Propose a solution (optional)
- Consider backward compatibility

**Check first:** Review `/docs/appendices/roadmap.md` to see if it's planned.

### 3. Improve Documentation

**Documentation is code!** Contributions include:

- Fix typos or unclear explanations
- Add examples or tutorials
- Improve API documentation
- Create how-to guides
- Translate documentation

**Location:** All docs in `/docs/` directory.

### 4. Submit Code

**Ready to code?** Great! See development setup below.

**Good first issues:** Look for issues labeled `good-first-issue` on GitHub.

### 5. Review Pull Requests

**Help review code:**

- Test the changes locally
- Check for edge cases
- Verify documentation is updated
- Ensure tests pass
- Provide constructive feedback

---

## Development Setup

### Prerequisites

- Python 3.10+
- Git
- PostgreSQL 12+ (optional, for testing)
- Redis 6.0+ (optional, for Celery testing)

### Clone and Install

```bash
# Clone repository
git clone https://github.com/your-org/ruvon-sdk.git
cd ruvon-sdk

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install development dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt

# Install Ruvon in editable mode
pip install -e .

# Verify installation
ruvon --version
pytest --version
```

### Optional: Set Up Databases

**PostgreSQL:**

```bash
# Via Docker
docker run -d --name ruvon-postgres \
  -e POSTGRES_USER=ruvon \
  -e POSTGRES_PASSWORD=ruvon_secret_2024 \
  -e POSTGRES_DB=ruvon_cloud \
  -p 5433:5432 \
  postgres:14

# Apply migrations
export DATABASE_URL="postgresql://ruvon:ruvon_secret_2024@localhost:5433/ruvon_cloud"
cd src/ruvon
alembic upgrade head
cd ../..
```

**Redis (for Celery):**

```bash
docker run -d --name ruvon-redis -p 6379:6379 redis:7
```

### IDE Setup

**VS Code:**

1. Install Python extension
2. Select interpreter: `.venv/bin/python`
3. Install recommended extensions (`.vscode/extensions.json`)

**PyCharm:**

1. Open project
2. Configure interpreter: Settings → Project → Python Interpreter → `.venv`
3. Enable pytest: Settings → Tools → Python Integrated Tools → Testing → pytest

### Run Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=ruvon --cov-report=html

# Run specific test file
pytest tests/sdk/test_workflow.py

# Run with verbose output
pytest -v

# Run integration tests (requires PostgreSQL/Redis)
pytest -m integration
```

---

## Coding Standards

### Python Style

**Follow PEP 8** with these specifics:

- **Line length:** 100 characters (not 79)
- **Indentation:** 4 spaces (no tabs)
- **Quotes:** Double quotes for strings
- **Imports:** Grouped (stdlib, third-party, local) with blank lines between

**Example:**

```python
# Standard library
import asyncio
from typing import Dict, Optional

# Third-party
from pydantic import BaseModel

# Local imports
from ruvon.models import WorkflowStep, StepContext
from ruvon.providers.persistence import PersistenceProvider
```

### Type Hints

**Always use type hints:**

```python
def process_workflow(
    workflow_id: str,
    state: Dict[str, Any],
    context: StepContext
) -> Dict[str, Any]:
    """Process a workflow step.

    Args:
        workflow_id: Unique workflow identifier
        state: Current workflow state
        context: Step execution context

    Returns:
        Updated state dictionary
    """
    pass
```

### Documentation

**Docstrings required for:**

- All public functions and methods
- All classes
- All modules

**Format:** Google-style docstrings:

```python
def calculate_metrics(workflow_id: str, detailed: bool = False) -> Dict[str, float]:
    """Calculate performance metrics for a workflow.

    Args:
        workflow_id: Unique workflow identifier
        detailed: If True, include per-step metrics

    Returns:
        Dictionary mapping metric names to values

    Raises:
        ValueError: If workflow_id is invalid
        WorkflowNotFoundError: If workflow doesn't exist

    Example:
        >>> metrics = calculate_metrics("wf-123", detailed=True)
        >>> print(metrics['total_duration'])
        45.2
    """
    pass
```

### Code Quality Tools

**We use:**

- **black** - Code formatting (line length 100)
- **isort** - Import sorting
- **flake8** - Linting
- **mypy** - Type checking
- **pylint** - Additional linting

**Run before committing:**

```bash
# Format code
black src/ tests/ --line-length 100
isort src/ tests/

# Check code quality
flake8 src/ tests/
mypy src/
pylint src/ruvon/
```

**Pre-commit hooks** (recommended):

```bash
pip install pre-commit
pre-commit install
```

---

## Testing Requirements

### Test Coverage

**Minimum coverage: 80%** for new code.

```bash
# Check coverage
pytest --cov=ruvon --cov-report=term-missing
```

### Test Types

**1. Unit Tests**

Test individual functions/classes in isolation:

```python
def test_workflow_initialization():
    """Test workflow creates with correct initial state."""
    workflow = Workflow(
        workflow_type="TestWorkflow",
        initial_data={"user_id": "123"}
    )
    assert workflow.state.user_id == "123"
    assert workflow.status == WorkflowStatus.PENDING
```

**2. Integration Tests**

Test multiple components together:

```python
@pytest.mark.integration
async def test_workflow_execution_with_postgres(postgres_persistence):
    """Test complete workflow execution with PostgreSQL."""
    builder = WorkflowBuilder(
        config_dir="config/",
    )
    workflow = await builder.create_workflow(
        workflow_type="TestWorkflow",
        persistence_provider=postgres_persistence,
        workflow_builder=builder,
        initial_data={"user_id": "123"},
    )
    await workflow.next_step(user_input={})
    assert workflow.status == WorkflowStatus.COMPLETED
```

**3. End-to-End Tests**

Test complete user scenarios:

```python
@pytest.mark.e2e
def test_cli_workflow_lifecycle():
    """Test complete workflow lifecycle via CLI."""
    result = subprocess.run(["ruvon", "start", "TestWorkflow", "--data", '{"user_id":"123"}'])
    assert result.returncode == 0
    # ... test resume, show, logs, cancel ...
```

### Testing Best Practices

- **Use fixtures** for common setup
- **Isolate tests** - no shared state between tests
- **Test edge cases** - empty inputs, None values, errors
- **Use descriptive names** - `test_workflow_fails_when_step_raises_exception`
- **Keep tests focused** - one concept per test
- **Mock external services** - no real API calls in tests

### Fixtures

**Common fixtures** (`conftest.py`):

```python
@pytest.fixture
async def in_memory_persistence():
    """Provide in-memory persistence for testing."""
    from ruvon.implementations.persistence.memory import InMemoryPersistenceProvider
    provider = InMemoryPersistenceProvider()
    await provider.initialize()
    yield provider
    await provider.close()

@pytest.fixture
def test_harness(in_memory_persistence):
    """Provide TestHarness with in-memory backend."""
    return TestHarness(persistence=in_memory_persistence)
```

---

## Pull Request Process

### Before Submitting

**Checklist:**

- [ ] Tests pass locally (`pytest`)
- [ ] Code formatted (`black`, `isort`)
- [ ] Linting passes (`flake8`, `mypy`)
- [ ] Documentation updated
- [ ] Changelog updated (if user-facing change)
- [ ] Commit messages follow guidelines
- [ ] Branch is up-to-date with main

### Create Pull Request

1. **Fork the repository** (first-time contributors)
2. **Create a branch** from `main`:
   ```bash
   git checkout -b feature/my-new-feature
   ```
3. **Make your changes** with frequent commits
4. **Push to your fork**:
   ```bash
   git push origin feature/my-new-feature
   ```
5. **Open pull request** on GitHub
6. **Fill out PR template** completely

### PR Title Format

```
<type>(<scope>): <short description>

Examples:
feat(cli): add workflow replay command
fix(postgres): handle null workflow_version
docs(tutorial): add FastAPI integration guide
test(sdk): add tests for loop step edge cases
```

**Types:**
- `feat` - New feature
- `fix` - Bug fix
- `docs` - Documentation only
- `test` - Test additions or fixes
- `refactor` - Code restructuring (no behavior change)
- `perf` - Performance improvement
- `chore` - Build/tooling changes

### PR Description

**Include:**

- **Summary:** What does this PR do?
- **Motivation:** Why is this change needed?
- **Changes:** List of specific changes
- **Testing:** How did you test this?
- **Breaking changes:** Any backwards-incompatible changes?
- **Related issues:** Fixes #123, Relates to #456

### Review Process

**What to expect:**

1. **Automated checks** - CI/CD runs tests, linting
2. **Maintainer review** - Usually within 48 hours
3. **Feedback** - Constructive suggestions for improvement
4. **Iteration** - Make requested changes
5. **Approval** - At least one maintainer approval required
6. **Merge** - Maintainer merges when ready

**Responding to feedback:**

- Be respectful and professional
- Ask questions if feedback is unclear
- Make requested changes promptly
- Explain reasoning if you disagree (politely)

---

## Commit Message Guidelines

### Format

```
<type>(<scope>): <subject>

<body>

<footer>
```

### Examples

**Simple commit:**
```
fix(cli): correct workflow ID parsing in show command
```

**Detailed commit:**
```
feat(postgres): add connection pooling configuration

Allow users to configure PostgreSQL connection pool size
via environment variables or constructor parameters.

Default pool size increased to 10 min, 50 max for better
performance under load.

Fixes #234
```

**Breaking change:**
```
feat(providers)!: rename PersistenceProvider methods

BREAKING CHANGE: Renamed save_workflow to persist_workflow
for consistency with other provider methods.

Migration:
- Replace persistence.save_workflow() with persistence.persist_workflow()
- No other changes required
```

### Rules

- **Subject line:** Max 72 characters
- **Body:** Wrap at 72 characters
- **Imperative mood:** "Add feature" not "Added feature"
- **Reference issues:** Include issue numbers in footer
- **Breaking changes:** Use `!` or `BREAKING CHANGE:` in footer

---

## Documentation

### Types of Documentation

**1. Code Documentation**
- Docstrings in Python code
- Type hints for all functions
- Inline comments for complex logic

**2. User Guides** (`/docs/`)
- Tutorials (learning-oriented)
- How-to guides (problem-oriented)
- Explanations (understanding-oriented)
- Reference (information-oriented)

**3. API Reference**
- Auto-generated from docstrings
- Class and method documentation
- Parameter descriptions

### Writing Good Documentation

**Principles:**

- **Clear and concise** - No jargon unless necessary
- **Examples** - Show, don't just tell
- **Up-to-date** - Update docs with code changes
- **Tested** - Verify examples actually work
- **Accessible** - Assume minimal background knowledge

**Structure:**

```markdown
# Feature Name

Brief description of what it does and why it's useful.

## When to Use

When you need to...

## Basic Usage

```python
# Simple example
from ruvon import ...
```

## Advanced Usage

More complex examples...

## Configuration

Available options...

## Troubleshooting

Common issues and solutions...
```

### Updating Documentation

**When to update:**

- Adding a new feature → Add how-to guide
- Changing API → Update reference docs
- Fixing a bug → Update troubleshooting section
- Deprecating feature → Add deprecation notice

**Where to update:**

- User-facing changes → `/docs/`
- Code documentation → Docstrings
- Breaking changes → `/docs/appendices/migration-notes.md`
- New features → `/docs/appendices/changelog.md`

---

## Release Process

### Versioning

**We follow semantic versioning:**

- **Major (X.0.0):** Breaking changes
- **Minor (0.X.0):** New features, backwards compatible
- **Patch (0.0.X):** Bug fixes, backwards compatible

### Release Checklist

**For maintainers only:**

1. **Update version** in `pyproject.toml`
2. **Update changelog** with release date
3. **Create git tag:** `git tag -a v0.3.0 -m "Release 0.3.0"`
4. **Push tag:** `git push origin v0.3.0`
5. **Build package:** `python -m build`
6. **Upload to PyPI:** `twine upload dist/*`
7. **Create GitHub release** with changelog
8. **Announce** in Discussions

---

## Getting Help

**Questions about contributing?**

- 💬 [GitHub Discussions](https://github.com/your-org/ruvon-sdk/discussions)
- 📖 [Development Docs](/docs/)
- 🐛 [Report Issues](https://github.com/your-org/ruvon-sdk/issues)

**Want to chat?**

- Join our Slack (coming soon)
- Attend community calls (schedule TBD)

---

## Recognition

**We appreciate all contributions!**

- All contributors listed in `CONTRIBUTORS.md`
- Significant contributions mentioned in release notes
- Top contributors featured on website (coming soon)

---

## License

By contributing to Ruvon SDK, you agree that your contributions will be licensed under the MIT License.

---

**Thank you for contributing to Ruvon!**

Your time and expertise help make Ruvon better for everyone. We look forward to working with you!

---

**Last Updated:** 2026-02-13

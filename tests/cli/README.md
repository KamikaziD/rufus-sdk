# Ruvon CLI Tests

Comprehensive tests for the Ruvon CLI tool covering all 21+ commands across 4 command groups.

## Overview

The Ruvon CLI has the following command structure:

**Config Commands** (`ruvon config *`):
- `show` - Display current configuration
- `set-persistence` - Configure persistence provider (SQLite/PostgreSQL/memory)
- `set-execution` - Configure execution provider (sync/thread_pool/celery)
- `set-default` - Set default behaviors
- `reset` - Reset configuration to defaults
- `path` - Show configuration file path

**Workflow Commands** (`ruvon workflow *` or top-level aliases):
- `list` - List workflows with filtering
- `start` - Start new workflow
- `show` - Show workflow details
- `resume` - Resume paused workflow
- `retry` - Retry failed workflow
- `logs` - View execution logs
- `metrics` - View performance metrics
- `cancel` - Cancel running workflow

**Database Commands** (`ruvon db *`):
- `init` - Initialize database schema
- `migrate` - Apply database migrations
- `status` - Show migration status
- `validate` - Validate schema
- `stats` - Show database statistics

**Top-Level Commands**:
- `validate` - Validate workflow YAML
- `run` - Run workflow locally (in-memory)
- `scan-zombies` - Scan for zombie workflows
- `zombie-daemon` - Run zombie scanner as daemon

## Running Tests

```bash
# Run all CLI tests
pytest tests/cli/

# Run specific test file
pytest tests/cli/test_config_cmd.py

# Run with verbose output
pytest tests/cli/ -v

# Run with coverage
pytest tests/cli/ --cov=ruvon_cli --cov-report=html

# Run single test
pytest tests/cli/test_config_cmd.py::TestConfigShow::test_config_show_default

# Skip integration tests (faster)
pytest tests/cli/ -m "not integration"
```

## Test Structure

```
tests/cli/
├── conftest.py                  # Shared fixtures and test utilities
├── utils.py                     # Test helper functions
├── test_config_cmd.py           # Config commands (6 commands)
├── test_workflow_cmd.py         # Workflow commands (8 commands)
├── test_db_cmd.py               # Database commands (5 commands)
├── test_validate_and_run.py     # Validation and run commands
├── test_zombie_commands.py      # Zombie scanner commands
├── test_cli_integration.py      # End-to-end integration tests
└── README.md                    # This file
```

## Test Categories

### Unit Tests

Test individual commands in isolation with mocked dependencies:

- **test_config_cmd.py**: Config file operations, argument parsing
- **test_workflow_cmd.py**: Workflow command argument handling, output formatting
- **test_db_cmd.py**: Database command structure and arguments
- **test_validate_and_run.py**: YAML validation, local execution setup
- **test_zombie_commands.py**: Zombie scanner argument parsing

**Characteristics**:
- Fast execution (< 1 second per test)
- Mock persistence, execution, and observer providers
- Test CLI argument parsing and error handling
- Isolated from database and external dependencies

### Integration Tests

Test end-to-end workflows with real SQLite databases:

- **test_cli_integration.py**: Complete workflow lifecycles

**Characteristics**:
- Slower execution (acceptable for integration tests)
- Use real SQLite in-memory or temporary file databases
- Validate complete user scenarios
- Test interaction between multiple commands

## Fixtures

### Core Fixtures (conftest.py)

- `cli_runner` - CliRunner for invoking Typer commands
- `temp_config_dir` - Temporary `.ruvon` config directory
- `temp_db` - Temporary SQLite database path
- `initialized_db` - SQLite database with schema initialized
- `sample_config` - Pre-configured config file
- `sample_workflow_yaml` - Test workflow YAML file
- `sample_workflow_registry` - Test workflow registry
- `sample_workflow_data` - Mock workflow data dict

### Mock Fixtures

- `mock_persistence` - AsyncMock persistence provider
- `mock_execution` - Mock execution provider
- `mock_observer` - Mock observer

### Auto-used Fixtures

- `set_test_config_path` - Automatically sets `RUVON_CONFIG_DIR` env var

## Testing Patterns

### Pattern 1: Basic Command Invocation

```python
def test_config_show(cli_runner):
    result = cli_runner.invoke(app, ["config", "show"])

    assert result.exit_code == 0
    assert "persistence" in result.stdout
```

### Pattern 2: Command with Mocked Provider

```python
def test_list_workflows(cli_runner, mock_persistence):
    mock_persistence.list_workflows.return_value = []

    with patch('ruvon_cli.providers.create_persistence_provider', return_value=mock_persistence):
        result = cli_runner.invoke(app, ["list"])

    assert result.exit_code == 0
```

### Pattern 3: JSON Output Validation

```python
def test_list_json_output(cli_runner, mock_persistence):
    mock_persistence.list_workflows.return_value = [...]

    with patch('ruvon_cli.providers.create_persistence_provider', return_value=mock_persistence):
        result = cli_runner.invoke(app, ["list", "--json"])

    workflows = json.loads(result.stdout)
    assert isinstance(workflows, list)
```

### Pattern 4: Config File Verification

```python
def test_config_save(cli_runner, temp_config_dir):
    result = cli_runner.invoke(app, ["config", "set-persistence", "--provider", "sqlite", "--yes"])

    assert result.exit_code == 0

    config_file = temp_config_dir / "config.yaml"
    assert config_file.exists()

    with open(config_file) as f:
        config = yaml.safe_load(f)
    assert config["persistence"]["provider"] == "sqlite"
```

## Test Coverage Goals

| Component | Target Coverage | Status |
|-----------|----------------|--------|
| Config Commands | 90%+ | ✅ Tests written |
| Workflow Commands | 80%+ | ⚠️ Partial (some features incomplete) |
| Database Commands | 70%+ | ⚠️ Basic tests (needs integration) |
| Validate/Run Commands | 80%+ | ⚠️ Basic tests (needs execution) |
| Zombie Commands | 70%+ | ⚠️ Basic tests (daemon needs special handling) |
| **Overall CLI** | **85%+** | 🚧 In progress |

## Common Testing Challenges

### Challenge 1: Incomplete CLI Features

**Issue**: Some commands (resume, retry, cancel) show warnings that they're incomplete.

**Solution**: Mark tests with `@pytest.mark.skip(reason="Feature not fully implemented")`

Example:
```python
@pytest.mark.skip(reason="Resume functionality not fully implemented")
def test_resume_workflow(cli_runner):
    pass
```

### Challenge 2: Database-Dependent Tests

**Issue**: Database commands require initialized schema.

**Solution**: Use `initialized_db` fixture or skip tests requiring full database setup.

### Challenge 3: Daemon Processes

**Issue**: `zombie-daemon` runs indefinitely, hard to test.

**Solution**: Test argument parsing only, skip actual daemon execution.

### Challenge 4: Provider Mocking

**Issue**: Need to mock persistence/execution providers without breaking CLI logic.

**Solution**: Use `unittest.mock.patch` on provider factory functions.

## Adding New Tests

To add tests for a new CLI command:

1. **Identify the command group**: config, workflow, db, or top-level
2. **Add test class** to appropriate test file:
   ```python
   class TestNewCommand:
       """Tests for 'ruvon new-command' command."""

       def test_new_command_basic(self, cli_runner):
           result = cli_runner.invoke(app, ["new-command"])
           assert result.exit_code == 0
   ```

3. **Test variations**:
   - Basic execution (no arguments)
   - With arguments/flags
   - JSON output (if applicable)
   - Error cases (invalid arguments, missing files, etc.)

4. **Add integration test** if command interacts with multiple components

5. **Update this README** with new command documentation

## CI/CD Integration

These tests are designed to run in CI/CD pipelines:

```bash
# Install dependencies
pip install -r requirements.txt

# Run tests with coverage
pytest tests/cli/ --cov=ruvon_cli --cov-report=xml --cov-report=term

# Check coverage threshold
pytest tests/cli/ --cov=ruvon_cli --cov-fail-under=80
```

## Troubleshooting

### Tests fail with "config file not found"

**Cause**: `set_test_config_path` fixture not applied.

**Fix**: Ensure `conftest.py` is in the test directory and fixture is `autouse=True`.

### Tests fail with "table not found"

**Cause**: Database schema not initialized.

**Fix**: Use `initialized_db` fixture instead of `temp_db`.

### Tests hang or timeout

**Cause**: Daemon processes or async operations not properly cleaned up.

**Fix**: Use `skip` marker for daemon tests or add proper cleanup/teardown.

### Mock not working

**Cause**: Mocking wrong import path.

**Fix**: Patch the factory function where it's used, not where it's defined:
```python
# ✅ Correct
with patch('ruvon_cli.providers.create_persistence_provider', return_value=mock):

# ❌ Wrong
with patch('ruvon.implementations.persistence.sqlite.SQLitePersistenceProvider', return_value=mock):
```

## Example Test Run Output

```
$ pytest tests/cli/ -v

tests/cli/test_config_cmd.py::TestConfigShow::test_config_show_default PASSED
tests/cli/test_config_cmd.py::TestConfigShow::test_config_show_with_file PASSED
tests/cli/test_config_cmd.py::TestConfigShow::test_config_show_json_output PASSED
...
tests/cli/test_workflow_cmd.py::TestWorkflowList::test_list_empty PASSED
tests/cli/test_workflow_cmd.py::TestWorkflowList::test_list_with_workflows PASSED
...

======================== 45 passed, 12 skipped in 5.32s =========================
```

## Next Steps

- [ ] Complete integration tests for workflow lifecycle
- [ ] Add tests for database migration commands
- [ ] Test zombie scanner with real workflow crashes
- [ ] Add performance benchmarks for CLI commands
- [ ] Create snapshot tests for CLI output formatting
- [ ] Test CLI with PostgreSQL (integration tests)

## Resources

- [Typer Testing Docs](https://typer.tiangolo.com/tutorial/testing/)
- [pytest Documentation](https://docs.pytest.org/)
- [pytest-mock](https://pytest-mock.readthedocs.io/)
- [Ruvon CLI Source](../../src/ruvon_cli/)
- [Ruvon SDK Tests](../sdk/) - Good patterns for async testing

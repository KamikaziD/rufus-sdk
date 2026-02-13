# How to test workflows

This guide covers testing Rufus workflows with the TestHarness and pytest.

## Overview

Rufus provides a TestHarness for writing fast, deterministic workflow tests. It uses in-memory persistence and synchronous execution.

## Basic workflow test

### Using TestHarness

```python
import pytest
from rufus.testing.harness import TestHarness

@pytest.mark.asyncio
async def test_simple_workflow():
    """Test basic workflow execution."""

    # Create test harness (in-memory, synchronous)
    harness = TestHarness()

    # Start workflow
    workflow = await harness.start_workflow(
        workflow_type="OrderProcessing",
        initial_data={
            "order_id": "ORD-001",
            "customer_id": "CUST-123",
            "amount": 99.99
        }
    )

    # Verify initial state
    assert workflow.status == "ACTIVE"
    assert workflow.state.order_id == "ORD-001"

    # Execute first step
    result = await harness.next_step(workflow.id)

    # Verify step result
    assert result["step_completed"] == True

    # Execute remaining steps
    while workflow.status == "ACTIVE":
        await harness.next_step(workflow.id)

    # Verify final state
    assert workflow.status == "COMPLETED"
    assert workflow.state.payment_id is not None
```

## Test structure

### Organize test files

```
tests/
├── conftest.py              # Shared fixtures
├── test_order_workflow.py   # Order processing tests
├── test_loan_workflow.py    # Loan application tests
└── integration/
    └── test_celery.py       # Integration tests
```

### Setup fixtures

```python
# tests/conftest.py
import pytest
from rufus.testing.harness import TestHarness
from rufus.implementations.persistence.sqlite import SQLitePersistenceProvider
from rufus.implementations.execution.sync import SyncExecutionProvider

@pytest.fixture
async def harness():
    """Create test harness for each test."""
    test_harness = TestHarness()
    yield test_harness
    # Cleanup handled by in-memory database

@pytest.fixture
async def persistence():
    """Create in-memory persistence provider."""
    provider = SQLitePersistenceProvider(db_path=":memory:")
    await provider.initialize()
    yield provider
    await provider.close()

@pytest.fixture
def execution():
    """Create synchronous execution provider."""
    return SyncExecutionProvider()
```

## Testing step functions

### Unit test step functions

```python
import pytest
from rufus.models import StepContext
from my_app.state_models import OrderState
from my_app.steps import validate_order

def test_validate_order():
    """Test order validation step."""

    # Create state
    state = OrderState(
        order_id="ORD-001",
        customer_id="CUST-123",
        amount=150.00
    )

    # Create context
    context = StepContext(
        workflow_id="test-workflow-id",
        step_name="Validate_Order",
        previous_step_result=None
    )

    # Execute step
    result = validate_order(state, context)

    # Verify result
    assert result["validated"] == True
    assert state.status == "validated"

def test_validate_order_negative_amount():
    """Test validation with invalid amount."""

    state = OrderState(
        order_id="ORD-002",
        customer_id="CUST-123",
        amount=-10.00  # Invalid
    )

    context = StepContext(
        workflow_id="test-workflow-id",
        step_name="Validate_Order"
    )

    # Should raise exception
    with pytest.raises(ValueError, match="amount must be positive"):
        validate_order(state, context)
```

## Testing decision steps

### Test routing conditions

```python
@pytest.mark.asyncio
async def test_high_value_routing():
    """Test high-value order routing."""

    harness = TestHarness()

    workflow = await harness.start_workflow(
        workflow_type="OrderProcessing",
        initial_data={
            "order_id": "ORD-001",
            "amount": 15000  # High value
        }
    )

    # Execute decision step
    await harness.next_step(workflow.id)

    # Should route to manual approval
    assert workflow.current_step == "Manual_Approval"

@pytest.mark.asyncio
async def test_standard_value_routing():
    """Test standard-value order routing."""

    harness = TestHarness()

    workflow = await harness.start_workflow(
        workflow_type="OrderProcessing",
        initial_data={
            "order_id": "ORD-002",
            "amount": 99.99  # Standard value
        }
    )

    await harness.next_step(workflow.id)

    # Should route to auto-process
    assert workflow.current_step == "Auto_Process"
```

## Testing human-in-the-loop

### Test pause and resume

```python
@pytest.mark.asyncio
async def test_approval_workflow():
    """Test workflow pause and resume."""

    harness = TestHarness()

    workflow = await harness.start_workflow(
        workflow_type="OrderProcessing",
        initial_data={"order_id": "ORD-001"}
    )

    # Execute until pause
    await harness.next_step(workflow.id)

    # Should be waiting for input
    assert workflow.status == "WAITING_HUMAN_INPUT"

    # Resume with approval
    await harness.next_step(
        workflow.id,
        user_input={
            "approved": True,
            "approved_by": "test@example.com"
        }
    )

    # Should continue
    assert workflow.status == "ACTIVE"
    assert workflow.state.approved == True

@pytest.mark.asyncio
async def test_rejection_workflow():
    """Test workflow rejection."""

    harness = TestHarness()

    workflow = await harness.start_workflow(
        workflow_type="OrderProcessing",
        initial_data={"order_id": "ORD-002"}
    )

    await harness.next_step(workflow.id)

    # Resume with rejection
    await harness.next_step(
        workflow.id,
        user_input={
            "approved": False,
            "rejection_reason": "Invalid customer"
        }
    )

    # Should handle rejection
    assert workflow.state.approved == False
```

## Testing saga mode

### Test compensation

```python
@pytest.mark.asyncio
async def test_saga_compensation():
    """Test saga rollback on failure."""

    harness = TestHarness()

    workflow = await harness.start_workflow(
        workflow_type="OrderProcessing",
        initial_data={
            "order_id": "ORD-001",
            "customer_id": "CUST-123",
            "amount": 99.99
        }
    )

    # Enable saga mode
    workflow.enable_saga_mode()

    # Mock service to fail at shipping
    from unittest.mock import patch

    with patch('my_app.services.shipping_service.ship') as mock_ship:
        mock_ship.side_effect = Exception("Shipping unavailable")

        # Execute workflow - should fail and compensate
        with pytest.raises(Exception):
            while workflow.status == "ACTIVE":
                await harness.next_step(workflow.id)

    # Verify compensation ran
    assert workflow.status == "FAILED_ROLLED_BACK"
    assert workflow.state.inventory_reserved == False
    assert workflow.state.refund_id is not None
```

## Mocking external services

### Mock HTTP calls

```python
@pytest.mark.asyncio
async def test_http_step():
    """Test HTTP step with mocked service."""

    harness = TestHarness()

    # Mock HTTP response
    from unittest.mock import Mock, patch

    mock_response = {
        "status": "success",
        "result": "processed"
    }

    with patch('aiohttp.ClientSession.post') as mock_post:
        mock_post.return_value.__aenter__.return_value.json.return_value = mock_response

        workflow = await harness.start_workflow(
            workflow_type="PolyglotPipeline",
            initial_data={"user_id": "123"}
        )

        await harness.next_step(workflow.id)

        assert workflow.state.service_response == mock_response
```

### Mock database calls

```python
@pytest.mark.asyncio
async def test_database_step():
    """Test step with mocked database."""

    from unittest.mock import AsyncMock, patch

    mock_user = {
        "id": "123",
        "name": "John Doe",
        "email": "john@example.com"
    }

    with patch('my_app.database.get_user', new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_user

        harness = TestHarness()

        workflow = await harness.start_workflow(
            workflow_type="UserOnboarding",
            initial_data={"user_id": "123"}
        )

        await harness.next_step(workflow.id)

        assert workflow.state.user_name == "John Doe"
```

## Testing parallel steps

### Test parallel execution

```python
@pytest.mark.asyncio
async def test_parallel_steps():
    """Test parallel step execution."""

    harness = TestHarness()

    workflow = await harness.start_workflow(
        workflow_type="RiskAssessment",
        initial_data={"application_id": "APP-001"}
    )

    # Execute parallel step
    await harness.next_step(workflow.id)

    # Verify all parallel tasks completed
    assert workflow.state.credit_check_complete == True
    assert workflow.state.fraud_check_complete == True
    assert workflow.state.income_verification_complete == True
```

## Testing error handling

### Test failure scenarios

```python
@pytest.mark.asyncio
async def test_workflow_failure():
    """Test workflow failure handling."""

    harness = TestHarness()

    workflow = await harness.start_workflow(
        workflow_type="OrderProcessing",
        initial_data={
            "order_id": "ORD-001",
            "amount": -100  # Invalid amount
        }
    )

    # Should fail validation
    with pytest.raises(ValueError):
        await harness.next_step(workflow.id)

    # Workflow should be marked as failed
    assert workflow.status == "FAILED"

@pytest.mark.asyncio
async def test_retryable_errors():
    """Test retry logic for transient errors."""

    from unittest.mock import Mock, patch

    harness = TestHarness()

    workflow = await harness.start_workflow(
        workflow_type="OrderProcessing",
        initial_data={"order_id": "ORD-001"}
    )

    # Mock service to fail twice, then succeed
    call_count = 0

    def mock_payment_service(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise Exception("Temporary failure")
        return "PAYMENT-123"

    with patch('my_app.services.payment_service.charge', side_effect=mock_payment_service):
        # Execute with retry logic
        # ... test retry behavior ...
        pass
```

## Testing state persistence

### Test state serialization

```python
@pytest.mark.asyncio
async def test_state_persistence():
    """Test workflow state persistence."""

    harness = TestHarness()

    # Create workflow
    workflow = await harness.start_workflow(
        workflow_type="OrderProcessing",
        initial_data={"order_id": "ORD-001"}
    )

    workflow_id = workflow.id

    # Execute first step
    await harness.next_step(workflow_id)

    # Reload workflow
    reloaded = await harness.load_workflow(workflow_id)

    # State should be preserved
    assert reloaded.state.order_id == "ORD-001"
    assert reloaded.current_step == workflow.current_step
```

## Performance testing

### Benchmark workflow execution

```python
import time
import pytest

@pytest.mark.asyncio
async def test_workflow_performance():
    """Benchmark workflow execution time."""

    harness = TestHarness()

    start_time = time.time()

    # Execute 100 workflows
    for i in range(100):
        workflow = await harness.start_workflow(
            workflow_type="OrderProcessing",
            initial_data={"order_id": f"ORD-{i:03d}"}
        )

        while workflow.status == "ACTIVE":
            await harness.next_step(workflow.id)

    elapsed = time.time() - start_time

    # Should complete in reasonable time
    assert elapsed < 10.0  # 10 seconds for 100 workflows
    print(f"Executed 100 workflows in {elapsed:.2f}s")
```

## Integration testing

### Test with PostgreSQL

```python
import pytest
from rufus.implementations.persistence.postgres import PostgresPersistenceProvider
from rufus.implementations.execution.sync import SyncExecutionProvider
from rufus.builder import WorkflowBuilder

@pytest.mark.integration
@pytest.mark.asyncio
async def test_postgres_workflow():
    """Integration test with PostgreSQL."""

    # Use test database
    persistence = PostgresPersistenceProvider(
        db_url="postgresql://rufus:rufus_secret_2024@localhost:5433/rufus_test"
    )
    await persistence.initialize()

    execution = SyncExecutionProvider()

    builder = WorkflowBuilder(
        config_dir="config/",
        persistence_provider=persistence,
        execution_provider=execution
    )

    # Create workflow
    workflow = await builder.create_workflow(
        workflow_type="OrderProcessing",
        initial_data={"order_id": "ORD-001"}
    )

    # Execute
    await workflow.next_step()

    # Verify persisted to database
    loaded = await persistence.load_workflow(workflow.id)
    assert loaded['state']['order_id'] == "ORD-001"

    await persistence.close()
```

### Test with Celery

See TESTING_GUIDE.md for Celery integration testing setup.

## Test data factories

### Create reusable test data

```python
# tests/factories.py
from my_app.state_models import OrderState

class OrderFactory:
    """Factory for creating test orders."""

    @staticmethod
    def create_standard_order(**kwargs):
        """Create standard order for testing."""
        defaults = {
            "order_id": "ORD-001",
            "customer_id": "CUST-123",
            "amount": 99.99,
            "items": [{"id": "ITEM-1", "quantity": 1}]
        }
        defaults.update(kwargs)
        return defaults

    @staticmethod
    def create_high_value_order(**kwargs):
        """Create high-value order for testing."""
        defaults = OrderFactory.create_standard_order()
        defaults["amount"] = 15000
        defaults.update(kwargs)
        return defaults

# Use in tests
@pytest.mark.asyncio
async def test_with_factory():
    harness = TestHarness()

    workflow = await harness.start_workflow(
        workflow_type="OrderProcessing",
        initial_data=OrderFactory.create_standard_order()
    )
```

## Best practices

1. **Use TestHarness for unit tests** - Fast, deterministic, in-memory
2. **Test all routing paths** - Cover every decision branch
3. **Mock external services** - Avoid dependencies in tests
4. **Test error scenarios** - Verify failure handling
5. **Use fixtures** - Share setup code across tests
6. **Test state persistence** - Verify serialization works
7. **Separate unit and integration** - Mark integration tests with `@pytest.mark.integration`
8. **Test idempotency** - Verify steps can be retried safely

## Running tests

### Run all tests

```bash
pytest
```

### Run specific test file

```bash
pytest tests/test_order_workflow.py
```

### Run single test

```bash
pytest tests/test_order_workflow.py::test_simple_workflow
```

### Run with coverage

```bash
pytest --cov=rufus --cov-report=html
```

### Run integration tests only

```bash
pytest -m integration
```

### Run with verbose output

```bash
pytest -v -s
```

## Next steps

- [Deploy to production](deployment.md)
- [Configure monitoring](troubleshooting.md)
- [Optimize performance](configuration.md)

## See also

- [Create workflow guide](create-workflow.md)
- [Configuration guide](configuration.md)
- TESTING_GUIDE.md for Celery testing
- USAGE_GUIDE.md section 11 for testing patterns

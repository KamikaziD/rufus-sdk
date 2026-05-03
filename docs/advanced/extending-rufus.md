# Advanced: Extending Ruvon

Guide to adding new capabilities to Ruvon: custom step types, observers, custom database tables, custom API routes, plugins, and contributing back to the project.

---

## Extending the Database Schema

Ruvon's PostgreSQL schema is defined in `src/ruvon/db_schema/database.py` using SQLAlchemy. All 33 cloud tables share a single `metadata` object, which means you can add your own tables and have them managed by Alembic alongside the core tables.

### Adding Custom Tables

```python
# myapp/schema.py
from ruvon.db_schema.database import metadata
from sqlalchemy import Table, Column, String, Integer, DateTime, Text, func

# Define your table using the shared metadata
payment_events = Table(
    "payment_events", metadata,
    Column("id", String(36), primary_key=True),
    Column("device_id", String(100), nullable=False),
    Column("amount_cents", Integer, nullable=False),
    Column("currency", String(3), nullable=False),
    Column("pan_token", String(200)),     # Never store raw PANs
    Column("result", String(20)),
    Column("occurred_at", DateTime(timezone=True), server_default=func.now()),
    Column("raw_response", Text),
)
```

Then generate and apply the migration:

```bash
cd src/ruvon
alembic revision --autogenerate -m "add_payment_events"
# Always review the generated file before applying
alembic upgrade head
```

**Note:** Alembic auto-generate has a ~15% false-positive rate. Always review the generated migration before applying it.

### Edge SQLite Schema

For edge-device tables, add them to `SQLITE_SCHEMA` in `src/ruvon/implementations/persistence/sqlite.py`. These tables are auto-created by `CREATE TABLE IF NOT EXISTS` on first startup — no Alembic needed.

---

## Custom API Routes (RUVON_CUSTOM_ROUTERS)

Mount additional FastAPI routers on the Ruvon server without modifying core server code:

### Step 1: Define your router

```python
# myapp/routers/payments.py
from fastapi import APIRouter, Depends
from typing import Optional

router = APIRouter(prefix="/api/v1/payments", tags=["Payments"])

@router.get("/summary")
async def payment_summary(device_id: Optional[str] = None):
    # Query your custom payment_events table here
    return {"total_today": 42, "device_id": device_id}

@router.post("/void/{txn_id}")
async def void_transaction(txn_id: str):
    return {"voided": True, "txn_id": txn_id}
```

### Step 2: Set the environment variable

```bash
export RUVON_CUSTOM_ROUTERS="myapp.routers.payments.router"

# Multiple routers (comma-separated)
export RUVON_CUSTOM_ROUTERS="myapp.routers.payments.router,myapp.routers.reports.router"
```

The routers are imported at server startup and mounted on the FastAPI app. They appear automatically in the Swagger UI at `/docs`.

---

## Custom Step Types

### Creating a New Step Type

Ruvon supports custom step types beyond the built-in `STANDARD`, `ASYNC`, `DECISION`, etc.

**Step 1: Define the Step Model**

```python
from ruvon.models import WorkflowStep
from pydantic import BaseModel
from typing import Optional, Dict, Any


class RetryableWorkflowStep(WorkflowStep):
    """
    Step with automatic retry logic
    """
    type: str = "RETRYABLE"

    # Retry configuration
    max_retries: int = 3
    retry_delay_seconds: int = 5
    backoff_multiplier: float = 2.0
    retry_on_exceptions: list[str] = []  # Exception class names

    # Retry state (tracked at runtime)
    retry_count: int = 0
    last_error: Optional[str] = None
```

**Step 2: Implement Execution Logic**

```python
# In ruvon/workflow.py or custom executor

async def execute_retryable_step(
    self,
    step: RetryableWorkflowStep,
    user_input: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Execute step with retry logic"""
    import asyncio

    retry_delay = step.retry_delay_seconds

    for attempt in range(step.max_retries + 1):
        try:
            # Execute step function
            result = await self._execute_step_function(step, user_input)

            # Success - reset retry count
            step.retry_count = 0
            step.last_error = None

            return result

        except Exception as e:
            exception_name = type(e).__name__

            # Check if we should retry this exception
            if step.retry_on_exceptions and exception_name not in step.retry_on_exceptions:
                raise  # Don't retry

            step.retry_count = attempt + 1
            step.last_error = str(e)

            if attempt < step.max_retries:
                # Log retry
                await self.persistence.log_execution(
                    workflow_id=self.id,
                    log_level="WARNING",
                    message=f"Step failed (attempt {attempt + 1}/{step.max_retries}), retrying in {retry_delay}s",
                    step_name=step.name,
                    metadata={"error": str(e)}
                )

                # Wait before retry (with exponential backoff)
                await asyncio.sleep(retry_delay)
                retry_delay *= step.backoff_multiplier
            else:
                # Max retries exceeded
                raise RuntimeError(f"Step failed after {step.max_retries} retries: {e}")
```

**Step 3: Use in YAML**

```yaml
workflow_type: "ResilientWorkflow"
steps:
  - name: "Call_External_API"
    type: "RETRYABLE"
    function: "steps.call_api"
    max_retries: 5
    retry_delay_seconds: 10
    backoff_multiplier: 2.0
    retry_on_exceptions:
      - "ConnectionError"
      - "TimeoutError"
      - "HTTPError"
```

---

## Custom Observers

### Advanced Observer: Distributed Tracing

Integrate with OpenTelemetry for distributed tracing.

```python
"""
OpenTelemetry Observer

Exports workflow traces to distributed tracing systems (Jaeger, Zipkin, etc.)
"""

from typing import Dict, Any
from opentelemetry import trace
from opentelemetry.exporter.jaeger.thrift import JaegerExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


class OpenTelemetryObserver:
    """
    Workflow observer that creates distributed traces
    """

    def __init__(self, service_name: str = "ruvon-workflows"):
        # Configure tracer
        resource = Resource(attributes={SERVICE_NAME: service_name})

        jaeger_exporter = JaegerExporter(
            agent_host_name="localhost",
            agent_port=6831,
        )

        provider = TracerProvider(resource=resource)
        processor = BatchSpanProcessor(jaeger_exporter)
        provider.add_span_processor(processor)

        trace.set_tracer_provider(provider)
        self.tracer = trace.get_tracer(__name__)

        # Active spans (workflow_id -> span)
        self.workflow_spans = {}
        self.step_spans = {}

    async def on_workflow_started(
        self,
        workflow_id: str,
        workflow_type: str,
        initial_state: Dict[str, Any]
    ) -> None:
        """Start workflow trace"""
        span = self.tracer.start_span(
            name=f"workflow.{workflow_type}",
            attributes={
                "workflow.id": workflow_id,
                "workflow.type": workflow_type,
            }
        )

        self.workflow_spans[workflow_id] = span

    async def on_step_executed(
        self,
        workflow_id: str,
        step_name: str,
        step_result: Dict[str, Any],
        execution_time_ms: float
    ) -> None:
        """Record step execution as span"""
        workflow_span = self.workflow_spans.get(workflow_id)

        if workflow_span:
            with self.tracer.start_as_current_span(
                name=f"step.{step_name}",
                context=trace.set_span_in_context(workflow_span),
                attributes={
                    "step.name": step_name,
                    "step.execution_time_ms": execution_time_ms,
                }
            ) as step_span:
                # Add result as attributes
                if "status" in step_result:
                    step_span.set_attribute("step.status", step_result["status"])

    async def on_workflow_completed(
        self,
        workflow_id: str,
        final_state: Dict[str, Any],
        total_execution_time_ms: float
    ) -> None:
        """End workflow trace"""
        span = self.workflow_spans.pop(workflow_id, None)

        if span:
            span.set_attribute("workflow.status", "completed")
            span.set_attribute("workflow.execution_time_ms", total_execution_time_ms)
            span.end()

    async def on_workflow_failed(
        self,
        workflow_id: str,
        error: Exception,
        failed_step: str
    ) -> None:
        """Mark workflow trace as failed"""
        span = self.workflow_spans.pop(workflow_id, None)

        if span:
            span.set_attribute("workflow.status", "failed")
            span.set_attribute("workflow.failed_step", failed_step)
            span.record_exception(error)
            span.end()

    async def on_workflow_status_changed(
        self,
        workflow_id: str,
        old_status: str,
        new_status: str
    ) -> None:
        """Add status change event to trace"""
        span = self.workflow_spans.get(workflow_id)

        if span:
            span.add_event(
                name="status_changed",
                attributes={
                    "old_status": old_status,
                    "new_status": new_status,
                }
            )
```

**Usage:**

```python
from my_observers.opentelemetry import OpenTelemetryObserver

builder = WorkflowBuilder(
    config_dir="config/",
)
```

---

## Plugin Architecture

### Creating a Ruvon Plugin Package

Ruvon supports `ruvon-*` plugin packages for extending functionality.

**Project Structure:**

```
ruvon-stripe/
├── pyproject.toml
├── README.md
├── src/
│   └── ruvon_stripe/
│       ├── __init__.py
│       ├── steps.py          # Stripe payment steps
│       ├── models.py         # Stripe state models
│       └── workflows/
│           └── payment.yaml  # Pre-built workflows
└── tests/
    └── test_stripe.py
```

**pyproject.toml:**

```toml
[project]
name = "ruvon-stripe"
version = "1.0.0"
description = "Stripe payment integration for Ruvon workflows"
requires-python = ">=3.10"
dependencies = [
    "ruvon>=1.0.0",
    "stripe>=5.0.0",
]

[project.entry-points."ruvon.plugins"]
stripe = "ruvon_stripe:plugin"
```

**src/ruvon_stripe/__init__.py:**

```python
"""
Ruvon Stripe Plugin

Provides Stripe payment processing steps for Ruvon workflows.
"""

from pathlib import Path


def plugin():
    """
    Plugin entry point

    Returns plugin metadata for Ruvon.
    """
    return {
        "name": "stripe",
        "version": "1.0.0",
        "description": "Stripe payment integration",
        "workflows_dir": Path(__file__).parent / "workflows",
        "steps_module": "ruvon_stripe.steps",
        "models_module": "ruvon_stripe.models",
    }
```

**src/ruvon_stripe/steps.py:**

```python
"""
Stripe payment steps
"""

import stripe
import os
from ruvon.models import StepContext
from ruvon_stripe.models import StripePaymentState


stripe.api_key = os.getenv("STRIPE_API_KEY")


def create_payment_intent(state: StripePaymentState, context: StepContext, **kwargs) -> dict:
    """
    Create Stripe payment intent
    """
    intent = stripe.PaymentIntent.create(
        amount=int(state.amount * 100),  # Convert to cents
        currency=state.currency,
        metadata={
            "workflow_id": str(context.workflow_id),
            "order_id": state.order_id,
        }
    )

    return {
        "payment_intent_id": intent.id,
        "client_secret": intent.client_secret,
        "status": intent.status,
    }


def confirm_payment(state: StripePaymentState, context: StepContext, **kwargs) -> dict:
    """
    Confirm Stripe payment
    """
    intent = stripe.PaymentIntent.confirm(state.payment_intent_id)

    return {
        "payment_status": intent.status,
        "payment_confirmed": intent.status == "succeeded",
    }


def refund_payment(state: StripePaymentState, context: StepContext, **kwargs) -> dict:
    """
    Refund Stripe payment (compensation function)
    """
    refund = stripe.Refund.create(payment_intent=state.payment_intent_id)

    return {
        "refund_id": refund.id,
        "refund_status": refund.status,
        "payment_refunded": True,
    }
```

**src/ruvon_stripe/workflows/payment.yaml:**

```yaml
workflow_type: "StripePayment"
workflow_version: "1.0.0"
initial_state_model: "ruvon_stripe.models.StripePaymentState"
description: "Stripe payment processing workflow"

steps:
  - name: "Create_Payment_Intent"
    type: "STANDARD"
    function: "ruvon_stripe.steps.create_payment_intent"
    automate_next: true

  - name: "Confirm_Payment"
    type: "STANDARD"
    function: "ruvon_stripe.steps.confirm_payment"
    compensate_function: "ruvon_stripe.steps.refund_payment"
```

**Using the Plugin:**

```bash
# Install plugin
pip install ruvon-stripe

# Plugin auto-discovered by Ruvon
```

```python
from ruvon.builder import WorkflowBuilder

builder = WorkflowBuilder(config_dir="config/")

# Plugin workflows automatically registered
workflow = builder.create_workflow(
    "StripePayment",
    initial_data={
        "order_id": "ORDER-123",
        "amount": 99.99,
        "currency": "usd",
    }
)
```

---

## Contributing Back to Ruvon

### Contribution Workflow

1. **Fork the repository**
   ```bash
   git clone https://github.com/yourusername/ruvon.git
   cd ruvon
   ```

2. **Create a feature branch**
   ```bash
   git checkout -b feature/my-awesome-feature
   ```

3. **Install development dependencies**
   ```bash
   pip install -e ".[dev]"
   ```

4. **Make changes**
   - Add tests for new features
   - Update documentation
   - Follow code style (PEP 8)

5. **Run tests**
   ```bash
   pytest tests/ -v
   pytest tests/benchmarks/  # Performance tests
   ```

6. **Run linters**
   ```bash
   black src/
   isort src/
   mypy src/
   ```

7. **Commit changes**
   ```bash
   git add .
   git commit -m "feat: add awesome feature

   - Detailed description
   - Breaking changes (if any)
   "
   ```

8. **Push and create PR**
   ```bash
   git push origin feature/my-awesome-feature
   # Create pull request on GitHub
   ```

---

### Contribution Guidelines

**Code Style:**
- Use `black` for formatting
- Use `isort` for import sorting
- Type hints required (check with `mypy`)
- Docstrings for all public functions

**Testing:**
- Unit tests required for new features
- Integration tests for new providers
- Benchmarks for performance-critical changes
- Minimum 80% code coverage

**Documentation:**
- Update relevant docs in `docs/`
- Add examples to `examples/`
- Update `CHANGELOG.md`

**Commit Messages:**
```
<type>(<scope>): <subject>

<body>

<footer>
```

Types: `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `chore`

---

## Plugin Ideas

### Useful Plugins to Build

1. **ruvon-aws** - AWS integrations (S3, SQS, SNS, Lambda)
2. **ruvon-gcp** - Google Cloud integrations
3. **ruvon-slack** - Slack notifications
4. **ruvon-email** - Email notifications (SendGrid, SES)
5. **ruvon-twilio** - SMS notifications
6. **ruvon-stripe** - Payment processing
7. **ruvon-paypal** - Alternative payments
8. **ruvon-shopify** - E-commerce integrations
9. **ruvon-salesforce** - CRM integrations
10. **ruvon-analytics** - Advanced analytics and dashboards

---

## Summary

**Extending Ruvon:**

1. **Custom Step Types**: Define new execution patterns
2. **Custom Observers**: Add monitoring, tracing, analytics
3. **Custom Providers**: Integrate with any backend
4. **Plugins**: Package and share reusable workflows

**Contributing:**

1. Fork → Branch → Code → Test → PR
2. Follow code style and testing guidelines
3. Add documentation and examples
4. Engage with community for feedback

**Resources:**

- Contributing Guide: `/CONTRIBUTING.md`
- Development Setup: `/docs/development.md`
- Architecture: `/docs/architecture.md`
- Community Forum: `https://github.com/yourorg/ruvon/discussions`

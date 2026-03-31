"""
Tests for CRON_SCHEDULE step type and poll_scheduled_workflows task.

Tests:
1. register_scheduled_workflow inserts correct row into DB (mocked pool).
2. poll_scheduled_workflows triggers due workflows and advances next_run_at.
3. poll_scheduled_workflows skips workflows with future next_run_at.
4. croniter computes next run correctly for a basic cron expression.
"""
import json
import sys
import types
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

# ---------------------------------------------------------------------------
# Stub out optional heavy dependencies before any rufus module is imported.
# rufus.tasks → rufus.events → redis.asyncio (not installed in test env)
# ---------------------------------------------------------------------------
if "redis" not in sys.modules:
    _redis_stub = types.ModuleType("redis")
    _redis_asyncio_stub = types.ModuleType("redis.asyncio")
    _redis_asyncio_stub.Redis = MagicMock
    _redis_asyncio_stub.from_url = MagicMock(return_value=MagicMock())
    _redis_stub.asyncio = _redis_asyncio_stub
    sys.modules["redis"] = _redis_stub
    sys.modules["redis.asyncio"] = _redis_asyncio_stub

if "celery" not in sys.modules:
    _celery_stub = types.ModuleType("celery")

    class _FakeCelery:
        def __init__(self, *a, **kw): pass
        def task(self, fn=None, *a, **kw):
            # Handles both @celery_app.task and @celery_app.task(bind=True, ...)
            def decorator(f):
                f.delay = MagicMock(side_effect=lambda *a, **kw: None)
                f.apply_async = MagicMock()
                return f
            if fn is not None:
                return decorator(fn)
            return decorator
        conf = MagicMock()
        config_from_object = MagicMock()

    _celery_stub.Celery = _FakeCelery

    # Stub out celery sub-modules accessed at import time
    for _sub in ("signals", "utils", "utils.log", "app", "app.base",
                 "schedules", "beat", "contrib", "contrib.django"):
        sys.modules[f"celery.{_sub}"] = types.ModuleType(f"celery.{_sub}")

    # signals module needs specific attributes
    _signals_stub = sys.modules["celery.signals"]
    for _sig in ("worker_process_init", "worker_ready", "worker_shutdown",
                 "task_prerun", "task_postrun", "task_failure", "task_success"):
        setattr(_signals_stub, _sig, MagicMock())

    # schedules module — crontab and others
    _sched_stub = sys.modules["celery.schedules"]
    _sched_stub.crontab = MagicMock
    _sched_stub.schedule = MagicMock

    sys.modules["celery"] = _celery_stub


# ---------------------------------------------------------------------------
# 1. croniter basic integration
# ---------------------------------------------------------------------------

def test_cron_next_run_computed_correctly():
    """croniter correctly computes the next run after a reference time."""
    from croniter import croniter

    ref = datetime(2026, 2, 25, 12, 0, 0, tzinfo=timezone.utc)  # noon UTC
    # "every hour at :30" — next should be 12:30
    cron = croniter("30 * * * *", ref)
    next_run = cron.get_next(datetime)

    assert next_run.minute == 30
    assert next_run.hour == 12
    assert next_run.tzinfo is not None


# ---------------------------------------------------------------------------
# 2. register_scheduled_workflow — DB insert
# ---------------------------------------------------------------------------

def test_register_schedule_inserts_row():
    """
    CeleryExecutionProvider.register_scheduled_workflow calls pool.execute
    with the correct INSERT statement and parameters.
    """
    from rufus.implementations.execution.celery import CeleryExecutionProvider

    # Build a fake provider with a mock pool
    conn_mock = AsyncMock()
    conn_mock.__aenter__ = AsyncMock(return_value=conn_mock)
    conn_mock.__aexit__ = AsyncMock(return_value=False)

    pool_mock = MagicMock()
    pool_mock.acquire = MagicMock(return_value=conn_mock)

    fake_persistence = MagicMock()
    fake_persistence.pool = pool_mock

    provider = CeleryExecutionProvider()

    inserted_args = []

    async def fake_execute(query, *args):
        inserted_args.extend(args)

    conn_mock.execute = fake_execute

    # Patch tasks._persistence_provider and pg_executor
    with patch("rufus.tasks._persistence_provider", fake_persistence), \
         patch("rufus.utils.postgres_executor.pg_executor") as mock_pg_exec, \
         patch("rufus.implementations.execution.celery.pg_executor", mock_pg_exec):

        def run_sync(coro):
            import asyncio
            return asyncio.run(coro)

        mock_pg_exec.run_coroutine_sync = run_sync

        provider.register_scheduled_workflow(
            schedule_name="nightly_report",
            workflow_type="NightlyReportWorkflow",
            cron_expression="0 2 * * *",
            initial_data={"env": "prod"},
        )

    assert "nightly_report" in inserted_args
    assert "NightlyReportWorkflow" in inserted_args
    assert "0 2 * * *" in inserted_args
    # initial_data should be JSON-serialised
    assert json.dumps({"env": "prod"}) in inserted_args


# ---------------------------------------------------------------------------
# 3. poll_scheduled_workflows — triggers due workflows
# ---------------------------------------------------------------------------

def test_poll_triggers_due_workflows():
    """
    poll_scheduled_workflows triggers trigger_scheduled_workflow.delay for each
    row with next_run_at <= now(), then updates next_run_at.
    """
    from rufus.tasks import poll_scheduled_workflows

    now = datetime.now(timezone.utc)
    due_row = {
        "schedule_name": "every_minute",
        "workflow_type": "PingWorkflow",
        "cron_expression": "* * * * *",
        "initial_data": json.dumps({"ping": True}),
        "next_run_at": now - timedelta(seconds=5),
    }

    conn_mock = AsyncMock()
    conn_mock.__aenter__ = AsyncMock(return_value=conn_mock)
    conn_mock.__aexit__ = AsyncMock(return_value=False)
    conn_mock.fetch = AsyncMock(return_value=[due_row])
    conn_mock.execute = AsyncMock()

    pool_mock = MagicMock()
    pool_mock.acquire = MagicMock(return_value=conn_mock)

    fake_persistence = MagicMock()
    fake_persistence.pool = pool_mock

    triggered = []

    with patch("rufus.tasks._persistence_provider", fake_persistence), \
         patch("rufus.tasks.pg_executor") as mock_pg_exec, \
         patch("rufus.tasks.trigger_scheduled_workflow") as mock_trigger:

        mock_trigger.delay = MagicMock(side_effect=lambda wf_type, data: triggered.append(wf_type))

        def run_sync(coro):
            import asyncio
            return asyncio.run(coro)

        mock_pg_exec.run_coroutine_sync = run_sync

        poll_scheduled_workflows()

    assert "PingWorkflow" in triggered, (
        f"Expected PingWorkflow to be triggered, got {triggered}"
    )
    # Verify next_run_at was updated
    conn_mock.execute.assert_called_once()


# ---------------------------------------------------------------------------
# 4. poll_scheduled_workflows — skips future workflows
# ---------------------------------------------------------------------------

def test_poll_skips_future_workflows():
    """
    poll_scheduled_workflows does NOT trigger workflows whose next_run_at is
    in the future (the SQL WHERE clause handles this, but we verify no dispatch
    when the DB returns an empty result set).
    """
    from rufus.tasks import poll_scheduled_workflows

    conn_mock = AsyncMock()
    conn_mock.__aenter__ = AsyncMock(return_value=conn_mock)
    conn_mock.__aexit__ = AsyncMock(return_value=False)
    conn_mock.fetch = AsyncMock(return_value=[])  # No due rows
    conn_mock.execute = AsyncMock()

    pool_mock = MagicMock()
    pool_mock.acquire = MagicMock(return_value=conn_mock)

    fake_persistence = MagicMock()
    fake_persistence.pool = pool_mock

    triggered = []

    with patch("rufus.tasks._persistence_provider", fake_persistence), \
         patch("rufus.tasks.pg_executor") as mock_pg_exec, \
         patch("rufus.tasks.trigger_scheduled_workflow") as mock_trigger:

        mock_trigger.delay = MagicMock(side_effect=lambda wf_type, data: triggered.append(wf_type))

        def run_sync(coro):
            import asyncio
            return asyncio.run(coro)

        mock_pg_exec.run_coroutine_sync = run_sync

        poll_scheduled_workflows()

    assert triggered == [], f"No workflows should be triggered, got {triggered}"
    conn_mock.execute.assert_not_called()

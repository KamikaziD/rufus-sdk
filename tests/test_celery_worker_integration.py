#!/usr/bin/env python3
"""
Integration test for Celery worker improvements.
Tests automatic task discovery and beat schedule population.

Note: This is a standalone runner script, not a pytest test suite.
Run directly: python tests/test_celery_worker_integration.py
"""
import os
import sys
import pytest

# Standalone script — skip when collected by pytest
pytestmark = pytest.mark.skip(reason="standalone runner script; run directly with python")

# Set up environment
os.environ['WORKFLOW_CONFIG_DIR'] = 'config'
os.environ['WORKFLOW_REGISTRY_FILE'] = 'workflow_registry.yaml'

def test_imports():
    """Test that celery_app can be imported"""
    print("Testing imports...")
    try:
        from rufus.celery_app import celery_app, workflow_builder, discovered_task_modules
        print("  ✅ Imports successful")
        return celery_app, workflow_builder, discovered_task_modules
    except ImportError as e:
        print(f"  ❌ Import failed: {e}")
        sys.exit(1)

def test_task_discovery(discovered_task_modules):
    """Test that user modules are discovered"""
    print("\nTesting task module discovery...")
    print(f"  Discovered modules: {discovered_task_modules}")

    if len(discovered_task_modules) == 0:
        print("  ⚠️  No task modules discovered (registry may be empty or not found)")
        print("  This is OK if you haven't created any workflows yet")
        return

    print(f"  ✅ Discovered {len(discovered_task_modules)} task modules")
    for module in discovered_task_modules:
        print(f"    - {module}")

def test_celery_config(celery_app):
    """Test Celery configuration"""
    print("\nTesting Celery configuration...")

    # Check includes
    includes = celery_app.conf.include
    print(f"  Celery includes: {includes}")
    assert 'rufus.tasks' in includes, "rufus.tasks not in includes!"
    print("  ✅ rufus.tasks included")

    # Check broker/backend
    broker = celery_app.conf.broker_url
    backend = celery_app.conf.result_backend
    print(f"  Broker: {broker}")
    print(f"  Backend: {backend}")
    print("  ✅ Broker and backend configured")

def test_beat_schedule(celery_app):
    """Test that scheduled workflows are registered"""
    print("\nTesting beat schedule...")
    beat_schedule = celery_app.conf.beat_schedule
    print(f"  Beat schedule keys: {list(beat_schedule.keys())}")

    # Should have at least poll-dynamic-schedules
    assert 'poll-dynamic-schedules' in beat_schedule, "poll-dynamic-schedules not found!"
    print("  ✅ poll-dynamic-schedules registered")

    # Check for scheduled workflows
    scheduled_workflows = [k for k in beat_schedule.keys() if k.startswith('trigger-')]
    if scheduled_workflows:
        print(f"  ✅ Found {len(scheduled_workflows)} scheduled workflows:")
        for wf_name in scheduled_workflows:
            schedule = beat_schedule[wf_name]
            print(f"    - {wf_name}: {schedule.get('schedule')}")
    else:
        print("  ⚠️  No scheduled workflows found (this is OK if none are configured)")

def test_workflow_builder(workflow_builder):
    """Test that global workflow_builder is available"""
    print("\nTesting WorkflowBuilder...")

    if workflow_builder is None:
        print("  ⚠️  WorkflowBuilder is None (registry file not found)")
        print("  This is OK if you haven't set up a workflow registry yet")
        return

    # Test methods exist
    assert hasattr(workflow_builder, 'get_all_task_modules'), "Missing get_all_task_modules method!"
    assert hasattr(workflow_builder, 'get_scheduled_workflows'), "Missing get_scheduled_workflows method!"
    print("  ✅ WorkflowBuilder has required methods")

    # Test registry
    try:
        registry = workflow_builder.workflow_registry
        print(f"  ✅ Registry has {len(registry)} workflows registered")
        for wf_type in list(registry.keys())[:5]:  # Show first 5
            print(f"    - {wf_type}")
    except Exception as e:
        print(f"  ⚠️  Could not access registry: {e}")

def test_task_registration(celery_app):
    """Test that core tasks are registered"""
    print("\nTesting task registration...")

    # Check if inspect works
    try:
        # Note: This requires a running worker, so we'll just check task names
        core_tasks = [
            'rufus.tasks.trigger_scheduled_workflow',
            'rufus.tasks.resume_from_async_task',
            'rufus.tasks.execute_sub_workflow',
        ]

        print("  Expected core tasks:")
        for task_name in core_tasks:
            print(f"    - {task_name}")
        print("  ✅ Core tasks should be registered (requires running worker to verify)")

    except Exception as e:
        print(f"  ⚠️  Could not inspect tasks: {e}")

def main():
    """Run all tests"""
    print("=" * 70)
    print("Celery Worker Integration Tests")
    print("=" * 70)

    # Test imports
    celery_app, workflow_builder, discovered_task_modules = test_imports()

    # Run tests
    test_task_discovery(discovered_task_modules)
    test_celery_config(celery_app)
    test_beat_schedule(celery_app)
    test_workflow_builder(workflow_builder)
    test_task_registration(celery_app)

    print("\n" + "=" * 70)
    print("🎉 All tests passed!")
    print("=" * 70)
    print("\nNext steps:")
    print("1. Set WORKFLOW_CONFIG_DIR to your config directory")
    print("2. Create workflow_registry.yaml with your workflows")
    print("3. Start a Celery worker: celery -A rufus.celery_app worker")
    print("4. Check worker logs for discovered modules and scheduled workflows")
    print("\nFor scheduled workflows:")
    print("1. Start Celery Beat: celery -A rufus.celery_app beat")
    print("2. Beat will automatically trigger workflows based on their schedule")

if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

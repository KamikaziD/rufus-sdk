"""
Flask REST API for Rufus Workflow Engine

This example demonstrates how to embed Rufus into a Flask application
to expose workflow operations via REST API endpoints.

Features:
- Full async/await support with uvloop for optimal performance
- High-performance JSON serialization (orjson)
- Optimized PostgreSQL connection pooling
- Import caching for step functions

Performance Optimizations:
- uvloop event loop (2-4x faster async I/O)
- orjson serialization (3-5x faster JSON operations)
- Connection pool tuning (configurable via environment variables)

Endpoints:
- POST /workflows - Start a new workflow
- GET /workflows/<workflow_id> - Get workflow status
- POST /workflows/<workflow_id>/resume - Resume a paused workflow
- GET /workflows - List all workflows
- POST /workflows/<workflow_id>/cancel - Cancel a workflow
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import asyncio
import os
import sys
from pathlib import Path
from typing import Dict, Any

# Add current directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from rufus.builder import WorkflowBuilder
from rufus.implementations.persistence_provider.postgres import PostgresPersistenceProvider
from rufus.implementations.execution.sync import SyncExecutor
from rufus.implementations.observability.logging import LoggingObserver
from rufus.implementations.expression_evaluator.simple import SimpleExpressionEvaluator
from rufus.implementations.templating.jinja2 import Jinja2TemplateEngine

# Initialize Flask app
app = Flask(__name__)
CORS(app)  # Enable CORS for frontend integration

# Global workflow builder instance
workflow_builder: WorkflowBuilder = None


def get_event_loop():
    """Get or create event loop for async operations"""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop


async def initialize_engine():
    """Initialize the workflow builder with optimized providers"""
    global workflow_builder

    # Get configuration from environment variables
    registry_path = os.getenv("WORKFLOW_REGISTRY_PATH", str(Path(__file__).parent / "workflow_registry.yaml"))
    db_url = os.getenv("DATABASE_URL", "postgresql://user:password@localhost:5432/rufus_db")

    # Optional: Configure PostgreSQL pool settings for optimal performance
    pool_min_size = int(os.getenv("POSTGRES_POOL_MIN_SIZE", "10"))
    pool_max_size = int(os.getenv("POSTGRES_POOL_MAX_SIZE", "50"))

    # Initialize persistence provider with optimized settings
    persistence = PostgresPersistenceProvider(
        db_url=db_url,
        pool_min_size=pool_min_size,
        pool_max_size=pool_max_size
    )
    await persistence.initialize()
    print(f"✓ PostgreSQL persistence initialized (pool: {pool_min_size}-{pool_max_size} connections)")

    # Initialize execution provider
    executor = SyncExecutor()
    await executor.initialize()

    # Initialize observer
    observer = LoggingObserver()

    # Create workflow builder
    workflow_builder = WorkflowBuilder(
        registry_path=registry_path,
        persistence_provider=persistence,
        execution_provider=executor,
        observer=observer,
        expression_evaluator_cls=SimpleExpressionEvaluator,
        template_engine_cls=Jinja2TemplateEngine,
    )

    # Check for performance optimizations
    import rufus
    from rufus.utils.serialization import get_backend
    print(f"✓ Performance optimizations:")
    print(f"  - Event loop: {rufus._event_loop_backend}")
    print(f"  - JSON backend: {get_backend()}")
    print(f"  - Import caching: Enabled")
    print(f"✓ Workflow builder ready")


# Initialize engine on startup
loop = get_event_loop()
loop.run_until_complete(initialize_engine())


@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({"status": "healthy", "service": "rufus-workflow-api"})


@app.route('/workflows', methods=['POST'])
def create_workflow():
    """
    Start a new workflow

    Request body:
    {
        "workflow_type": "OrderProcessing",
        "initial_data": {
            "customer_id": "CUST123",
            "customer_email": "customer@example.com",
            "items": [
                {
                    "product_id": "PROD001",
                    "name": "Widget",
                    "quantity": 2,
                    "price": 29.99
                }
            ]
        }
    }

    Response:
    {
        "workflow_id": "abc-123-def",
        "status": "ACTIVE",
        "current_step": "Initialize_Order"
    }
    """
    try:
        data = request.get_json()
        workflow_type = data.get("workflow_type")
        initial_data = data.get("initial_data", {})

        if not workflow_type:
            return jsonify({"error": "workflow_type is required"}), 400

        # Start workflow
        loop = get_event_loop()
        workflow = loop.run_until_complete(
            workflow_builder.create_workflow(
                workflow_type=workflow_type,
                initial_data=initial_data
            )
        )

        # Execute workflow steps until it pauses or completes
        while workflow.status == "ACTIVE":
            try:
                loop.run_until_complete(workflow.next_step(user_input={}))
            except WorkflowPauseDirective:
                # Workflow paused for human input
                break

        return jsonify({
            "workflow_id": workflow.id,
            "status": workflow.status,
            "current_step": workflow.current_step_name,
            "state": workflow.state.model_dump() if workflow.state else {}
        }), 201

    except Exception as e:
        app.logger.error(f"Error creating workflow: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/workflows/<workflow_id>', methods=['GET'])
def get_workflow(workflow_id: str):
    """
    Get workflow status

    Response:
    {
        "workflow_id": "abc-123-def",
        "workflow_type": "OrderProcessing",
        "status": "WAITING_HUMAN",
        "current_step": "Request_Approval",
        "state": { ... }
    }
    """
    try:
        loop = get_event_loop()
        workflow = loop.run_until_complete(workflow_builder.load_workflow(workflow_id))

        return jsonify({
            "workflow_id": workflow.id,
            "workflow_type": workflow.workflow_type,
            "status": workflow.status,
            "current_step": workflow.current_step_name,
            "current_step_index": workflow.current_step,
            "total_steps": len(workflow.workflow_steps),
            "state": workflow.state.model_dump() if workflow.state else {}
        })

    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        app.logger.error(f"Error getting workflow: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/workflows/<workflow_id>/resume', methods=['POST'])
def resume_workflow(workflow_id: str):
    """
    Resume a paused workflow with user input

    Request body:
    {
        "user_input": {
            "approved": true,
            "approver_id": "ADMIN001",
            "notes": "Approved for processing"
        }
    }

    Response:
    {
        "workflow_id": "abc-123-def",
        "status": "COMPLETED",
        "current_step": null
    }
    """
    try:
        data = request.get_json()
        user_input = data.get("user_input", {})

        loop = get_event_loop()
        workflow = loop.run_until_complete(workflow_builder.load_workflow(workflow_id))

        if workflow.status not in ["WAITING_HUMAN", "PENDING_ASYNC"]:
            return jsonify({
                "error": f"Workflow is not paused. Current status: {workflow.status}"
            }), 400

        # Resume workflow with user input
        while workflow.status in ["ACTIVE", "WAITING_HUMAN"]:
            try:
                loop.run_until_complete(workflow.next_step(user_input=user_input))
                user_input = {}  # Only use input once
            except WorkflowPauseDirective:
                # Workflow paused again
                break

        return jsonify({
            "workflow_id": workflow.id,
            "status": workflow.status,
            "current_step": workflow.current_step_name,
            "state": workflow.state.model_dump() if workflow.state else {}
        })

    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        app.logger.error(f"Error resuming workflow: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/workflows', methods=['GET'])
def list_workflows():
    """
    List all workflows with optional filtering

    Query parameters:
    - status: Filter by status (e.g., ACTIVE, WAITING_HUMAN, COMPLETED)
    - workflow_type: Filter by workflow type
    - limit: Maximum number of results (default: 50)

    Response:
    {
        "workflows": [
            {
                "workflow_id": "abc-123-def",
                "workflow_type": "OrderProcessing",
                "status": "COMPLETED",
                "current_step": null
            }
        ],
        "total": 10
    }
    """
    try:
        # Get query parameters
        status = request.args.get('status')
        workflow_type = request.args.get('workflow_type')
        limit = int(request.args.get('limit', 50))

        # Build filters
        filters = {}
        if status:
            filters['status'] = status
        if workflow_type:
            filters['workflow_type'] = workflow_type

        loop = get_event_loop()
        workflows_data = loop.run_until_complete(
            workflow_builder.persistence_provider.list_workflows(**filters)
        )

        # Limit results
        workflows_data = workflows_data[:limit]

        # Format response
        workflows = []
        for wf_data in workflows_data:
            workflows.append({
                "workflow_id": wf_data.get("id"),
                "workflow_type": wf_data.get("workflow_type"),
                "status": wf_data.get("status"),
                "current_step": wf_data.get("current_step"),
                "created_at": wf_data.get("state", {}).get("created_at")
            })

        return jsonify({
            "workflows": workflows,
            "total": len(workflows)
        })

    except Exception as e:
        app.logger.error(f"Error listing workflows: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/workflows/<workflow_id>/cancel', methods=['POST'])
def cancel_workflow(workflow_id: str):
    """
    Cancel a workflow (marks as CANCELLED, does not execute rollback)

    Response:
    {
        "workflow_id": "abc-123-def",
        "status": "CANCELLED"
    }
    """
    try:
        loop = get_event_loop()
        workflow = loop.run_until_complete(workflow_builder.load_workflow(workflow_id))

        if workflow.status in ["COMPLETED", "FAILED", "CANCELLED"]:
            return jsonify({
                "error": f"Cannot cancel workflow with status: {workflow.status}"
            }), 400

        # Update status to CANCELLED
        old_status = workflow.status
        workflow.status = "CANCELLED"
        loop.run_until_complete(
            workflow.persistence_provider.save_workflow(workflow.id, workflow.to_dict())
        )
        loop.run_until_complete(
            workflow._notify_status_change(old_status, "CANCELLED", workflow.current_step_name)
        )

        return jsonify({
            "workflow_id": workflow.id,
            "status": workflow.status,
            "message": "Workflow cancelled successfully"
        })

    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        app.logger.error(f"Error cancelling workflow: {e}")
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    debug = os.getenv('DEBUG', 'False').lower() == 'true'
    app.run(host='0.0.0.0', port=port, debug=debug)

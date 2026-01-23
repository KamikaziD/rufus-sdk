"""
Flask REST API for Rufus Workflow Engine

This example demonstrates how to embed Rufus into a Flask application
to expose workflow operations via REST API endpoints.

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
import yaml
import os
import sys
from pathlib import Path
from typing import Dict, Any

# Add current directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from rufus.engine import WorkflowEngine
from rufus.implementations.persistence.postgres import PostgresPersistence
from rufus.implementations.execution.sync import SyncExecutor
from rufus.implementations.observability.logging import LoggingObserver
from rufus.implementations.expression_evaluator.simple import SimpleExpressionEvaluator
from rufus.implementations.templating.jinja2 import Jinja2TemplateEngine
from rufus.models import WorkflowPauseDirective

# Initialize Flask app
app = Flask(__name__)
CORS(app)  # Enable CORS for frontend integration

# Global workflow engine instance
workflow_engine: WorkflowEngine = None


def get_event_loop():
    """Get or create event loop for async operations"""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop


async def initialize_engine():
    """Initialize the workflow engine with providers"""
    global workflow_engine

    # Load workflow registry
    registry_path = Path(__file__).parent / "workflow_registry.yaml"
    with open(registry_path) as f:
        registry_config = yaml.safe_load(f)

    # Build workflow registry dict
    workflow_registry = {}
    for workflow in registry_config["workflows"]:
        workflow_file = Path(__file__).parent / workflow["config_file"]
        with open(workflow_file) as f:
            workflow_config = yaml.safe_load(f)
        workflow_registry[workflow["type"]] = {
            "initial_state_model_path": workflow["initial_state_model"],
            "steps": workflow_config["steps"],
            "workflow_version": workflow_config.get("workflow_version", "1.0"),
            "description": workflow.get("description", ""),
        }

    # Get database URL from environment variable
    db_url = os.getenv("DATABASE_URL", "postgresql://user:password@localhost:5432/rufus_db")

    # Initialize engine with PostgreSQL persistence
    persistence = PostgresPersistence(db_url=db_url)
    await persistence.initialize()

    workflow_engine = WorkflowEngine(
        persistence=persistence,
        executor=SyncExecutor(),
        observer=LoggingObserver(),
        workflow_registry=workflow_registry,
        expression_evaluator_cls=SimpleExpressionEvaluator,
        template_engine_cls=Jinja2TemplateEngine,
    )
    await workflow_engine.initialize()
    print(f"✓ Workflow engine initialized with {len(workflow_registry)} workflow types")


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
            workflow_engine.start_workflow(
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
        workflow = loop.run_until_complete(workflow_engine.get_workflow(workflow_id))

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
        workflow = loop.run_until_complete(workflow_engine.get_workflow(workflow_id))

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
            workflow_engine.persistence.list_workflows(**filters)
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
        workflow = loop.run_until_complete(workflow_engine.get_workflow(workflow_id))

        if workflow.status in ["COMPLETED", "FAILED", "CANCELLED"]:
            return jsonify({
                "error": f"Cannot cancel workflow with status: {workflow.status}"
            }), 400

        # Update status to CANCELLED
        old_status = workflow.status
        workflow.status = "CANCELLED"
        loop.run_until_complete(
            workflow.persistence.save_workflow(workflow.id, workflow.to_dict())
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

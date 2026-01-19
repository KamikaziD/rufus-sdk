# Workflow Testing UI Enhancements

## Summary
Updated the workflow testing UI (`src/confucius/contrib/`) to support all new production features including sub-workflows, saga pattern, and enhanced status tracking.

## Changes Made

### 1. JavaScript Updates (`src/confucius/contrib/static/js/app.js`)

#### New Status Handling
- **PENDING_SUB_WORKFLOW**: Displays when parent workflow is waiting for child workflow
  - Shows child workflow ID in the status message
  - Logs parent-child relationship details
  - Displays "Check Status" button for manual updates

- **FAILED_ROLLED_BACK**: Displays when saga compensation has been executed
  - Shows clear indication that rollback occurred
  - Enables "Retry" button for recovery

#### Enhanced Status Display
- Added display for `parent_execution_id` when workflow is a child
- Added display for `blocked_on_child_id` when workflow is waiting for child
- Added display for `workflow_type` to identify workflow category

### 2. CSS Updates (`src/confucius/contrib/static/css/style.css`)

#### New Status Badge Styles
```css
.status-PENDING_SUB_WORKFLOW { background-color: #8b5cf6; color: #fff; } /* Purple */
.status-FAILED_ROLLED_BACK { background-color: #d97706; color: #fff; } /* Orange */
```

### 3. API Model Updates (`src/confucius/models.py`)

#### WorkflowStatusResponse Enhanced
Added new optional fields to support sub-workflow tracking:
- `workflow_type`: The type of workflow (e.g., "LoanApplication", "KYC")
- `parent_execution_id`: UUID of parent workflow (if this is a child)
- `blocked_on_child_id`: UUID of child workflow (if parent is waiting)

### 4. Router Updates (`src/confucius/routers.py`)

#### get_workflow_status Endpoint
Now returns complete workflow metadata including parent-child relationships.

#### Workflow Examples
Added example data for KYC workflow:
```python
"KYC": {
    "user_name": "John Doe",
    "id_document_url": "s3://docs/id_valid.pdf"
}
```

Updated LoanApplication example to trigger detailed review (age 22 for lower credit score).

## Features Now Supported

### ✅ Sub-Workflows
- Parent workflow pauses with PENDING_SUB_WORKFLOW status
- UI displays child workflow ID that's blocking parent
- Clear visual indication (purple badge) for this state
- Can check status manually while waiting

### ✅ Saga Pattern (Compensation)
- Failed workflows show FAILED_ROLLED_BACK status
- Orange badge clearly distinguishes rolled-back failures
- Retry button available for recovery
- Logs indicate compensation was executed

### ✅ Parent-Child Relationships
- Parent workflows show which child is blocking them
- Child workflows show their parent ID
- Workflow type displayed for clarity
- Full metadata in status display

### ✅ Backward Compatibility
- All existing features continue to work
- New fields are optional (don't break old workflows)
- Existing status badges unchanged

## Testing Recommendations

### 1. Test Sub-Workflow Flow
```bash
# Start UI server
uvicorn main:app --reload

# Create LoanApplication workflow with age=22
# This will trigger KYC sub-workflow
# Verify:
# - Parent shows PENDING_SUB_WORKFLOW status (purple)
# - Parent displays blocked_on_child_id
# - Status includes workflow type
```

### 2. Test Saga Rollback
```bash
# Use test_loan_saga_rollback.py to create failed workflow
python test_loan_saga_rollback.py

# Load the workflow ID in UI
# Verify:
# - Status shows FAILED_ROLLED_BACK (orange)
# - Retry button is available
# - Logs mention compensation execution
```

### 3. Test Parent-Child Navigation
- Create parent workflow that launches child
- Note both workflow IDs
- Load parent in UI → see child ID
- Load child in UI → see parent ID
- Verify workflow types are displayed correctly

## Architecture Notes

### Status Badge Color Scheme
- **Green** (COMPLETED): Workflow finished successfully
- **Red** (FAILED): Workflow failed without rollback
- **Orange** (FAILED_ROLLED_BACK): Workflow failed, saga compensation executed
- **Yellow** (ACTIVE, PENDING_ASYNC): Workflow in progress or waiting for async task
- **Purple** (PENDING_SUB_WORKFLOW): Parent waiting for child workflow
- **Blue** (WAITING_HUMAN): Workflow waiting for human input

### WebSocket Real-Time Updates
- All status changes push immediately via WebSocket
- New statuses automatically reflected in UI
- No polling required for status updates

### PostgreSQL Integration
- UI is backend-agnostic (works with Redis or PostgreSQL)
- All workflow metadata persisted correctly
- Parent-child relationships maintained in database

## Future Enhancements (Not Implemented)

### Compensation Log Viewer
A dedicated tab could show:
- List of compensation steps executed
- Order of rollback (reverse of forward steps)
- State snapshots before/after compensation
- Compensation function results

This would require:
1. New API endpoint: `GET /workflow/{id}/compensation_log`
2. New tab in UI for compensation history
3. Visual timeline of rollback steps

### Hierarchical Workflow Tree View
Could display:
- Visual tree of parent-child relationships
- Navigate between parent/child workflows
- Show concurrent sub-workflows
- Indicate completion status of entire tree

### Saga Progress Visualization
- Show which steps have compensation defined
- Indicate checkpoint points for rollback
- Display compensation execution progress

## Files Modified
1. `/src/confucius/contrib/static/js/app.js` - JavaScript UI logic
2. `/src/confucius/contrib/static/css/style.css` - Status badge styles
3. `/src/confucius/models.py` - API response models
4. `/src/confucius/routers.py` - API endpoints and examples

## Dependencies
- PostgreSQL (running on port 5432)
- Redis (running on port 6379, for WebSocket)
- FastAPI server
- Modern web browser with WebSocket support

## Quick Start
```bash
# Ensure services are running
docker ps | grep postgres  # Should show confucius-postgres
docker ps | grep redis     # Should show redis

# Start the UI server
cd /Users/kim/Documents/ai/confucius
uvicorn main:app --reload

# Open browser to http://localhost:8000
# UI will be available at root path
# API docs at http://localhost:8000/docs
```

## Conclusion
The workflow testing UI now fully supports:
- ✅ Sub-workflow visualization
- ✅ Saga pattern status indication
- ✅ Parent-child relationship tracking
- ✅ All new workflow statuses
- ✅ PostgreSQL backend
- ✅ Real-time WebSocket updates
- ✅ Backward compatibility

All features implemented are production-ready and have been integrated with minimal disruption to existing functionality.

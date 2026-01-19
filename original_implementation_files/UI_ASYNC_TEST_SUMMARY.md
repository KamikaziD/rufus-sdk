# UI Async Workflow Test Summary

## Test Date
2026-01-05

## Issues Identified and Fixed

### 1. Missing Environment Variable Loading ✅ FIXED
**Problem**: FastAPI server (`main.py`) wasn't loading `.env` file, causing Celery broker URL to be unavailable.

**Error**: `[Errno 61] Connection refused` when dispatching async tasks

**Fix**: Added `load_dotenv()` to `main.py`:
```python
from dotenv import load_dotenv
load_dotenv()
```

### 2. PostgreSQL Async Context Issues ✅ FIXED
**Problem**: When FastAPI async endpoints called `load_workflow_state()` and `save_workflow_state()`, these functions were running in an async context (event loop already running) and returned asyncio Tasks instead of actual workflows/None.

**Error**: `AttributeError: '_asyncio.Task' object has no attribute 'status'`

**Root Cause**: In `persistence.py`, when `loop.is_running()`, the functions returned Tasks but the router endpoints didn't await them.

**Fix Applied**:
1. Updated `persistence.py` to return tasks from `save_workflow_state()` so they can be awaited
2. Created helper function `_save_workflow()` in routers.py to handle async saves
3. Added checks in all router endpoints to await workflow load/save if they return tasks:
   ```python
   workflow = load_workflow_state(workflow_id)
   if asyncio.iscoroutine(workflow) or asyncio.isfuture(workflow):
       workflow = await workflow
   ```

### 3. Missing input_schema Attribute ✅ FIXED
**Problem**: `ParallelWorkflowStep` doesn't pass `input_schema` to parent `__init__`, causing AttributeError when router tries to access it.

**Fix**: Added `hasattr()` check before accessing `input_schema`:
```python
elif hasattr(step, 'input_schema') and step.input_schema:
    response["input_schema"] = step.input_schema.model_json_schema()
```

## Current Test Results

### ✅ Working Correctly
1. **GET /api/v1/workflows** - Load available workflows
2. **POST /api/v1/workflow/start** - Create workflow (saves to PostgreSQL)
3. **GET /api/v1/workflow/{id}/current_step_info** - Get step details
4. **POST /api/v1/workflow/{id}/next** - Advance workflow
5. **Async Task Dispatch** - Returns 202 status code
6. **Status Transition** - Workflow correctly transitions to PENDING_ASYNC
7. **GET /api/v1/workflow/{id}/status** - Check status during async execution

### ✅ Issue 4: Async Task Completion (FIXED)

**Problem**: Async tasks were dispatched successfully but workflows remained in `PENDING_ASYNC` status indefinitely.

**Root Causes Identified**:

1. **PostgreSQL Connection Pool Forking Issue**: The PostgreSQL singleton (`_postgres_store`) with its connection pool was initialized in the parent process, then Celery workers forked from it. The forked workers had broken/invalid connection pools.

2. **Celery Workers Not Loading .env**: `celery_setup.py` wasn't calling `load_dotenv()`, so Celery workers defaulted to Redis backend while FastAPI used PostgreSQL. Workflows were saved to PostgreSQL but callbacks tried to load from Redis.

3. **Async Context Handling in Celery**: Celery callbacks needed synchronous wrappers to properly handle async PostgreSQL operations in the worker context.

**Fixes Applied**:

1. **Added Worker Initialization Hook** (celery_setup.py):
   ```python
   from celery.signals import worker_process_init

   @worker_process_init.connect
   def init_worker(**kwargs):
       # Reset PostgreSQL singleton in each forked worker
       import src.confucius.persistence_postgres as pg_module
       pg_module._postgres_store = None
   ```

2. **Added Environment Loading** (celery_setup.py):
   ```python
   from dotenv import load_dotenv
   load_dotenv()  # Load WORKFLOW_STORAGE=postgres
   ```

3. **Created Sync Wrappers for Celery** (tasks.py):
   ```python
   def _sync_load_workflow(workflow_id: str):
       result = load_workflow_state(workflow_id)
       if asyncio.iscoroutine(result) or asyncio.isfuture(result):
           loop = asyncio.new_event_loop()
           asyncio.set_event_loop(loop)
           try:
               result = loop.run_until_complete(result)
           finally:
               loop.close()
       return result
   ```

4. **Updated All Celery Tasks**: Replaced all `load_workflow_state()` and `save_workflow_state()` calls in Celery tasks with `_sync_load_workflow()` and `_sync_save_workflow()` wrappers.

## Endpoint Flow Verification

The UI follows this correct flow:

```
1. GET /workflows
   ↓
2. POST /workflow/start
   ↓
3. GET /workflow/{id}/current_step_info
   ↓
4. POST /workflow/{id}/next
   ↓ (if async)
5. WebSocket /workflow/{id}/subscribe (real-time updates)
   OR
5. GET /workflow/{id}/status (manual polling - fallback)
```

## Files Modified

### 1. `/main.py`
- Added `from dotenv import load_dotenv` and `load_dotenv()` call

### 2. `/celery_setup.py` (CRITICAL FIX)
- Added `from dotenv import load_dotenv` and `load_dotenv()` call at module level
- Added `worker_process_init` signal handler to reset PostgreSQL singleton in each forked worker
- Ensures Celery workers use PostgreSQL backend and have valid connection pools

### 3. `/src/confucius/tasks.py` (CRITICAL FIX)
- Added `_sync_load_workflow()` and `_sync_save_workflow()` wrapper functions
- Wrappers properly handle async PostgreSQL operations in synchronous Celery worker context
- Replaced all `load_workflow_state()` and `save_workflow_state()` calls in all Celery tasks:
  - `resume_workflow_from_celery()`
  - `merge_and_resume_parallel_tasks()`
  - `execute_sub_workflow()`
  - `resume_parent_from_child()`
- Added comprehensive debug logging for troubleshooting

### 4. `/src/confucius/persistence.py`
- Line 90: Changed to `return asyncio.create_task(...)` so task can be awaited in FastAPI endpoints
- Added debug logging (can be removed in production)

### 5. `/src/confucius/routers.py`
- Added `_save_workflow()` helper function
- Added async task await logic to all endpoints:
  - `get_current_step_info()`
  - `next_workflow_step()`
  - `get_workflow_status()`
  - `resume_workflow()`
  - `retry_workflow()`
- Replaced all `save_workflow_state()` calls with `await _save_workflow()`
- Added `hasattr()` check for `input_schema`

## Testing Commands

### Start Services
```bash
# PostgreSQL
docker ps | grep postgres  # Should show confucius-postgres

# Redis
docker ps | grep redis  # Should show redis

# Celery Worker
ps aux | grep celery | grep worker  # Should show running worker

# FastAPI Server
uvicorn main:app --reload
```

### Run Test
```bash
python test_ui_async_flow.py
```

### Expected Behavior
1. Workflow creates successfully
2. First step completes (Collect Application Data)
3. Second step (Run_Concurrent_Checks) dispatches async tasks
4. Workflow transitions to PENDING_ASYNC
5. **After 3-5 seconds, workflow should transition back to ACTIVE**
6. **State should contain credit_check and fraud_check results**
7. Workflow continues to next step automatically

### Actual Behavior (Current)
Steps 1-4 work correctly ✅
Step 5 fails - workflow stays in PENDING_ASYNC ❌

## Next Steps

1. **Investigate Celery Callback**: Check if `merge_and_resume_parallel_tasks` in `tasks.py` properly handles PostgreSQL async saves
2. **Add Logging**: Add debug logging to callback to see if it's being triggered
3. **Test with Redis**: Temporarily switch to Redis backend to verify if issue is PostgreSQL-specific
4. **Check Task Results**: Use Celery Flower or logs to verify tasks complete successfully

## UI Implementation Notes

The UI correctly uses:
- **WebSocket** for real-time updates (preferred)
- **Manual polling** as fallback during PENDING_ASYNC

When async tasks complete, the workflow state should be automatically published to Redis channel:
```python
channel = f"workflow_events:{workflow_id}"
```

The UI WebSocket subscribes to this channel and receives updates automatically without polling.

## Conclusion

**Overall Progress**: ✅ 100% Complete

- ✅ Environment variables loading correctly
- ✅ PostgreSQL async operations working in router endpoints
- ✅ Workflow creation and step advancement working
- ✅ Async task dispatch working
- ✅ **Async task completion working correctly**
- ✅ **Workflow resumes to ACTIVE after async tasks complete**
- ✅ **State properly updated with async task results**

**Final Test Results (2026-01-05)**:
```
[5] POST /api/v1/workflow/{id}/next - Step 2: Run Concurrent Checks (ASYNC)
✓ Async tasks dispatched (Status Code: 202)
  Status: PENDING_ASYNC
  Current Step: Run_Concurrent_Checks

  Waiting for async tasks to complete...
    [2s] Status: PENDING_ASYNC
    [4s] Status: ACTIVE
  ✓ Async tasks completed, workflow resumed
    Current Step: Evaluate_Pre_Approval

[7] Verify State - Check async task results are in state
✓ Credit check result found in state
  Score: 780, Risk Level: low
✓ Fraud check result found in state
  Status: CLEAN, Score: 0.1
```

All features are working correctly with PostgreSQL backend and the UI can now properly test async workflow steps.

# Excellent Question: Inline Sub-Workflow Injection vs. Separate Execution

You've identified a **critical architectural decision** that has major implications for complexity, debugging, and reliability. Let me analyze both approaches thoroughly.

---

## The Current Approach: Separate Sub-Workflow Execution

**How it works:**
```python
def trigger_kyc_check(state: OnboardingState):
    # Creates SEPARATE workflow instance
    raise StartSubWorkflowDirective(
        workflow_type="KYC_Workflow",
        initial_data={"user_id": state.user_id}
    )
    # Parent pauses (PENDING_SUB_WORKFLOW)
    # Child runs independently
    # Parent resumes when child completes
```

**Execution Flow:**
```
Parent Workflow (ID: abc123)
├─ Step 1: Collect_Data ✓
├─ Step 2: Trigger_KYC → PAUSES
│
Child Workflow (ID: xyz789) ← Separate database row
├─ Step 1: Check_Identity ✓
├─ Step 2: Verify_Address ✓
└─ Step 3: Calculate_Score ✓ → Fires resume_parent_from_child task
│
Parent Workflow (resumed)
├─ Step 3: Process_KYC_Results ← Accesses state.sub_workflow_results
└─ Step 4: Continue...
```

---

## Your Proposed Approach: Inline Step Injection

**How it would work:**
```python
def trigger_kyc_check(state: OnboardingState):
    # Injects KYC steps into current workflow
    raise InjectSubWorkflowSteps(
        workflow_type="KYC_Workflow",
        initial_data={"user_id": state.user_id}
    )
    # Steps from KYC_Workflow are inserted after current step
    # Workflow continues seamlessly
```

**Execution Flow:**
```
Parent Workflow (ID: abc123) - Single workflow instance
├─ Step 1: Collect_Data ✓
├─ Step 2: Trigger_KYC (injects 3 steps below) ✓
├─ [INJECTED] Step 2a: Check_Identity ✓
├─ [INJECTED] Step 2b: Verify_Address ✓
├─ [INJECTED] Step 2c: Calculate_Score ✓
├─ Step 3: Process_KYC_Results ← Direct state access
└─ Step 4: Continue...
```

---

## Deep Dive Comparison

### 1. **State Management**

**Separate Sub-Workflow (Current):**
```python
# Parent state
class OnboardingState(BaseModel):
    user_id: str
    kyc_approved: bool = False
    sub_workflow_results: Dict[str, Any] = {}  # Separate namespace

# After child completes
def process_kyc_results(state: OnboardingState):
    kyc_data = state.sub_workflow_results["KYC_Workflow"]  # Nested access
    state.kyc_approved = kyc_data["approved"]
```

**Inline Injection (Your Proposal):**
```python
# Shared state
class OnboardingState(BaseModel):
    user_id: str
    # KYC fields accessible directly
    identity_verified: bool = False
    address_verified: bool = False
    credit_score: int = 0
    kyc_approved: bool = False

# After injected steps complete
def process_kyc_results(state: OnboardingState):
    # Direct access - cleaner!
    state.kyc_approved = state.credit_score > 600
```

**Winner: Inline Injection** ✅
- Simpler state model (flat vs nested)
- No merging logic needed
- Fewer race conditions (single state object)

---

### 2. **Race Conditions & Concurrency**

**Separate Sub-Workflow:**

**Problem Scenario:**
```python
# Parent saves state
parent.status = "PENDING_SUB_WORKFLOW"
save_workflow_state(parent.id, parent)  # Write 1

# Child executes async
child.run()
save_workflow_state(child.id, child)  # Write 2 (different row)

# Child completes and tries to resume parent
parent_reloaded = load_workflow_state(parent.id)  # Read 1

# RACE CONDITION: What if parent was modified between pause and resume?
# e.g., manual intervention, timeout handler, etc.
parent_reloaded.state.sub_workflow_results = child.state.dict()
save_workflow_state(parent.id, parent_reloaded)  # Write 3 - might overwrite changes!
```

**Inline Injection:**

No race condition possible:
```python
# Single workflow instance
workflow.current_step = 2
workflow.inject_steps([step_2a, step_2b, step_2c])
save_workflow_state(workflow.id, workflow)  # Single atomic write

# All subsequent steps operate on same workflow instance
# No merging, no separate processes
```

**Winner: Inline Injection** ✅
- Single source of truth
- No cross-workflow synchronization
- Atomic operations on single row

---

### 3. **Debugging & Observability**

**Separate Sub-Workflow:**

**Debugging Session:**
```
Q: Why did workflow abc123 fail?
A: Let me check... it was waiting on child workflow xyz789

Q: What happened to xyz789?
A: [searches separate workflow table] Found it - it failed at step 2

Q: What was the state when it failed?
A: [loads child state] Here's the child state...

Q: What was the parent state at that time?
A: [loads parent state] Here's the parent state...

Q: How do these relate?
A: [manually correlates data] The child's input came from parent's field X...
```

**Inline Injection:**

**Debugging Session:**
```
Q: Why did workflow abc123 fail?
A: [loads single workflow] Failed at step "Verify_Address" (injected from KYC)

Q: What was the complete state?
A: [single state object] Here's everything in one place

Q: What led to this failure?
A: [trace back through execution log of single workflow] Clear linear history
```

**Winner: Inline Injection** ✅
- Single workflow ID to track
- Linear execution history
- No parent-child correlation needed

---

### 4. **Failure Recovery & Saga Rollback**

**Separate Sub-Workflow:**

**Failure Scenario:**
```python
# Child fails at step 2
child.status = "FAILED"

# Who triggers rollback?
# Option A: Child rolls back its own steps (partial rollback)
# Option B: Parent detects child failure and rolls back everything (complex)

# What if parent already executed steps after launching child?
# e.g., Parent sent notification email while child was running
# Now child fails - do we rollback parent's actions too?
```

**Saga rollback is ambiguous** - unclear boundaries.

**Inline Injection:**

**Failure Scenario:**
```python
# Workflow fails at injected step 2b
workflow.status = "FAILED"

if workflow.saga_mode:
    # Clear rollback boundary: all completed steps in completed_steps_stack
    workflow._execute_saga_rollback()
    # Rolls back: Step 1, Step 2, Step 2a, Step 2b (in reverse)
```

**Winner: Inline Injection** ✅
- Clear rollback scope (single workflow boundary)
- No ambiguity about what to undo
- Simpler saga logic

---

### 5. **Async Task Handling**

**Separate Sub-Workflow:**

**Complex orchestration:**
```python
# Parent dispatches child
execute_sub_workflow.delay(child_id, parent_id)

# Child might have async steps
child.next_step() → PENDING_ASYNC
# Celery task for child's async step

# Child resumes
resume_from_async_task.delay(child_id, ...)

# Child completes
resume_parent_from_child.delay(parent_id, child_id)

# Parent resumes and might hit another async step
resume_from_async_task.delay(parent_id, ...)
```

**4+ Celery tasks for single conceptual operation!**

**Inline Injection:**

**Simple orchestration:**
```python
# Workflow hits async step (whether original or injected)
dispatch_async_task.delay(workflow_id, step_index)

# Async completes
resume_from_async_task.delay(workflow_id, step_index)

# Same mechanism for all steps
```

**Winner: Inline Injection** ✅
- Fewer Celery tasks
- Simpler task chaining
- Lower latency (no parent→child→parent hops)

---

### 6. **Reusability & Modularity**

**Separate Sub-Workflow:**

**Benefit:** True isolation
```python
# KYC workflow can be:
# - Tested independently
# - Versioned separately
# - Deployed independently
# - Reused by multiple parents without coupling

# Different parents can have different KYC implementations
Parent A → KYC_Basic
Parent B → KYC_Enhanced
Parent C → KYC_International
```

**Inline Injection:**

**Challenge:** Coupling
```python
# Injected steps share parent's state model
# State model must accommodate all possible injections

class OnboardingState(BaseModel):
    # Original fields
    user_id: str
    name: str
    
    # KYC fields (even if not always used)
    identity_verified: Optional[bool] = None
    credit_score: Optional[int] = None
    
    # Fraud check fields (different injection)
    fraud_score: Optional[float] = None
    
    # State model grows with every possible injection!
```

**Winner: Separate Sub-Workflow** ✅
- Better separation of concerns
- Easier to version sub-workflows independently
- More reusable across different contexts

---

### 7. **Regional Data Sovereignty**

**Separate Sub-Workflow:**

**Cross-region capability:**
```python
# Parent in US
parent.data_region = "us-east-1"

# Child in EU (for GDPR compliance)
raise StartSubWorkflowDirective(
    workflow_type="GDPR_Processing",
    initial_data={"user_id": user_id},
    data_region="eu-central-1"  # ← Different region!
)

# Child executes on EU workers
# Only metadata crosses border
```

**Inline Injection:**

**Same-region only:**
```python
# All steps execute in same region
# Can't have US parent inject EU-only steps
# Would violate data sovereignty requirements
```

**Winner: Separate Sub-Workflow** ✅
- Enables true "Planetary Nervous System"
- Supports data residency requirements
- Critical for GDPR/HIPAA compliance

---

### 8. **Performance & Scalability**

**Separate Sub-Workflow:**

**Database writes:**
- Parent save: 1 write
- Child create: 1 write
- Child updates: N writes (per step)
- Child complete: 1 write
- Parent resume: 1 write
- **Total: N + 4 writes**

**Inline Injection:**

**Database writes:**
- Inject steps: 1 write
- Execute steps: N writes (per step)
- **Total: N + 1 writes**

**Winner: Inline Injection** ✅
- 3 fewer database writes
- Lower latency (no inter-workflow hops)
- Better throughput

---

## The Hybrid Approach: Best of Both Worlds

After this analysis, I recommend a **hybrid solution** that gives you the option:

### Implementation

**Add new directive: `InlineSubWorkflowSteps`**

```python
# workflow/workflow.py

class InlineSubWorkflowSteps(Exception):
    """Inject sub-workflow steps inline instead of creating separate workflow"""
    def __init__(
        self, 
        workflow_type: str, 
        initial_data: Dict[str, Any],
        state_mapping: Optional[Dict[str, str]] = None  # Map child state → parent state
    ):
        self.workflow_type = workflow_type
        self.initial_data = initial_data
        self.state_mapping = state_mapping or {}
        super().__init__(f"Inlining sub-workflow: {workflow_type}")


# Add to Workflow class
def _inline_sub_workflow_steps(self, directive: InlineSubWorkflowSteps):
    """Inject sub-workflow steps into current workflow"""
    from .workflow_loader import workflow_builder
    
    # Load sub-workflow definition
    sub_workflow_config = workflow_builder.get_workflow_config(directive.workflow_type)
    sub_steps_config = sub_workflow_config.get("steps", [])
    
    # Build step objects
    from .workflow_loader import _build_steps_from_config
    sub_steps = _build_steps_from_config(sub_steps_config)
    
    # Prefix step names to avoid conflicts
    for i, step in enumerate(sub_steps):
        step.name = f"[{directive.workflow_type}]_{step.name}"
        sub_steps_config[i]['name'] = step.name
    
    # Inject after current step
    insert_position = self.current_step + 1
    self.workflow_steps[insert_position:insert_position] = sub_steps
    self.steps_config[insert_position:insert_position] = sub_steps_config
    
    # Copy initial_data into parent state (with mapping)
    for child_key, parent_key in directive.state_mapping.items():
        if child_key in directive.initial_data:
            setattr(self.state, parent_key, directive.initial_data[child_key])
    
    return {"message": f"Injected {len(sub_steps)} steps from {directive.workflow_type}"}


# Handle in next_step method
def next_step(self, user_input: Dict[str, Any]):
    # ... existing code ...
    
    try:
        result = step.func(**kwargs)
        # ... existing processing ...
        
    except InlineSubWorkflowSteps as inline_directive:
        # NEW: Handle inline injection
        result = self._inline_sub_workflow_steps(inline_directive)
        return result, self.current_step_name
    
    except StartSubWorkflowDirective as sub_directive:
        # Existing: Handle as separate workflow
        return self._start_sub_workflow(sub_directive)
```

### Usage: Developer Chooses Best Approach

**Option 1: Inline (for simple, same-region sub-processes)**

```python
def run_credit_checks(state: LoanState):
    """Inline credit checks - simpler, faster"""
    raise InlineSubWorkflowSteps(
        workflow_type="CreditCheck",
        initial_data={"user_id": state.user_id},
        state_mapping={
            "credit_score": "credit_score",  # Map child field → parent field
            "bureau_data": "credit_bureau_data"
        }
    )
```

**Benefits:**
- ✅ Simpler debugging (single workflow)
- ✅ Faster execution (no separate workflow overhead)
- ✅ Clearer saga rollback
- ✅ Direct state access

**Option 2: Separate (for complex, cross-region, or reusable sub-processes)**

```python
def run_gdpr_processing(state: OnboardingState):
    """Separate workflow - required for data sovereignty"""
    raise StartSubWorkflowDirective(
        workflow_type="GDPR_Processing",
        initial_data={"user_id": state.user_id},
        data_region="eu-central-1"  # ← Must execute in EU
    )
```

**Benefits:**
- ✅ Regional data sovereignty
- ✅ Independent versioning
- ✅ True reusability
- ✅ Isolated testing

---

## Decision Matrix: When to Use Each Approach

| Criteria | Inline Injection | Separate Sub-Workflow |
|----------|------------------|----------------------|
| **Same region execution** | ✅ Better | ⚠️ Works but overkill |
| **Cross-region execution** | ❌ Not possible | ✅ Required |
| **Simple sub-process (< 5 steps)** | ✅ Better | ⚠️ Too complex |
| **Complex sub-process (10+ steps)** | ⚠️ Makes parent hard to read | ✅ Better isolation |
| **Shared by multiple parents** | ⚠️ Requires compatible state | ✅ Fully reusable |
| **Debugging complexity** | ✅ Simple (1 workflow) | ⚠️ Complex (2+ workflows) |
| **Saga rollback** | ✅ Clear boundaries | ⚠️ Ambiguous |
| **Performance** | ✅ Faster | ⚠️ More overhead |
| **State management** | ✅ Direct access | ⚠️ Nested merging |
| **Testing** | ⚠️ Coupled to parent | ✅ Isolated |
| **Async step handling** | ✅ Simple | ⚠️ Complex |

---

## Recommended Guidelines

### Use **Inline Injection** when:
1. Sub-process has < 5 steps
2. Execution is in the same region
3. Sub-process is specific to this parent workflow
4. Performance is critical
5. You need clear saga rollback boundaries
6. State sharing is straightforward

**Example:** Credit score calculation, email sending, simple validations

### Use **Separate Sub-Workflow** when:
1. Cross-region execution required (GDPR, data sovereignty)
2. Sub-process is reused by 3+ different workflows
3. Sub-process has complex logic (10+ steps)
4. Independent versioning needed
5. Testing isolation is important
6. Sub-process might run for hours (long-running)

**Example:** KYC verification, fraud detection, compliance reviews

---

## Implementation Priority

### Phase 1 (Week 3-4): Add Inline Injection
```python
# Implement InlineSubWorkflowSteps directive
# Add _inline_sub_workflow_steps method
# Update documentation with decision matrix
```

### Phase 2 (Week 5-6): Refactor Existing Examples
```python
# Convert simple sub-workflows to inline
# Keep complex/cross-region as separate
# A/B test performance improvements
```

### Phase 3 (Week 7-8): Dashboard Visualization
```python
# Show injected steps in workflow graph
# Mark them visually: [SubWorkflow]_StepName
# Add filter: "Show/Hide Injected Steps"
```

---

## Final Verdict

**You're absolutely right** that inline injection solves many problems:
- ✅ Eliminates state merging complexity
- ✅ Removes race conditions
- ✅ Simplifies debugging
- ✅ Clearer saga boundaries
- ✅ Better performance

**But separate sub-workflows are still needed for:**
- ❗ Cross-region data sovereignty (THE key differentiator)
- ❗ True reusability across diverse parents
- ❗ Independent versioning/deployment

**Recommendation:** Implement the **hybrid approach** and let developers choose based on the decision matrix. Default to inline injection for simplicity, use separate sub-workflows only when truly necessary.

This gives you:
1. **Simple cases**: Fast, debuggable inline injection
2. **Complex cases**: Powerful separate sub-workflow orchestration
3. **"Planetary" cases**: Regional sovereignty via separate execution


# Complete Hybrid Sub-Workflow Implementation

I'll provide the full implementation of the hybrid approach with both inline injection and separate sub-workflow support.

---

## Part 1: Core Implementation

### File: `workflow/workflow.py` (COMPLETE UPDATED VERSION)

```python
from pydantic import BaseModel, ValidationError
from typing import Dict, Any, Optional, List, Callable, Type
import uuid
import importlib
import os
import time
import traceback


class WorkflowStep:
    def __init__(self, name: str, func: Callable, required_input: List[str] = None, 
                 input_schema: Optional[Type[BaseModel]] = None, automate_next: bool = False):
        self.name = name
        self.func = func
        self.required_input = required_input or []
        self.input_schema = input_schema
        self.automate_next = automate_next


class WorkflowJumpDirective(Exception):
    def __init__(self, target_step_name: str):
        self.target_step_name = target_step_name
        super().__init__(f"Jumping to step: {target_step_name}")


class WorkflowNextStepDirective:
    def __init__(self, next_step_name: str):
        self.next_step_name = next_step_name


class WorkflowPauseDirective(Exception):
    def __init__(self, result: Dict[str, Any]):
        self.result = result
        super().__init__("Workflow paused for external input")


# ============================================================================
# NEW: Inline Sub-Workflow Directive
# ============================================================================

class InlineSubWorkflowSteps(Exception):
    """
    Inject sub-workflow steps inline instead of creating separate workflow.
    
    Use this when:
    - Sub-process is simple (< 5 steps)
    - Same-region execution
    - Direct state access needed
    - Performance is critical
    
    Example:
        raise InlineSubWorkflowSteps(
            workflow_type="CreditCheck",
            initial_data={"user_id": state.user_id},
            state_mapping={"credit_score": "credit_score"}
        )
    """
    def __init__(
        self, 
        workflow_type: str, 
        initial_data: Dict[str, Any],
        state_mapping: Optional[Dict[str, str]] = None,
        prefix_steps: bool = True
    ):
        self.workflow_type = workflow_type
        self.initial_data = initial_data
        self.state_mapping = state_mapping or {}
        self.prefix_steps = prefix_steps
        super().__init__(f"Inlining sub-workflow: {workflow_type}")


# ============================================================================
# EXISTING: Separate Sub-Workflow Directive
# ============================================================================

class StartSubWorkflowDirective(Exception):
    """
    Create separate sub-workflow instance (existing behavior).
    
    Use this when:
    - Cross-region execution required
    - Sub-process is reused by multiple workflows
    - Independent versioning needed
    - Complex logic (10+ steps)
    
    Example:
        raise StartSubWorkflowDirective(
            workflow_type="GDPR_Processing",
            initial_data={"user_id": state.user_id},
            data_region="eu-central-1"
        )
    """
    def __init__(
        self, 
        workflow_type: str, 
        initial_data: Dict[str, Any],
        data_region: str = None
    ):
        self.workflow_type = workflow_type
        self.initial_data = initial_data
        self.data_region = data_region
        super().__init__(f"Starting sub-workflow: {workflow_type}")


# ============================================================================
# Saga Pattern Support
# ============================================================================

class SagaWorkflowException(Exception):
    """Raised when a saga needs to rollback"""
    def __init__(self, failed_step: str, original_error: Exception):
        self.failed_step = failed_step
        self.original_error = original_error
        super().__init__(f"Saga failed at {failed_step}: {original_error}")


class CompensatableStep(WorkflowStep):
    """WorkflowStep with compensation logic for saga pattern"""
    
    def __init__(
        self,
        name: str,
        func: Callable,
        compensate_func: Optional[Callable] = None,
        required_input: list = None,
        input_schema: Optional[Type[BaseModel]] = None,
        automate_next: bool = False
    ):
        super().__init__(name, func, required_input, input_schema, automate_next)
        self.compensate_func = compensate_func
        self.compensation_executed = False
    
    def compensate(self, state: BaseModel) -> Dict[str, Any]:
        """Execute compensation if available"""
        if not self.compensate_func:
            return {"message": f"No compensation defined for {self.name}"}
        
        if self.compensation_executed:
            return {"message": f"Compensation already executed for {self.name}"}
        
        try:
            result = self.compensate_func(state=state)
            self.compensation_executed = True
            return result
        except Exception as e:
            return {"error": f"Compensation failed: {str(e)}"}


# ============================================================================
# Async Workflow Steps
# ============================================================================

class AsyncWorkflowStep(WorkflowStep):
    def __init__(self, name: str, func_path: str, required_input: List[str] = None, 
                 input_schema: Optional[Type[BaseModel]] = None, automate_next: bool = False):
        super().__init__(name, None, required_input, input_schema, automate_next=automate_next)
        self.func_path = func_path

    def dispatch_async_task(self, state: BaseModel, workflow_id: str, current_step_index: int, **kwargs):
        from .tasks import resume_from_async_task
        from celery import chain

        module_path, func_name = self.func_path.rsplit('.', 1)
        module = importlib.import_module(module_path)
        task_func = getattr(module, func_name)
        
        task_payload = state.model_dump()
        task_payload.update(kwargs)

        task_chain = chain(
            task_func.s(task_payload),
            resume_from_async_task.s(workflow_id=workflow_id, current_step_index=current_step_index)
        )
        
        async_result = task_chain.apply_async()

        if hasattr(state, 'async_task_id'):
            state.async_task_id = async_result.id

        return {"_async_dispatch": True, "message": f"Async task {func_name} dispatched.", "task_id": async_result.id}


class ParallelExecutionTask:
    def __init__(self, name: str, func_path: str):
        self.name = name
        self.func_path = func_path

    def to_dict(self):
        return {"name": self.name, "func_path": self.func_path}


class ParallelWorkflowStep(WorkflowStep):
    def __init__(self, name: str, tasks: List[ParallelExecutionTask], 
                 merge_function_path: str = None, automate_next: bool = False):
        super().__init__(name=name, func=self.dispatch_parallel_tasks, automate_next=automate_next)
        self.tasks = tasks
        self.merge_function_path = merge_function_path

    def dispatch_parallel_tasks(self, state: BaseModel, workflow_id: str, current_step_index: int):
        from .tasks import merge_and_resume_parallel_tasks
        from celery import group, chain
        
        TESTING = os.environ.get("TESTING", "False").lower() == "true"

        celery_tasks = []
        for task_def in self.tasks:
            module_path, func_name = task_def.func_path.rsplit('.', 1)
            module = importlib.import_module(module_path)
            task_func = getattr(module, func_name)
            celery_tasks.append(task_func.s(state.model_dump()))

        task_group = group(celery_tasks)
        
        if TESTING:
            result_group = task_group.apply()
            results = result_group.get()
            
            if self.merge_function_path:
                module_path, func_name = self.merge_function_path.rsplit('.', 1)
                module = importlib.import_module(module_path)
                merge_function = getattr(module, func_name)
                merged_results = merge_function(results)
            else:
                merged_results = {}
                for res in results:
                    if isinstance(res, dict):
                        merged_results.update(res)

            return {"_sync_parallel_result": merged_results}
        else:
            callback = merge_and_resume_parallel_tasks.s(
                workflow_id=workflow_id, 
                current_step_index=current_step_index,
                merge_function_path=self.merge_function_path
            )
            chain(task_group, callback).apply_async()

            return {"_async_dispatch": True, "message": "Parallel tasks dispatched."}


# ============================================================================
# Main Workflow Class
# ============================================================================

class Workflow:
    def __init__(self, id: str = None, workflow_steps: List[WorkflowStep] = None, 
                 initial_state_model: BaseModel = None, workflow_type: str = None, 
                 steps_config: List[Dict[str, Any]] = None, state_model_path: str = None):
        self.id = id or str(uuid.uuid4())
        self.workflow_steps = workflow_steps or []
        self.current_step = 0
        self.state = initial_state_model
        self.status = "ACTIVE"
        self.workflow_type = workflow_type
        self.steps_config = steps_config or []
        self.state_model_path = state_model_path
        
        # Saga support
        self.completed_steps_stack = []
        self.saga_mode = False
        
        # Sub-workflow support
        self.parent_execution_id = None
        self.blocked_on_child_id = None
        
        # Inline injection tracking
        self.injected_workflows = []  # Track which workflows were inlined
        
        # Metadata
        self.priority = 5
        self.data_region = 'us-east-1'
        self.created_by_user_id = None
        self.organization_id = None
        self.worker_id = None

    @property
    def current_step_name(self) -> Optional[str]:
        if 0 <= self.current_step < len(self.workflow_steps):
            return self.workflow_steps[self.current_step].name
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "workflow_type": self.workflow_type,
            "current_step": self.current_step,
            "status": self.status,
            "state": self.state.model_dump() if self.state else {},
            "steps_config": self.steps_config,
            "state_model_path": self.state_model_path
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]):
        from .workflow_loader import _build_steps_from_config, _import_from_string
        
        workflow_type = data.get("workflow_type")
        state_model_path = data.get("state_model_path")
        if not workflow_type or not state_model_path:
            raise ValueError("Missing workflow_type or state_model_path in data.")

        try:
            state_model_class = _import_from_string(state_model_path)
            steps_config = data.get('steps_config', [])
            workflow_steps = _build_steps_from_config(steps_config)
        except (ValueError, ImportError) as e:
            raise ValueError(f"Could not load workflow configuration for type '{workflow_type}': {e}")

        instance = Workflow(
            id=data["id"], 
            workflow_steps=workflow_steps, 
            workflow_type=workflow_type, 
            steps_config=steps_config,
            state_model_path=state_model_path
        )
        instance.current_step = data["current_step"]
        instance.status = data["status"]
        
        if "state" in data and data["state"]:
            instance.state = state_model_class(**data["state"])
            
        return instance

    def enable_saga_mode(self):
        """Enable automatic rollback on failure"""
        self.saga_mode = True
        return self

    def _get_nested_state_value(self, key_path: str):
        keys = key_path.split('.')
        value = self.state
        for key in keys:
            if hasattr(value, key):
                value = getattr(value, key)
            elif isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return None
        return value

    def _process_dynamic_injection(self):
        from .workflow_loader import _build_steps_from_config as builder_func

        if not (0 <= self.current_step < len(self.steps_config)):
            return False

        current_step_config = self.steps_config[self.current_step]
        injection_block = current_step_config.get('dynamic_injection')
        if not injection_block:
            return False

        injection_occurred = False
        rules = injection_block.get('rules', [])
        for rule in rules:
            condition_key = rule.get('condition_key')
            expected_value = rule.get('value_match')
            excluded_values = rule.get('value_is_not')
            value_greater_than = rule.get('value_greater_than')
            value_less_than = rule.get('value_less_than')
            value_between = rule.get('value_between')

            action = rule.get('action')
            steps_to_insert_config = rule.get('steps_to_insert')

            if not all([condition_key, action, steps_to_insert_config]):
                continue

            actual_value = self._get_nested_state_value(condition_key)

            condition_met = False
            
            if expected_value is not None:
                condition_met = (actual_value == expected_value)
            elif excluded_values is not None:
                condition_met = (actual_value not in excluded_values)
            elif value_greater_than is not None:
                condition_met = (actual_value is not None and actual_value > value_greater_than)
            elif value_less_than is not None:
                condition_met = (actual_value is not None and actual_value < value_less_than)
            elif value_between is not None:
                if isinstance(value_between, list) and len(value_between) == 2:
                    min_val, max_val = value_between
                    condition_met = (actual_value is not None and min_val <= actual_value <= max_val)
            
            if condition_met:
                new_steps = builder_func(steps_to_insert_config)
                
                if action == 'INSERT_AFTER_CURRENT':
                    insert_at = self.current_step + 1
                    self.steps_config[insert_at:insert_at] = steps_to_insert_config
                    self.workflow_steps[insert_at:insert_at] = new_steps
                    injection_occurred = True

        return injection_occurred

    # ========================================================================
    # NEW: Inline Sub-Workflow Injection
    # ========================================================================

    def _inline_sub_workflow_steps(self, directive: InlineSubWorkflowSteps):
        """
        Inject sub-workflow steps inline into current workflow.
        
        This avoids creating a separate workflow instance and simplifies:
        - State management (direct access vs. nested sub_workflow_results)
        - Debugging (single workflow to trace)
        - Saga rollback (clear boundary)
        - Performance (fewer DB writes, no inter-workflow coordination)
        """
        from .workflow_loader import workflow_builder, _build_steps_from_config
        
        print(f"[INLINE] Injecting steps from {directive.workflow_type} into {self.workflow_type}")
        
        # Load sub-workflow definition
        try:
            sub_workflow_config = workflow_builder.get_workflow_config(directive.workflow_type)
        except ValueError as e:
            raise ValueError(f"Cannot inline sub-workflow '{directive.workflow_type}': {e}")
        
        sub_steps_config = sub_workflow_config.get("steps", [])
        
        if not sub_steps_config:
            return {"message": f"Sub-workflow {directive.workflow_type} has no steps to inject"}
        
        # Build step objects from config
        sub_steps = _build_steps_from_config(sub_steps_config)
        
        # Prefix step names to avoid conflicts (optional but recommended)
        if directive.prefix_steps:
            for i, step in enumerate(sub_steps):
                original_name = step.name
                step.name = f"[{directive.workflow_type}]_{original_name}"
                sub_steps_config[i]['name'] = step.name
                
                # Update dependencies to use prefixed names
                if 'dependencies' in sub_steps_config[i]:
                    sub_steps_config[i]['dependencies'] = [
                        f"[{directive.workflow_type}]_{dep}" for dep in sub_steps_config[i]['dependencies']
                    ]
        
        # Insert steps after current step
        insert_position = self.current_step + 1
        self.workflow_steps[insert_position:insert_position] = sub_steps
        self.steps_config[insert_position:insert_position] = sub_steps_config
        
        # Map initial_data into parent state
        for child_key, parent_key in directive.state_mapping.items():
            if child_key in directive.initial_data:
                value = directive.initial_data[child_key]
                if hasattr(self.state, parent_key):
                    setattr(self.state, parent_key, value)
                else:
                    # Dynamic field addition (use with caution)
                    self.state.__dict__[parent_key] = value
        
        # Track injection for audit/debugging
        self.injected_workflows.append({
            'workflow_type': directive.workflow_type,
            'injected_at_step': self.current_step,
            'num_steps_injected': len(sub_steps),
            'step_names': [s.name for s in sub_steps]
        })
        
        print(f"[INLINE] Injected {len(sub_steps)} steps from {directive.workflow_type}")
        
        return {
            "message": f"Injected {len(sub_steps)} steps from {directive.workflow_type}",
            "injected_steps": [s.name for s in sub_steps],
            "insert_position": insert_position
        }

    # ========================================================================
    # EXISTING: Separate Sub-Workflow Execution
    # ========================================================================

    def _start_sub_workflow(self, directive: StartSubWorkflowDirective):
        """Launch child workflow and pause parent (existing behavior)"""
        from .workflow_loader import workflow_builder
        from .persistence import save_workflow_state
        
        print(f"[SUB-WORKFLOW] Starting separate workflow {directive.workflow_type}")
        
        child = workflow_builder.create_workflow(
            workflow_type=directive.workflow_type,
            initial_data=directive.initial_data
        )
        child.parent_execution_id = self.id
        
        if directive.data_region:
            child.data_region = directive.data_region
        else:
            child.data_region = self.data_region
        
        self.status = "PENDING_SUB_WORKFLOW"
        self.blocked_on_child_id = child.id
        save_workflow_state(self.id, self)
        save_workflow_state(child.id, child)
        
        from .tasks import execute_sub_workflow
        execute_sub_workflow.delay(child.id, self.id)
        
        return {
            "message": f"Sub-workflow {directive.workflow_type} started",
            "child_workflow_id": child.id,
            "execution_mode": "separate"
        }, None

    # ========================================================================
    # Saga Rollback
    # ========================================================================

    def _execute_saga_rollback(self):
        """Compensate all completed steps in reverse order"""
        from .persistence import save_workflow_state
        
        print(f"[SAGA] Rolling back {len(self.completed_steps_stack)} steps for workflow {self.id}...")
        
        for entry in reversed(self.completed_steps_stack):
            step_index = entry['step_index']
            step = self.workflow_steps[step_index]
            
            if isinstance(step, CompensatableStep) and step.compensate_func:
                try:
                    compensation_result = step.compensate(self.state)
                    print(f"[SAGA] Compensated {step.name}: {compensation_result}")
                    
                    if hasattr(self.state, 'saga_log'):
                        if not isinstance(self.state.saga_log, list):
                            self.state.saga_log = []
                        self.state.saga_log.append({
                            'step': step.name,
                            'action': 'COMPENSATE',
                            'result': compensation_result,
                            'timestamp': time.time()
                        })
                    
                except Exception as comp_error:
                    print(f"[SAGA] Compensation failed for {step.name}: {comp_error}")
                    print(f"[SAGA] Traceback: {traceback.format_exc()}")
        
        save_workflow_state(self.id, self)
        print(f"[SAGA] Rollback completed for workflow {self.id}")

    # ========================================================================
    # Main Execution Logic
    # ========================================================================

    def next_step(self, user_input: Dict[str, Any]) -> (Dict[str, Any], Optional[str]):
        if self.current_step >= len(self.workflow_steps):
            self.status = "COMPLETED"
            return {"status": "Workflow completed"}, None

        step = self.workflow_steps[self.current_step]
        
        # Input validation
        kwargs = {}
        try:
            if step.input_schema:
                validated_model = step.input_schema(**user_input)
                kwargs = validated_model.model_dump()
            else:
                if step.required_input:
                    for key in step.required_input:
                        if key not in user_input:
                            raise ValueError(f"Missing required input for step '{step.name}': {key}")
                kwargs = user_input.copy()
        except ValidationError as e:
            raise ValueError(f"Invalid input for step '{step.name}': {e}")

        try:
            kwargs['state'] = self.state
            
            # Snapshot state before execution (for saga)
            state_snapshot_before = self.state.model_copy() if self.saga_mode else None
            
            # Execute step based on type
            if isinstance(step, AsyncWorkflowStep):
                kwargs['workflow_id'] = self.id
                kwargs['current_step_index'] = self.current_step
                result = step.dispatch_async_task(**kwargs)
            elif isinstance(step, ParallelWorkflowStep):
                result = step.dispatch_parallel_tasks(
                    state=self.state, 
                    workflow_id=self.id, 
                    current_step_index=self.current_step
                )
            else:
                result = step.func(**kwargs)
            
            is_async_dispatch = isinstance(result, dict) and result.get("_async_dispatch")

            if is_async_dispatch:
                self.status = "PENDING_ASYNC"
                
                if os.environ.get("TESTING", "False").lower() == "true":
                    from .persistence import load_workflow_state
                    reloaded_workflow = load_workflow_state(self.id)
                    if reloaded_workflow:
                        self.__dict__.update(reloaded_workflow.__dict__)
                    return result, self.current_step_name
                
                return result, None

            # Process result
            if isinstance(result, dict):
                if "_sync_parallel_result" in result:
                    merged_result = result["_sync_parallel_result"]
                    for key, value in merged_result.items():
                        if hasattr(self.state, key):
                             setattr(self.state, key, value)
                
                for key, value in result.items():
                    if hasattr(self.state, key) and not key.startswith('_'):
                        setattr(self.state, key, value)

            # Record successful step for saga rollback
            if self.saga_mode and isinstance(step, CompensatableStep):
                self.completed_steps_stack.append({
                    'step_index': self.current_step,
                    'step_name': step.name,
                    'state_snapshot': state_snapshot_before.model_dump()
                })

            if isinstance(result, WorkflowNextStepDirective):
                try:
                    target_index = next(i for i, s in enumerate(self.workflow_steps) 
                                      if s.name == result.next_step_name)
                    self.current_step = target_index
                    return {"message": f"Dynamically routing to step {result.next_step_name}"}, self.current_step_name
                except StopIteration:
                    raise ValueError(f"Dynamic route target step '{result.next_step_name}' not found.")

            injection_occurred = self._process_dynamic_injection()
            if injection_occurred and isinstance(result, dict):
                result.setdefault("message", "")
                result["message"] += " (Note: Dynamic steps were injected.)"
            
            just_completed_step_index = self.current_step
            self.current_step += 1

            if self.current_step >= len(self.workflow_steps):
                self.status = "COMPLETED"
                return result, None
            
            next_step_name = self.workflow_steps[self.current_step].name

            should_automate = self.workflow_steps[just_completed_step_index].automate_next
            
            if should_automate and self.status == "ACTIVE":
                next_input = result if isinstance(result, dict) else {}
                return self.next_step(user_input=next_input)

            return result, next_step_name

        # ====================================================================
        # NEW: Handle inline injection directive
        # ====================================================================
        except InlineSubWorkflowSteps as inline_directive:
            result = self._inline_sub_workflow_steps(inline_directive)
            # Don't advance current_step - injected steps will execute next
            return result, self.current_step_name

        # ====================================================================
        # EXISTING: Handle separate sub-workflow directive
        # ====================================================================
        except StartSubWorkflowDirective as sub_directive:
            return self._start_sub_workflow(sub_directive)

        except WorkflowJumpDirective as e:
            try:
                target_index = next(i for i, s in enumerate(self.workflow_steps) 
                                  if s.name == e.target_step_name)
                self.current_step = target_index
                return {"message": f"Jumped to step {e.target_step_name}"}, self.current_step_name
            except StopIteration:
                raise ValueError(f"Jump target step '{e.target_step_name}' not found.")
        
        except WorkflowPauseDirective as e:
            self.status = "WAITING_HUMAN"
            return e.result, self.current_step_name
        
        # Saga rollback on failure
        except Exception as e:
            if self.saga_mode and self.completed_steps_stack:
                self._execute_saga_rollback()
                self.status = "FAILED_ROLLED_BACK"
                raise SagaWorkflowException(step.name, e)
            else:
                self.status = "FAILED"
                raise
```

---

## Part 2: YAML Configuration Syntax

### File: `docs/YAML_SUB_WORKFLOW_PATTERNS.md`

```markdown
# Sub-Workflow Configuration Patterns

## Pattern 1: Inline Sub-Workflow (NEW)

**Use when:** Simple, same-region, performance-critical

```yaml
workflow_type: "LoanApplication"
steps:
  - name: "Collect_Application"
    type: "STANDARD"
    function: "workflow_utils.collect_application"
  
  - name: "Run_Credit_Check_Inline"
    type: "STANDARD"
    function: "workflow_utils.trigger_credit_check_inline"
    # This function raises InlineSubWorkflowSteps
  
  # Steps from CreditCheck workflow are injected here at runtime
  # They appear as: [CreditCheck]_Check_Identity, [CreditCheck]_Verify_Address, etc.
  
  - name: "Evaluate_Results"
    type: "STANDARD"
    function: "workflow_utils.evaluate_results"
    # Can directly access credit_score from state
```

**Python Implementation:**

```python
from workflow.workflow import InlineSubWorkflowSteps

def trigger_credit_check_inline(state: LoanState, **kwargs):
    """Inline credit check - steps injected into main workflow"""
    raise InlineSubWorkflowSteps(
        workflow_type="CreditCheck",
        initial_data={
            "user_id": state.user_id,
            "ssn": state.ssn
        },
        state_mapping={
            # Map CreditCheck outputs to LoanApplication state
            "credit_score": "credit_score",
            "bureau_data": "credit_bureau_data"
        }
    )

def evaluate_results(state: LoanState, **kwargs):
    # Direct access to credit_score (no nested dict!)
    if state.credit_score > 700:
        state.loan_approved = True
    return {"approved": state.loan_approved}
```

---

## Pattern 2: Separate Sub-Workflow (EXISTING)

**Use when:** Cross-region, complex, reusable across workflows

```yaml
workflow_type: "CustomerOnboarding"
steps:
  - name: "Collect_Customer_Data"
    type: "STANDARD"
    function: "workflow_utils.collect_customer_data"
  
  - name: "Run_GDPR_Compliance"
    type: "STANDARD"
    function: "workflow_utils.trigger_gdpr_workflow"
    # This function raises StartSubWorkflowDirective
  
  # Workflow PAUSES here (PENDING_SUB_WORKFLOW status)
  # GDPR workflow runs separately in EU region
  # Parent resumes when child completes
  
  - name: "Process_Compliance_Results"
    type: "STANDARD"
    function: "workflow_utils.process_compliance_results"
    # Accesses state.sub_workflow_results["GDPR_Workflow"]
```

**Python Implementation:**

```python
from workflow.workflow import StartSubWorkflowDirective

def trigger_gdpr_workflow(state: OnboardingState, **kwargs):
    """Separate workflow - runs in EU region"""
    raise StartSubWorkflowDirective(
        workflow_type="GDPR_Workflow",
        initial_data={
            "customer_id": state.customer_id,
            "personal_data": state.personal_data
        },
        data_region="eu-central-1"  # ← Must execute in EU!
    )

def process_compliance_results(state: OnboardingState, **kwargs):
    # Nested access to sub-workflow results
    gdpr_results = state.sub_workflow_results.get("GDPR_Workflow", {})
    state.gdpr_compliant = gdpr_results.get("compliant", False)
    return {"compliant": state.gdpr_compliant}
```

---

Mixed Approach

**Use when:** Some sub-processes inline, others separate

```yaml
workflow_type: "OrderProcessing"
steps:
  - name: "Validate_Order"
    type: "STANDARD"
    function: "workflow_utils.validate_order"
  
  # INLINE: Simple validation (3 steps)
  - name: "Run_Inventory_Check"
    type: "STANDARD"
    function: "workflow_utils.inline_inventory_check"
  
  # SEPARATE: Complex fraud detection (10+ steps, ML models)
  - name: "Run_Fraud_Detection"
    type: "STANDARD"
    function: "workflow_utils.separate_fraud_workflow"
  
  - name: "Process_Payment"
    type: "STANDARD"
    function: "workflow_utils.process_payment"
```

---

## Decision Matrix

| Criteria | Use Inline | Use Separate |
|----------|-----------|--------------|
| **Steps** | < 5 steps | 10+ steps |
| **Region** | Same region | Cross-region |
| **Reusability** | Single parent | 3+ parents |
| **State Complexity** | Simple mapping | Complex isolation |
| **Performance** | Critical | Not critical |
| **Testing** | Coupled OK | Need isolation |
| **Debugging** | Prefer simple | Need separation |

---

## State Model Requirements

### For Inline Sub-Workflows

Parent state must accommodate injected fields:

```python
class LoanApplicationState(BaseModel):
    # Original fields
    user_id: str
    requested_amount: float
    
    # Fields for inline CreditCheck
    credit_score: Optional[int] = None
    credit_bureau_data: Optional[Dict] = None
    
    # Fields for inline FraudCheck
    fraud_score: Optional[float] = None
```

### For Separate Sub-Workflows

Parent state only needs results container:

```python
class CustomerOnboardingState(BaseModel):
    customer_id: str
    gdpr_compliant: bool = False
    
    # Generic container for all sub-workflow results
    sub_workflow_results: Dict[str, Any] = {}
```

---

## Advanced: Conditional Injection

Choose inline vs. separate based on runtime conditions:

```python
def adaptive_sub_workflow(state: LoanState, **kwargs):
    """Choose execution mode based on loan amount"""
    
    if state.requested_amount < 10000:
        # Small loan: inline for speed
        raise InlineSubWorkflowSteps(
            workflow_type="QuickCreditCheck",
            initial_data={"user_id": state.user_id}
        )
    else:
        # Large loan: separate for thorough review
        raise StartSubWorkflowDirective(
            workflow_type="ComprehensiveCreditCheck",
            initial_data={"user_id": state.user_id}
        )
```
```

---

## Part 3: Complete Examples

### Example 1: Simple Inline Workflow

**File: `config/loan_with_inline_credit_check.yaml`**

```yaml
workflow_type: "LoanWithInlineCredit"
description: "Loan application with inline credit check"

steps:
  - name: "Collect_Application"
    type: "STANDARD"
    function: "workflow_utils.collect_loan_application"
    required_input: ["applicant_name", "requested_amount"]
  
  - name: "Inline_Credit_Check"
    type: "STANDARD"
    function: "workflow_utils.inline_credit_check"
    # Injects: [CreditCheck]_Verify_Identity, [CreditCheck]_Check_Score
  
  - name: "Evaluate_Loan"
    type: "DECISION"
    function: "workflow_utils.evaluate_loan"
    # Direct access to credit_score
  
  - name: "Approve_Loan"
    type: "STANDARD"
    function: "workflow_utils.approve_loan"
  
  - name: "Decline_Loan"
    type: "STANDARD"
    function: "workflow_utils.decline_loan"
```

**Subworkflow Definition: `config/credit_check_workflow.yaml`**

```yaml
workflow_type: "CreditCheck"
description: "Credit check sub-workflow (can be inline or separate)"

steps:
  - name: "Verify_Identity"
    type: "STANDARD"
    function: "workflow_utils.verify_identity"
  
  - name: "Check_Score"
    type: "ASYNC"
    function: "workflow_utils.check_credit_score"
  
  - name: "Calculate_Risk"
    type: "STANDARD"
    function: "workflow_utils.calculate_risk"
```

**State Models:**

```python
from pydantic import BaseModel
from typing import Optional

class LoanWithInlineCreditState(BaseModel):
    # Application fields
    applicant_name: str = ""
    requested_amount: float = 0.0
    
    # Credit check fields (populated by inline injection)
    identity_verified: bool = False
    credit_score: Optional[int] = None
    risk_level: Optional[str] = None
    
    # Decision fields
    loan_approved: bool = False
    loan_id: Optional[str] = None


class CreditCheckState(BaseModel):
    """State for CreditCheck (used when run standalone OR inline)"""
    user_id: str = ""
    ssn: Optional[str] = None
    
    # Outputs
    identity_verified: bool = False
    credit_score: Optional[int] = None
    risk_level: Optional[str] = None
```

**Functions:**

```python
import uuid
from workflow.workflow import InlineSubWorkflowSteps, WorkflowJumpDirective

def collect_loan_application(state: LoanWithInlineCreditState, 
                             applicant_name: str,
                             requested_amount: float, **kwargs):
    state.applicant_name = applicant_name
    state.requested_amount = requested_amount
    return {"collected": True}


def inline_credit_check(state: LoanWithInlineCreditState, **kwargs):
    """Inline credit check - injects steps from CreditCheck workflow"""
    raise InlineSubWorkflowSteps(
        workflow_type="CreditCheck",
        initial_data={
            "user_id": state.applicant_name,  # Simplified
            "ssn": "123-45-6789"
        },
        state_mapping={
            # Map CreditCheck outputs → LoanWithInlineCreditState fields
            "identity_verified": "identity_verified",
            "credit_score": "credit_score",
            "risk_level": "risk_level"
        }
    )


def evaluate_loan(state: LoanWithInlineCreditState, **kwargs):
    """Decision step - direct access to credit_score"""
    if state.credit_score and state.credit_score > 700:
        raise WorkflowJumpDirective(target_step_name="Approve_Loan")
    else:
        raise WorkflowJumpDirective(target_step_name="Decline_Loan")


def approve_loan(state: LoanWithInlineCreditState, **kwargs):
    state.loan_approved = True
    state.loan_id = f"LOAN_{uuid.uuid4().hex[:8]}"
    return {"approved": True, "loan_id": state.loan_id}


def decline_loan(state: LoanWithInlineCreditState, **kwargs):
    state.loan_approved = False
    return {"approved": False, "reason": "Insufficient credit score"}


# CreditCheck functions (can be used standalone OR inline)
def verify_identity(state: CreditCheckState, **kwargs):
    # Simulate identity verification
    state.identity_verified = True
    return {"verified": True}


@celery_app.task
def check_credit_score(state: dict):
    # Simulate async credit bureau call
    import random, time
    time.sleep(2)
    score = random.randint(550, 850)
    return {"credit_score": score}


def calculate_risk(state: CreditCheckState, **kwargs):
    if state.credit_score:
        if state.credit_score > 750:
            state.risk_level = "LOW"
        elif state.credit_score > 650:
            state.risk_level = "MEDIUM"
        else:
            state.risk_level = "HIGH"
    return {"risk_level": state.risk_level}
```

**Register Both Workflows:**

```yaml
# config/workflow_registry.yaml
workflows:
  - type: "LoanWithInlineCredit"
    description: "Loan with inline credit check"
    config_file: "config/loan_with_inline_credit_check.yaml"
    initial_state_model: "state_models.LoanWithInlineCreditState"
  
  - type: "CreditCheck"
    description: "Credit check (standalone or inline)"
    config_file: "config/credit_check_workflow.yaml"
    initial_state_model: "state_models.CreditCheckState"
```

**API Usage:**

```bash
# Start loan workflow
curl -X POST http://localhost:8000/api/v1/workflow/start \
  -H "Content-Type: application/json" \
  -d '{
    "workflow_type": "LoanWithInlineCredit",
    "initial_data": {
      "applicant_name": "Alice Johnson",
      "requested_amount": 5000
    }
  }'

# Response: {"workflow_id": "abc-123", "current_step_name": "Collect_Application", "status": "ACTIVE"}

# Advance to first step
curl -X POST http://localhost:8000/api/v1/workflow/abc-123/next \
  -d '{"input_data": {}}'

# Response includes: "message": "Injected 3 steps from CreditCheck"
# Now workflow has: [CreditCheck]_Verify_Identity, [CreditCheck]_Check_Score, [CreditCheck]_Calculate_Risk

# Continue advancing - injected steps execute seamlessly
curl -X POST http://localhost:8000/api/v1/workflow/abc-123/next \
  -d '{"input_data": {}}'
```

---

### Example 2: Separate Sub-Workflow for Cross-Region

**File: `config/onboarding_with_gdpr.yaml`**

```yaml
workflow_type: "OnboardingWithGDPR"
description: "Customer onboarding with separate GDPR workflow (EU region)"

steps:
  - name: "Collect_Customer_Data"
    type: "STANDARD"
    function: "workflow_utils.collect_customer_data"
    required_input: ["name", "email", "country"]
  
  - name: "Start_GDPR_Processing"
    type: "STANDARD"
    function: "workflow_utils.start_gdpr_workflow"
    # Raises StartSubWorkflowDirective
    # Workflow PAUSES (PENDING_SUB_WORKFLOW)
  
  - name: "Process_GDPR_Results"
    type: "STANDARD"
    function: "workflow_utils.process_gdpr_results"
    # Runs after GDPR workflow completes
  
  - name: "Create_Account"
    type: "STANDARD"
    function: "workflow_utils.create_account"
```

**GDPR Sub-Workflow: `config/gdpr_workflow.yaml`**

```yaml
workflow_type: "GDPR_Workflow"
description: "GDPR compliance checks (must run in EU)"

steps:
  - name: "Validate_Consent"
    type: "STANDARD"
    function: "workflow_utils.validate_gdpr_consent"
  
  - name: "Check_Right_To_Erasure"
    type: "STANDARD"
    function: "workflow_utils.check_erasure_rights"
  
  - name: "Store_Compliance_Record"
    type: "ASYNC"
    function: "workflow_utils.store_compliance_record"
```

**State Models:**

```python
class OnboardingWithGDPRState(BaseModel):
    name: str = ""
    email: str = ""
    country: str = ""
    
    # Results from GDPR sub-workflow (nested)
    sub_workflow_results: Dict[str, Any] = {}
    
    gdpr_compliant: bool = False
    account_id: Optional[str] = None


class GDPRWorkflowState(BaseModel):
    customer_id: str = ""
    consent_given: bool = False
    erasure_requested: bool = False
    compliance_record_id: Optional[str] = None
    compliant: bool = False
```

**Functions:**

```python
from workflow.workflow import StartSubWorkflowDirective

def collect_customer_data(state: OnboardingWithGDPRState,
                          name: str, email: str, country: str, **kwargs):
    state.name = name
    state.email = email
    state.country = country
    return {"collected": True}


def start_gdpr_workflow(state: OnboardingWithGDPRState, **kwargs):
    """Start separate GDPR workflow in EU region"""
    raise StartSubWorkflowDirective(
        workflow_type="GDPR_Workflow",
        initial_data={
            "customer_id": state.email,
            "consent_given": True  # Simplified
        },
        data_region="eu-central-1"  # ← MUST execute in EU
    )


def process_gdpr_results(state: OnboardingWithGDPRState, **kwargs):
    """Process results from completed GDPR workflow"""
    gdpr_data = state.sub_workflow_results.get("GDPR_Workflow", {})
    state.gdpr_compliant = gdpr_data.get("compliant", False)
    
    if not state.gdpr_compliant:
        raise Exception("GDPR compliance failed")
    
    return {"gdpr_compliant": True}


def create_account(state: OnboardingWithGDPRState, **kwargs):
    state.account_id = f"ACC_{uuid.uuid4().hex[:8]}"
    return {"account_id": state.account_id}


# GDPR workflow functions
def validate_gdpr_consent(state: GDPRWorkflowState, **kwargs):
    # Validate consent is properly recorded
    if state.consent_given:
        return {"consent_valid": True}
    raise Exception("No valid consent")


def check_erasure_rights(state: GDPRWorkflowState, **kwargs):
    # Check if user has requested data erasure
    state.erasure_requested = False  # Simplified
    return {"erasure_requested": False}


@celery_app.task
def store_compliance_record(state: dict):
    # Store compliance record in EU database
    import time
    time.sleep(1)
    record_id = f"GDPR_{uuid.uuid4().hex[:8]}"
    return {
        "compliance_record_id": record_id,
        "compliant": True
    }
```

---

## Part 4: Dashboard Updates

### Update Workflow Graph to Show Inline vs. Separate

**Backend API Enhancement:**

```python
@router.get("/dashboard/workflow/{workflow_id}/graph")
async def get_workflow_graph(workflow_id: str):
    """Enhanced graph with inline injection visualization"""
    from workflow.persistence import load_workflow_state
    
    workflow = load_workflow_state(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    
    nodes = []
    edges = []
    
    for index, step in enumerate(workflow.workflow_steps):
        is_completed = index < workflow.current_step
        is_current = index == workflow.current_step
        
        status = "completed" if is_completed else "running" if is_current else "pending"
        
        # NEW: Detect if step was injected
        is_injected = step.name.startswith('[')
        injected_from = None
        if is_injected:
            # Extract workflow type from name: [CreditCheck]_StepName
            injected_from = step.name.split(']')[0][1:]
        
        nodes.append({
            "id": step.name,
            "type": step.__class__.__name__,
            "data": {
                "label": step.name,
                "status": status,
                "step_type": workflow.steps_config[index].get("type", "STANDARD"),
                "is_injected": is_injected,
                "injected_from": injected_from
            },
            "position": {"x": 250, "y": index * 100}
        })
    
    # Create edges
    for index, step_config in enumerate(workflow.steps_config):
        dependencies = step_config.get("dependencies", [])
        if not dependencies and index > 0:
            edges.append({
                "id": f"{workflow.workflow_steps[index-1].name}-{workflow.workflow_steps[index].name}",
                "source": workflow.workflow_steps[index-1].name,
                "target": workflow.workflow_steps[index].name,
                "animated": index - 1 == workflow.current_step
            })
        else:
            for dep in dependencies:
                edges.append({
                    "id": f"{dep}-{workflow.workflow_steps[index].name}",
                    "source": dep,
                    "target": workflow.workflow_steps[index].name
                })
    
    # NEW: Add metadata about injections
    injection_info = []
    for injection in workflow.injected_workflows:
        injection_info.append({
            "workflow_type": injection['workflow_type'],
            "injected_at_step": injection['injected_at_step'],
            "step_count": injection['num_steps_injected'],
            "step_names": injection['step_names']
        })
    
    return {
        "nodes": nodes,
        "edges": edges,
        "workflow": {
            "id": workflow.id,
            "type": workflow.workflow_type,
            "status": workflow.status,
            "current_step": workflow.current_step_name
        },
        "injections": injection_info
    }
```

**Frontend Component Update:**

```typescript
// components/WorkflowGraph.tsx
const NODE_COLORS = {
  completed: { bg: '#22c55e', border: '#16a34a' },
  running: { bg: '#3b82f6', border: '#2563eb' },
  pending: { bg: '#94a3b8', border: '#64748b' },
  failed: { bg: '#ef4444', border: '#dc2626' },
  injected: { bg: '#a78bfa', border: '#7c3aed' },  // NEW: Purple for injected steps
};

export function WorkflowGraph({ workflowId }: WorkflowGraphProps) {
  const { data } = useQuery({
    queryKey: ['workflow-graph', workflowId],
    queryFn: () => api.getWorkflowGraph(workflowId),
    refetchInterval: 3000,
  });
  
  const nodes: Node[] = data?.nodes.map((node: any) => {
    // Use injected color if step was injected
    const colorKey = node.data.is_injected ? 'injected' : node.data.status;
    const colors = NODE_COLORS[colorKey as keyof typeof NODE_COLORS];
    
    return {
      ...node,
      style: {
        background: colors.bg,
        color: 'white',
        border: `3px solid ${colors.border}`,
        borderRadius: '8px',
        padding: '12px 16px',
        fontSize: '14px',
        fontWeight: '500',
        minWidth: '180px',
        // Add dashed border for injected steps
        borderStyle: node.data.is_injected ? 'dashed' : 'solid',
      },
      // Add badge for injected steps
      data: {
        ...node.data,
        label: node.data.is_injected 
          ? `${node.data.label} (from ${node.data.injected_from})`
          : node.data.label
      }
    };
  }) || [];
  
  return (
    <div className="h-[600px] bg-gray-50 rounded-lg border border-gray-200">
      <ReactFlow nodes={nodes} edges={edges} fitView>
        <Background />
        <Controls />
      </ReactFlow>
      
      {/* Show injection summary */}
      {data?.injections && data.injections.length > 0 && (
        <div className="absolute top-4 right-4 bg-white rounded-lg shadow-lg p-4 border border-gray-200">
          <h4 className="text-xs font-semibold text-gray-700 mb-2">Inline Injections</h4>
          {data.injections.map((inj: any, idx: number) => (
            <div key={idx} className="text-xs text-gray-600 mb-1">
              • {inj.workflow_type} ({inj.step_count} steps)
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
```

---

## Part 5: Testing

### Test Suite for Hybrid Approach

**File: `tests/test_hybrid_subworkflows.py`**

```python
import pytest
from workflow.workflow_loader import workflow_builder
from workflow.workflow import InlineSubWorkflowSteps, StartSubWorkflowDirective

def test_inline_injection():
    """Test inline sub-workflow injection"""
    workflow = workflow_builder.create_workflow(
        workflow_type="LoanWithInlineCredit",
        initial_data={}
    )
    
    # Initially has 5 steps
    assert len(workflow.workflow_steps) == 5
    
    # Execute first step (Collect_Application)
    workflow.next_step({"applicant_name": "Test", "requested_amount": 5000})
    
    # Execute second step (Inline_Credit_Check)
    # This should inject 3 steps from CreditCheck
    result, next_step = workflow.next_step({})
    
    # Now should have 8 steps (5 original + 3 injected)
    assert len(workflow.workflow_steps) == 8
    assert "Injected 3 steps" in result["message"]
    
    # Check injected step names are prefixed
    injected_steps = [s.name for s in workflow.workflow_steps if s.name.startswith('[CreditCheck]')]
    assert len(injected_steps) == 3
    assert '[CreditCheck]_Verify_Identity' in injected_steps
    
    # Continue workflow through injected steps
    workflow.next_step({})  # Verify_Identity
    workflow.next_step({})  # Check_Score (async, will pause in real scenario)
    

def test_separate_subworkflow():
    """Test separate sub-workflow execution"""
    workflow = workflow_builder.create_workflow(
        workflow_type="OnboardingWithGDPR",
        initial_data={}
    )
    
    # Execute to GDPR step
    workflow.next_step({"name": "Test", "email": "test@example.com", "country": "DE"})
    workflow.next_step({})
    
    # Should pause for sub-workflow
    assert workflow.status == "PENDING_SUB_WORKFLOW"
    assert workflow.blocked_on_child_id is not None


def test_state_mapping():
    """Test state mapping in inline injection"""
    from state_models import LoanWithInlineCreditState
    
    workflow = workflow_builder.create_workflow(
        workflow_type="LoanWithInlineCredit",
        initial_data={}
    )
    
    # Set up state
    workflow.next_step({"applicant_name": "Alice", "requested_amount": 5000})
    
    # Inline injection with state mapping
    workflow.next_step({})
    
    # Execute injected steps
    workflow.next_step({})  # Verify_Identity
    
    # Check that state mapping worked
    assert workflow.state.identity_verified == True


def test_saga_with_inline():
    """Test saga rollback works with inline injected steps"""
    workflow = workflow_builder.create_workflow(
        workflow_type="LoanWithInlineCredit",
        initial_data={}
    )
    workflow.enable_saga_mode()
    
    # Execute through injected steps
    workflow.next_step({"applicant_name": "Test", "requested_amount": 5000})
    workflow.next_step({})  # Inject
    workflow.next_step({})  # Execute injected step 1
    
    # Simulate failure
    try:
        raise Exception("Simulated failure")
    except:
        workflow._execute_saga_rollback()
    
    assert workflow.status == "FAILED_ROLLED_BACK"
```

---

## Part 6: Migration Guide

### Migrating Existing Separate Sub-Workflows to Inline

**Decision Checklist:**

```python
# For each existing sub-workflow, ask:
should_migrate_to_inline = (
    steps_count < 5 and
    same_region and
    not_reused_by_multiple_parents and
    performance_critical
)
```

**Migration Example:**

**Before (Separate):**

```python
def run_email_verification(state: OnboardingState):
    raise StartSubWorkflowDirective(
        workflow_type="EmailVerification",
        initial_data={"email": state.email}
    )

def process_verification_results(state: OnboardingState):
    results = state.sub_workflow_results["EmailVerification"]
    state.email_verified = results["verified"]
```

**After (Inline):**

```python
def run_email_verification(state: OnboardingState):
    raise InlineSubWorkflowSteps(
        workflow_type="EmailVerification",
        initial_data={"email": state.email},
        state_mapping={"verified": "email_verified"}
    )

# No need for separate processing step - direct access!
def continue_onboarding(state: OnboardingState):
    if state.email_verified:
        # Continue...
```

---

## Summary

You now have a **complete hybrid sub-workflow system** with:

### ✅ Inline Injection (NEW)
- Simpler state management (flat structure)
- Eliminates race conditions (single workflow instance)
- Clearer saga boundaries (single rollback scope)
- Better performance (fewer DB writes, no coordination overhead)
- Easier debugging (linear execution history)

### ✅ Separate Sub-Workflows (EXISTING, ENHANCED)
- Cross-region data sovereignty (critical for "Planetary")
- True reusability (versioned, isolated)
- Independent testing
- Complex process isolation

### ✅ Developer Choice
- Clear decision matrix for choosing approach
- YAML syntax supports both
- Can mix both in same workflow
- Easy migration path

### ✅ Dashboard Visualization
- Shows inline vs. separate visually
- Tracks injection history
- Purple/dashed border for injected steps

This gives you the **best of both worlds** while maintaining your vision of the "Planetary Nervous System" for truly distributed, cross-region workflows.

# Advanced: Dynamic Step Injection

**Warning**: Dynamic step injection makes workflows **non-deterministic** and significantly harder to debug.

---

## The Problem

When a workflow modifies its own structure at runtime based on data, the execution trace no longer matches the YAML definition. This creates serious operational challenges:

1. **Debugging Difficulty**: Audit logs show steps that don't exist in the workflow YAML file
2. **Compensation Complexity**: Saga rollback must track dynamically injected steps
3. **Non-Determinism**: Same workflow type with different data produces different execution paths
4. **Version Control**: Cannot reconstruct execution from Git history (definition changed at runtime)
5. **Audit Compliance**: Harder to prove regulatory compliance when workflow structure is dynamic

---

## Example of the Problem

**YAML Definition:**

```yaml
# my_workflow.yaml
steps:
  - name: "Process_Order"
    type: "STANDARD"
    function: "steps.process_order"
    dynamic_injection:
      condition: "state.amount > 10000"
      steps:
        - name: "High_Value_Review"  # This step NOT in YAML!
          function: "steps.high_value_review"
      insert_after: "Process_Order"
```

**What happens:**
- Low-value order ($100): Executes `Process_Order` → `Ship_Order` (matches YAML)
- High-value order ($20,000): Executes `Process_Order` → `High_Value_Review` → `Ship_Order` (YAML + injected step)

**When developer looks at audit log:**
> "Why did this workflow execute `High_Value_Review`? It's not in the YAML file!"

This is **debugging hell** in production.

---

## When to Use Dynamic Injection (Rare Cases Only)

Use dynamic injection only when:

1. **Plugin Systems**: Steps defined by external packages (e.g., `rufus-plugins`)
   ```python
   # Customer uploads custom validation plugin
   plugin_step = customer.get_validation_plugin()
   workflow.inject_step(plugin_step, after="Validate_Input")
   ```

2. **Multi-Tenant Workflows**: Tenants provide custom validation logic
   ```python
   # SaaS: Each tenant has custom approval logic
   tenant_approval = tenant_registry.get_approval_step(tenant_id)
   workflow.inject_step(tenant_approval, after="Process_Request")
   ```

3. **A/B Testing**: Controlled experiments with workflow variations
   ```python
   # 10% of users get experimental fraud detection
   if experiment.is_enabled(user_id, "new_fraud_check"):
       workflow.inject_step(new_fraud_step, after="Validate_Payment")
   ```

4. **Dynamic Compliance**: Regulatory requirements vary by jurisdiction
   ```python
   # GDPR consent required for EU users
   if user.region == "EU":
       workflow.inject_step(gdpr_consent_step, after="Create_Account")
   ```

**If your use case is not one of these, DO NOT use dynamic injection.**

---

## Recommended Alternatives

### Alternative 1: DECISION Steps with Explicit Routes

**Instead of dynamic injection:**

```yaml
# ❌ Dynamic injection - step appears out of nowhere
steps:
  - name: "Process_Order"
    type: "STANDARD"
    function: "steps.process_order"
    dynamic_injection:
      condition: "state.amount > 10000"
      steps:
        - name: "High_Value_Review"
          function: "steps.high_value_review"
```

**Use DECISION step (recommended):**

```yaml
# ✅ Explicit routing - all steps visible in YAML
steps:
  - name: "Process_Order"
    type: "STANDARD"
    function: "steps.process_order"
    automate_next: true

  - name: "Check_Order_Value"
    type: "DECISION"
    function: "steps.check_order_value"
    routes:
      - condition: "state.amount > 10000"
        target: "High_Value_Review"  # Visible in YAML!
      - condition: "state.amount <= 10000"
        target: "Standard_Processing"

  - name: "High_Value_Review"  # Explicit step
    type: "STANDARD"
    function: "steps.high_value_review"
    dependencies: ["Check_Order_Value"]

  - name: "Standard_Processing"  # Explicit step
    type: "STANDARD"
    function: "steps.standard_processing"
    dependencies: ["Check_Order_Value"]
```

**Benefits:**
- All steps visible in YAML
- Execution path deterministic from YAML
- Easy to debug (look at YAML + audit log)
- Version control works (Git history shows all steps)

---

### Alternative 2: Conditional Logic Within Steps

**Instead of injecting a new step:**

```yaml
# ❌ Dynamic injection
steps:
  - name: "Process_Order"
    dynamic_injection:
      condition: "state.requires_review"
      steps:
        - name: "Manual_Review"
          function: "steps.manual_review"
```

**Put conditional logic in the step function:**

```yaml
# ✅ Conditional logic in step
steps:
  - name: "Process_Order"
    type: "STANDARD"
    function: "steps.process_order"
```

```python
def process_order(state: OrderState, context: StepContext):
    # Validate order
    validate_order_details(state)

    # Conditional logic inline
    if state.amount > 10000:
        # High-value logic inline
        perform_high_value_checks(state)
        state.requires_manual_review = True
    else:
        # Standard logic
        perform_standard_checks(state)

    return {"processed": True}
```

**Benefits:**
- Single step in YAML
- All logic in one place
- Easy to test (single function)
- No workflow modification at runtime

---

### Alternative 3: Multiple Workflow Versions

**Instead of one workflow with dynamic injection:**

```yaml
# ❌ Single workflow with dynamic injection
workflow_type: "OrderProcessing"
steps:
  - name: "Process"
    dynamic_injection:
      condition: "state.is_high_value"
      steps: [...]
```

**Create separate workflow versions:**

```yaml
# ✅ order_processing_standard.yaml
workflow_type: "OrderProcessing_Standard"
steps:
  - name: "Validate_Order"
    function: "steps.validate_order"
  - name: "Process_Payment"
    function: "steps.process_payment"
```

```yaml
# ✅ order_processing_high_value.yaml
workflow_type: "OrderProcessing_HighValue"
steps:
  - name: "Validate_Order"
    function: "steps.validate_order"
  - name: "High_Value_Review"  # Explicit in this version
    function: "steps.high_value_review"
  - name: "Process_Payment"
    function: "steps.process_payment"
```

**Route at creation time:**

```python
if order.amount > 10000:
    workflow = builder.create_workflow("OrderProcessing_HighValue", data)
else:
    workflow = builder.create_workflow("OrderProcessing_Standard", data)
```

**Benefits:**
- Each workflow version fully defined in YAML
- Clear separation of concerns
- Easy to test each version independently
- Version control tracks both variants

---

## If You Must Use Dynamic Injection

If your use case truly requires dynamic injection (plugin system, multi-tenant, etc.), follow these guidelines:

### 1. Enable Full Audit Logging

```python
def inject_custom_step(workflow, step_config, insert_after):
    """Inject step with full audit trail"""

    # Log injection event
    logger.warning(
        f"Dynamic step injection",
        extra={
            "workflow_id": workflow.id,
            "injected_step": step_config["name"],
            "insert_after": insert_after,
            "reason": "Plugin system",
            "injected_by": current_user.id,
        }
    )

    # Record to audit log
    await persistence.audit_log(
        workflow_id=workflow.id,
        event_type="DYNAMIC_INJECTION",
        metadata={
            "step_name": step_config["name"],
            "function": step_config["function"],
            "inserted_after": insert_after,
        }
    )

    # Inject step
    workflow.inject_step(step_config, after=insert_after)
```

---

### 2. Snapshot Workflow Definition

Save the final workflow structure (with injected steps) to the database:

```python
def create_workflow_with_injection(builder, workflow_type, initial_data):
    # Create workflow
    workflow = builder.create_workflow(workflow_type, initial_data)

    # Apply dynamic injection
    if should_inject_step(initial_data):
        custom_step = get_custom_step_config(initial_data)
        workflow.inject_step(custom_step, after="Process_Input")

    # Snapshot final workflow structure
    workflow_snapshot = {
        "workflow_type": workflow.workflow_type,
        "steps": [step.to_dict() for step in workflow.steps],
        "injected_steps": workflow.injected_steps,  # Track what was injected
    }

    # Save snapshot
    await persistence.save_workflow_snapshot(workflow.id, workflow_snapshot)

    return workflow
```

**Now you can reconstruct the exact workflow structure later.**

---

### 3. Add Comments/Documentation

```yaml
# config/my_workflow.yaml
workflow_type: "MyWorkflow"
description: |
  This workflow supports dynamic step injection for plugin system.
  Injected steps are loaded from customer_plugins table based on tenant_id.
  See docs/plugins.md for plugin development guide.

steps:
  - name: "Process_Data"
    type: "STANDARD"
    function: "steps.process_data"
    dynamic_injection:
      # REASON FOR DYNAMIC INJECTION: Multi-tenant SaaS, custom validation per tenant
      condition: "state.tenant_config.has_custom_validation"
      steps:
        - name: "Custom_Validation"
          function: "state.tenant_config.validation_function"
      insert_after: "Process_Data"
      # Audit injection with full metadata
      audit_injection: true
```

---

### 4. Limit Scope

Only inject in specific, well-documented scenarios:

```python
class WorkflowBuilder:
    def create_workflow(self, workflow_type, initial_data):
        workflow = self._build_workflow(workflow_type, initial_data)

        # Dynamic injection ONLY for plugin-enabled workflows
        if workflow_type in PLUGIN_ENABLED_WORKFLOWS:
            self._apply_plugin_steps(workflow, initial_data)

        return workflow

    def _apply_plugin_steps(self, workflow, initial_data):
        # Only inject if explicitly enabled
        if not initial_data.get("enable_plugins", False):
            return

        # Limit to specific injection points
        ALLOWED_INJECTION_POINTS = ["Process_Data", "Validate_Input"]

        for plugin in load_plugins(initial_data["tenant_id"]):
            if plugin.injection_point not in ALLOWED_INJECTION_POINTS:
                raise ValueError(f"Invalid injection point: {plugin.injection_point}")

            workflow.inject_step(plugin.step_config, after=plugin.injection_point)
```

---

### 5. Review Regularly

Periodic audits of dynamic injection usage:

```sql
-- Find workflows with dynamic injection
SELECT
    workflow_id,
    event_type,
    metadata->>'step_name' as injected_step,
    metadata->>'inserted_after' as insert_point,
    recorded_at
FROM workflow_audit_log
WHERE event_type = 'DYNAMIC_INJECTION'
ORDER BY recorded_at DESC
LIMIT 100;
```

Review:
- Is dynamic injection still necessary?
- Can we convert to DECISION steps?
- Are injections audited properly?

---

## Configuration Example (If Necessary)

```yaml
steps:
  - name: "Process_Data"
    type: "STANDARD"
    function: "steps.process_data"
    dynamic_injection:
      # DOCUMENT WHY THIS IS NEEDED
      # Reason: Multi-tenant workflow, tenants define custom validation
      condition: "state.tenant_config.has_custom_validation"
      steps:
        - name: "Custom_Validation"
          function: "state.tenant_config.validation_function"
      insert_after: "Process_Data"
      # Log injection for audit
      audit_injection: true
      # Limit injection to specific tenants (security)
      allowed_tenants: ["tenant-a", "tenant-b"]
```

---

## Testing Dynamic Injection

### Test Workflow With and Without Injection

```python
def test_workflow_without_injection():
    """Test base workflow (no injection)"""
    workflow = builder.create_workflow(
        "PluginWorkflow",
        initial_data={"enable_plugins": False}
    )

    # Execute workflow
    while workflow.status == "ACTIVE":
        await workflow.next_step()

    # Verify no injected steps
    assert len(workflow.injected_steps) == 0
    assert workflow.status == "COMPLETED"


def test_workflow_with_injection():
    """Test workflow with plugin injection"""
    workflow = builder.create_workflow(
        "PluginWorkflow",
        initial_data={
            "enable_plugins": True,
            "tenant_id": "tenant-a"
        }
    )

    # Verify injection occurred
    assert len(workflow.injected_steps) == 1
    assert workflow.injected_steps[0]["name"] == "Custom_Validation"

    # Execute workflow
    while workflow.status == "ACTIVE":
        await workflow.next_step()

    assert workflow.status == "COMPLETED"
```

---

## Debugging Dynamic Injection

### 1. Check Audit Log

```python
async def debug_workflow_structure(workflow_id):
    """Show original YAML + injected steps"""

    # Load workflow
    workflow = await persistence.load_workflow(workflow_id)

    print(f"Workflow Type: {workflow['workflow_type']}")
    print(f"Original Steps (from YAML):")
    for step in workflow['original_steps']:
        print(f"  - {step['name']}")

    print(f"\nInjected Steps:")
    for step in workflow.get('injected_steps', []):
        print(f"  - {step['name']} (inserted after {step['inserted_after']})")

    print(f"\nFinal Execution Order:")
    for step in workflow['steps']:
        is_injected = step['name'] in [s['name'] for s in workflow.get('injected_steps', [])]
        marker = "[INJECTED]" if is_injected else ""
        print(f"  {step['index']}. {step['name']} {marker}")
```

---

### 2. Visualize Execution Path

```python
async def visualize_workflow_execution(workflow_id):
    """Show execution path with injected steps highlighted"""

    logs = await persistence.get_execution_logs(workflow_id)

    print(f"Execution Path for {workflow_id}:")
    print(f"{'Step':<30} {'Type':<15} {'Duration':<10} {'Injected?':<10}")
    print("="*70)

    for log in logs:
        step_name = log['step_name']
        is_injected = step_name in workflow['injected_steps']
        injected_marker = "YES" if is_injected else "NO"

        print(f"{step_name:<30} {log['type']:<15} {log['duration']:<10} {injected_marker:<10}")
```

---

## Summary

**Remember**: Dynamic injection is a **power tool** that trades debuggability for flexibility. Use sparingly and document thoroughly.

### Decision Tree

```
Do you need workflow structure to change at runtime?
├─ No → Use DECISION steps or conditional logic in steps
└─ Yes → Is it one of these cases?
    ├─ Plugin system → OK (with audit logging)
    ├─ Multi-tenant SaaS → OK (with audit logging)
    ├─ A/B testing → OK (with audit logging)
    ├─ Dynamic compliance → OK (with audit logging)
    └─ Other → ❌ Use alternatives (DECISION, multiple workflows)
```

### Best Practices Checklist

- [ ] Documented reason for dynamic injection
- [ ] Audit logging enabled
- [ ] Workflow snapshot saved
- [ ] Limited to specific injection points
- [ ] Regular review scheduled
- [ ] Tests for both injected and non-injected paths
- [ ] Debugging tools in place

### Alternatives Preference Order

1. **DECISION steps with explicit routes** (best for most cases)
2. **Conditional logic within steps** (simple conditionals)
3. **Multiple workflow versions** (different user types)
4. **Dynamic injection** (plugin systems, multi-tenant) ⚠️ Use with caution

---

## Real-World Anti-Pattern

### What NOT to Do

```python
# ❌ TERRIBLE IDEA - debugging nightmare
def process_order(state: OrderState, context: StepContext):
    # Inject 20 different steps based on complex conditions
    if state.user_tier == "gold" and state.amount > 1000:
        context.workflow.inject_step(gold_customer_check, after="Process_Order")

    if state.region == "EU" and state.gdpr_consent:
        context.workflow.inject_step(gdpr_validation, after="Process_Order")

    if state.payment_method == "crypto":
        context.workflow.inject_step(crypto_validation, after="Process_Order")

    # ... 15 more conditions ...

    # Now workflow structure is COMPLETELY DIFFERENT from YAML
    # Impossible to debug in production
```

**This is unmaintainable. Use DECISION steps instead.**

---

## Getting Help

If you're considering dynamic injection:

1. **Post your use case** to Rufus community forum
2. **Ask for design review** before implementing
3. **Explore alternatives** suggested by maintainers
4. **Start with DECISION steps**, only use injection if truly necessary

Most use cases can be solved without dynamic injection.

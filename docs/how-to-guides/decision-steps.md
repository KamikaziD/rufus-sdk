# How to use decision steps

This guide covers implementing conditional branching in workflows using DECISION steps.

## Overview

DECISION steps enable conditional routing based on workflow state. They evaluate conditions and direct execution to different target steps.

## Basic decision step

### Define in YAML

```yaml
workflow_type: "OrderProcessing"
initial_state_model: "my_app.state_models.OrderState"

steps:
  - name: "Check_Order_Amount"
    type: "DECISION"
    function: "my_app.steps.check_order_amount"
    routes:
      - condition: "state.amount > 10000"
        target: "Manual_Approval"
      - condition: "state.amount <= 10000"
        target: "Auto_Process"

  - name: "Manual_Approval"
    type: "HUMAN_IN_LOOP"
    function: "my_app.steps.await_approval"

  - name: "Auto_Process"
    type: "STANDARD"
    function: "my_app.steps.auto_process"
```

### Implement decision function

```python
from ruvon.models import StepContext
from my_app.state_models import OrderState

def check_order_amount(state: OrderState, context: StepContext) -> dict:
    """Check order amount and set routing metadata."""

    # Decision function just returns metadata
    # Routing is handled by YAML conditions
    return {
        "amount_checked": True,
    }
```

**Key points:**
- Decision function returns data like any other step
- Routing happens automatically based on YAML `routes`
- Conditions are evaluated against workflow state
- First matching condition wins

## Condition syntax

Conditions are Python expressions evaluated against workflow state:

```yaml
routes:
  # Numeric comparisons
  - condition: "state.amount > 10000"
    target: "High_Value_Process"

  # String comparisons
  - condition: "state.status == 'premium'"
    target: "Premium_Processing"

  # Boolean checks
  - condition: "state.is_verified"
    target: "Verified_Path"

  # Complex conditions
  - condition: "state.amount > 5000 and state.country == 'US'"
    target: "US_High_Value"

  # List membership
  - condition: "'fraud' in state.risk_flags"
    target: "Fraud_Review"

  # Default fallback (always true)
  - condition: "True"
    target: "Default_Process"
```

## Multiple decision branches

Create complex routing logic:

```yaml
- name: "Route_Order"
  type: "DECISION"
  function: "my_app.steps.route_order"
  routes:
    # Premium customers
    - condition: "state.customer_tier == 'premium'"
      target: "Premium_Processing"

    # High value orders
    - condition: "state.amount > 10000"
      target: "Manual_Review"

    # International orders
    - condition: "state.country != 'US'"
      target: "International_Shipping"

    # Default path
    - condition: "True"
      target: "Standard_Processing"
```

## Programmatic jumps

Use `WorkflowJumpDirective` for programmatic control:

```python
from ruvon.models import StepContext, WorkflowJumpDirective
from my_app.state_models import OrderState

def check_fraud_score(state: OrderState, context: StepContext) -> dict:
    """Check fraud score and route programmatically."""

    fraud_score = calculate_fraud_score(state)
    state.fraud_score = fraud_score

    if fraud_score > 0.8:
        # High fraud - immediate rejection
        raise WorkflowJumpDirective(target_step_name="Reject_Order")
    elif fraud_score > 0.5:
        # Medium fraud - manual review
        raise WorkflowJumpDirective(target_step_name="Fraud_Review")
    else:
        # Low fraud - continue normally
        raise WorkflowJumpDirective(target_step_name="Process_Order")
```

**When to use WorkflowJumpDirective:**
- Complex routing logic not expressible in YAML
- Dynamic target selection based on calculations
- Multiple conditions requiring Python logic

## Nested decisions

Chain decision steps for complex workflows:

```yaml
steps:
  - name: "Check_Customer_Type"
    type: "DECISION"
    function: "my_app.steps.check_customer_type"
    routes:
      - condition: "state.customer_type == 'business'"
        target: "Check_Business_Size"
      - condition: "state.customer_type == 'individual'"
        target: "Check_Individual_Tier"

  - name: "Check_Business_Size"
    type: "DECISION"
    function: "my_app.steps.check_business_size"
    routes:
      - condition: "state.employee_count > 100"
        target: "Enterprise_Process"
      - condition: "True"
        target: "SMB_Process"

  - name: "Check_Individual_Tier"
    type: "DECISION"
    function: "my_app.steps.check_individual_tier"
    routes:
      - condition: "state.tier == 'premium'"
        target: "Premium_Process"
      - condition: "True"
        target: "Standard_Process"
```

## Decision with data enrichment

Enrich state before routing:

```python
def evaluate_loan_application(state: LoanState, context: StepContext) -> dict:
    """Evaluate loan and enrich state before routing."""

    # Calculate credit score
    credit_score = get_credit_score(state.ssn)
    state.credit_score = credit_score

    # Calculate debt-to-income ratio
    dti_ratio = state.total_debt / state.annual_income
    state.dti_ratio = dti_ratio

    # Calculate approval likelihood
    approval_likelihood = calculate_approval(credit_score, dti_ratio)
    state.approval_likelihood = approval_likelihood

    return {
        "credit_score": credit_score,
        "dti_ratio": dti_ratio,
        "approval_likelihood": approval_likelihood
    }
```

```yaml
- name: "Evaluate_Loan"
  type: "DECISION"
  function: "my_app.steps.evaluate_loan_application"
  routes:
    - condition: "state.credit_score > 750 and state.dti_ratio < 0.36"
      target: "Auto_Approve"
    - condition: "state.credit_score < 600"
      target: "Auto_Reject"
    - condition: "True"
      target: "Manual_Review"
```

## Error handling in decisions

Handle errors gracefully:

```python
def check_eligibility(state: OrderState, context: StepContext) -> dict:
    """Check eligibility with error handling."""

    try:
        # External API call
        eligibility = check_customer_eligibility(state.customer_id)
        state.is_eligible = eligibility

        return {
            "eligibility_checked": True,
            "is_eligible": eligibility
        }

    except APIException as e:
        # Log error but don't fail workflow
        state.eligibility_error = str(e)
        state.is_eligible = False  # Safe default

        return {
            "eligibility_checked": True,
            "is_eligible": False,
            "error": str(e)
        }
```

```yaml
- name: "Check_Eligibility"
  type: "DECISION"
  function: "my_app.steps.check_eligibility"
  routes:
    - condition: "state.is_eligible == True"
      target: "Process_Order"
    - condition: "state.eligibility_error is not None"
      target: "Handle_Error"
    - condition: "True"
      target: "Reject_Order"
```

## Default routes

Always provide a default route:

```yaml
routes:
  - condition: "state.priority == 'high'"
    target: "High_Priority"
  - condition: "state.priority == 'medium'"
    target: "Medium_Priority"
  # Default fallback - catches everything else
  - condition: "True"
    target: "Low_Priority"
```

**Without a default:**
- Workflow fails if no conditions match
- Status set to FAILED
- Error logged

## Testing decision steps

Test all routing paths:

```python
import pytest
from ruvon.testing.harness import TestHarness

@pytest.mark.asyncio
async def test_high_value_routing():
    """Test high value order routing."""

    harness = TestHarness()

    # Create workflow with high-value order
    workflow = await harness.start_workflow(
        workflow_type="OrderProcessing",
        initial_data={
            "order_id": "ORD-001",
            "amount": 15000  # High value
        }
    )

    # Execute decision step
    result = await harness.next_step(workflow.id)

    # Should route to Manual_Approval
    assert workflow.current_step == "Manual_Approval"

@pytest.mark.asyncio
async def test_standard_value_routing():
    """Test standard value order routing."""

    harness = TestHarness()

    workflow = await harness.start_workflow(
        workflow_type="OrderProcessing",
        initial_data={
            "order_id": "ORD-002",
            "amount": 99.99  # Standard value
        }
    )

    result = await harness.next_step(workflow.id)

    # Should route to Auto_Process
    assert workflow.current_step == "Auto_Process"
```

## Common patterns

### A/B testing

```yaml
- name: "AB_Test_Route"
  type: "DECISION"
  function: "my_app.steps.ab_test"
  routes:
    - condition: "state.ab_group == 'A'"
      target: "Process_A"
    - condition: "state.ab_group == 'B'"
      target: "Process_B"
```

### Feature flags

```python
def check_feature_flag(state: OrderState, context: StepContext) -> dict:
    """Route based on feature flags."""

    new_checkout_enabled = get_feature_flag("new_checkout", state.customer_id)
    state.new_checkout_enabled = new_checkout_enabled

    return {"feature_checked": True}
```

```yaml
- name: "Check_Checkout_Version"
  type: "DECISION"
  function: "my_app.steps.check_feature_flag"
  routes:
    - condition: "state.new_checkout_enabled"
      target: "New_Checkout"
    - condition: "True"
      target: "Legacy_Checkout"
```

### Time-based routing

```python
from datetime import datetime

def check_business_hours(state: OrderState, context: StepContext) -> dict:
    """Route based on business hours."""

    now = datetime.now()
    is_business_hours = 9 <= now.hour < 17
    state.is_business_hours = is_business_hours

    return {"time_checked": True}
```

```yaml
- name: "Check_Hours"
  type: "DECISION"
  function: "my_app.steps.check_business_hours"
  routes:
    - condition: "state.is_business_hours"
      target: "Immediate_Process"
    - condition: "True"
      target: "Queue_For_Tomorrow"
```

## Best practices

1. **Always provide default route** - Use `condition: "True"` as last route
2. **Order routes by priority** - First matching condition wins
3. **Keep conditions simple** - Complex logic goes in step function
4. **Enrich state first** - Calculate values before routing
5. **Test all paths** - Write tests for each routing scenario
6. **Log decisions** - Return metadata about why route was chosen

## Next steps

- [Add human-in-the-loop](human-in-loop.md)
- [Implement parallel steps](http-steps.md)
- [Enable saga mode](saga-mode.md)

## See also

- [Create workflow guide](create-workflow.md)
- [Testing guide](testing.md)
- USAGE_GUIDE.md section 8.4 for DECISION steps
- YAML_GUIDE.md for route configuration

# JavaScript Steps Example

This example demonstrates how to use JavaScript/TypeScript steps in Rufus workflows for data transformation and business logic.

## Overview

This workflow processes an e-commerce order using a mix of Python and JavaScript steps:

1. **Validate Order** (Python) - Basic validation
2. **Calculate Pricing** (JavaScript) - Complex pricing calculations
3. **Apply Discounts** (TypeScript) - Discount logic with type safety
4. **Process Order** (Python) - Final processing

## Prerequisites

```bash
# Install py-mini-racer for JavaScript execution
pip install py-mini-racer

# Optional: Install esbuild for TypeScript support
npm install -g esbuild
```

## Files

- `workflow.yaml` - Workflow definition with JavaScript steps
- `workflow_registry.yaml` - Workflow registry
- `state_models.py` - Pydantic state model
- `steps.py` - Python step functions
- `scripts/calculate-pricing.js` - JavaScript pricing calculation
- `scripts/apply-discounts.ts` - TypeScript discount logic
- `run_example.py` - Example runner

## Running the Example

```bash
cd examples/javascript_steps
python run_example.py
```

## What This Demonstrates

### 1. Inline JavaScript Code

Simple calculations directly in YAML:

```yaml
- name: "Quick_Calc"
  type: "JAVASCRIPT"
  js_config:
    code: "return { total: state.items.length };"
```

### 2. File-Based JavaScript

External scripts with full access to rufus utilities:

```yaml
- name: "Calculate_Pricing"
  type: "JAVASCRIPT"
  js_config:
    script_path: "scripts/calculate-pricing.js"
    timeout_ms: 5000
```

### 3. TypeScript Support

Type-safe business logic:

```yaml
- name: "Apply_Discounts"
  type: "JAVASCRIPT"
  js_config:
    script_path: "scripts/apply-discounts.ts"
    typescript: true
```

### 4. Built-in Utilities

The `rufus` object provides common utilities:

```javascript
rufus.log("Processing...");
rufus.round(19.999, 2);  // 20.00
rufus.sum([1, 2, 3]);    // 6
rufus.groupBy(items, 'category');
```

## Security

JavaScript steps run in a sandboxed V8 environment:
- No file system access
- No network access
- No `eval`, `require`, `process`, etc.
- Memory and timeout limits enforced
- State is read-only (frozen)

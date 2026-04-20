# JavaScript Step Type Implementation Plan

> **Status**: Draft - Pending Review
> **Author**: Claude
> **Date**: 2026-01-25
> **Branch**: claude/polyglot-documentation-fPaTB

## Executive Summary

This document outlines the implementation plan for adding a JavaScript step type to the Ruvon SDK, enabling workflows to execute JavaScript/TypeScript code within a sandboxed V8 environment. This complements HTTP steps for polyglot workflows by providing fast, in-process script execution without external service dependencies.

---

## Table of Contents

1. [Goals and Non-Goals](#1-goals-and-non-goals)
2. [Technical Decision: Runtime Selection](#2-technical-decision-runtime-selection)
3. [Architecture Overview](#3-architecture-overview)
4. [Data Model](#4-data-model)
5. [Execution Flow](#5-execution-flow)
6. [TypeScript Support](#6-typescript-support)
7. [Security Model](#7-security-model)
8. [File Structure](#8-file-structure)
9. [Implementation Phases](#9-implementation-phases)
10. [YAML Configuration](#10-yaml-configuration)
11. [Built-in Utilities (ruvon object)](#11-built-in-utilities-ruvon-object)
12. [Error Handling](#12-error-handling)
13. [Testing Strategy](#13-testing-strategy)
14. [Documentation Updates](#14-documentation-updates)
15. [Example Implementation](#15-example-implementation)
16. [Future: NPM Package Support](#16-future-npm-package-support)
17. [Migration Path](#17-migration-path)
18. [Open Questions](#18-open-questions)

---

## 1. Goals and Non-Goals

### Goals

| Goal | Description |
|------|-------------|
| **File-based scripts** | Primary mode: point to `.js` or `.ts` files |
| **Inline scripts** | Secondary mode: embed small scripts in YAML |
| **TypeScript support** | Transpile `.ts` files to JS before execution |
| **Sandboxed execution** | V8 isolate with no system access |
| **Fast startup** | < 10ms cold start, < 1ms warm start |
| **State injection** | Workflow state available as `state` global |
| **Result extraction** | Return object merged into workflow state |
| **Timeout enforcement** | Configurable execution timeout |
| **Memory limits** | Configurable V8 heap size |
| **Prepared for npm** | Architecture supports future npm package loading |

### Non-Goals (Phase 1)

| Non-Goal | Rationale |
|----------|-----------|
| **npm package support** | Deferred to Phase 2 |
| **Node.js APIs** | No `fs`, `http`, `process`, etc. |
| **async/await in scripts** | V8 isolates are synchronous |
| **ES Modules (import/export)** | Deferred to Phase 2 with bundling |
| **Debugging/breakpoints** | Out of scope for MVP |
| **Hot reloading** | Scripts loaded fresh each execution |

---

## 2. Technical Decision: Runtime Selection

### Options Evaluated

| Runtime | Pros | Cons |
|---------|------|------|
| **PyMiniRacer** | V8-based, well-maintained, good Python bindings | Larger binary (~15MB), slower cold start |
| **QuickJS** | Tiny (~500KB), fastest cold start, ES2023 | Not V8 (minor compatibility differences) |
| **Deno (subprocess)** | Modern, TypeScript native, secure | External process, higher latency |
| **pyjsengine** | Multiple engine support | Less mature, fewer users |

### Recommendation: **PyMiniRacer** (Primary) with **QuickJS** (Optional)

**Rationale:**
1. **V8 compatibility** - Same engine as Chrome/Node.js, maximum JS compatibility
2. **Battle-tested** - Used in production by many Python projects
3. **Active maintenance** - Regular updates, responsive maintainers
4. **TypeScript ecosystem** - Better tooling compatibility with V8
5. **Future npm support** - V8's module system is more compatible with npm

**QuickJS as fallback:**
- Optional lightweight alternative for resource-constrained environments
- Can be added later without architecture changes

### Installation

```bash
# Primary runtime
pip install py-mini-racer>=0.12.0

# TypeScript transpilation
pip install esbuild  # Fast, Go-based transpiler
# OR
pip install pyright  # Type checking only, use tsc for transpilation
```

**Note**: We'll use `esbuild` for TypeScript transpilation because:
- 10-100x faster than `tsc`
- Single binary, no Node.js required
- Handles both transpilation and bundling (future npm support)

---

## 3. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Workflow Engine                               │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │  WorkflowBuilder                                             │    │
│  │  - Parses YAML with type="JAVASCRIPT"                       │    │
│  │  - Creates JavaScriptWorkflowStep                           │    │
│  └──────────────────────┬──────────────────────────────────────┘    │
│                         │                                            │
│  ┌──────────────────────▼──────────────────────────────────────┐    │
│  │  ExecutionProvider                                           │    │
│  │  - Delegates to JavaScriptExecutor                          │    │
│  └──────────────────────┬──────────────────────────────────────┘    │
│                         │                                            │
│  ┌──────────────────────▼──────────────────────────────────────┐    │
│  │  JavaScriptExecutor                                          │    │
│  │  ┌─────────────────────────────────────────────────────┐    │    │
│  │  │  ScriptLoader                                        │    │    │
│  │  │  - Loads .js/.ts files from disk                    │    │    │
│  │  │  - Caches compiled scripts                          │    │    │
│  │  │  - Handles TypeScript transpilation                 │    │    │
│  │  └─────────────────────────────────────────────────────┘    │    │
│  │  ┌─────────────────────────────────────────────────────┐    │    │
│  │  │  V8ContextPool                                       │    │    │
│  │  │  - Manages pool of V8 isolates                      │    │    │
│  │  │  - Reuses contexts for performance                  │    │    │
│  │  │  - Enforces memory limits                           │    │    │
│  │  └─────────────────────────────────────────────────────┘    │    │
│  │  ┌─────────────────────────────────────────────────────┐    │    │
│  │  │  RuntimeBridge                                       │    │    │
│  │  │  - Injects state, context, ruvon utilities          │    │    │
│  │  │  - Extracts return value                            │    │    │
│  │  │  - Handles errors                                   │    │    │
│  │  └─────────────────────────────────────────────────────┘    │    │
│  └─────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility |
|-----------|----------------|
| **JavaScriptWorkflowStep** | Model holding script path/code and configuration |
| **JavaScriptExecutor** | Orchestrates script loading and execution |
| **ScriptLoader** | Loads files, handles TypeScript, caches compiled code |
| **V8ContextPool** | Manages V8 isolate lifecycle and pooling |
| **RuntimeBridge** | Serializes state in, deserializes results out |

---

## 4. Data Model

### 4.1 JavaScriptConfig (Pydantic Model)

```python
# src/ruvon/models.py

from pydantic import BaseModel, Field, model_validator
from typing import Optional, Dict, Any, Literal
from pathlib import Path

class JavaScriptConfig(BaseModel):
    """Configuration for JavaScript step execution."""

    # Script source (one required)
    script_path: Optional[str] = Field(
        None,
        description="Path to .js or .ts file (relative to config_dir or absolute)"
    )
    code: Optional[str] = Field(
        None,
        description="Inline JavaScript code (for simple scripts)"
    )

    # Execution limits
    timeout_ms: int = Field(
        5000,
        ge=100,
        le=300000,
        description="Maximum execution time in milliseconds"
    )
    memory_limit_mb: int = Field(
        128,
        ge=16,
        le=1024,
        description="Maximum V8 heap size in megabytes"
    )

    # TypeScript options
    typescript: bool = Field(
        False,
        description="Force TypeScript transpilation (auto-detected from .ts extension)"
    )
    tsconfig_path: Optional[str] = Field(
        None,
        description="Path to tsconfig.json for TypeScript options"
    )

    # Output configuration
    output_key: Optional[str] = Field(
        None,
        description="Key to store result in state (default: merge at root)"
    )

    # Advanced options
    strict_mode: bool = Field(
        True,
        description="Execute in JavaScript strict mode"
    )

    @model_validator(mode='after')
    def validate_script_source(self):
        if not self.script_path and not self.code:
            raise ValueError("Either 'script_path' or 'code' must be provided")
        if self.script_path and self.code:
            raise ValueError("Cannot specify both 'script_path' and 'code'")
        return self
```

### 4.2 JavaScriptWorkflowStep

```python
# src/ruvon/models.py

class JavaScriptWorkflowStep(WorkflowStep):
    """Workflow step that executes JavaScript/TypeScript code."""

    js_config: JavaScriptConfig

    # Inherit from WorkflowStep
    merge_strategy: MergeStrategy = MergeStrategy.SHALLOW
    merge_conflict_behavior: MergeConflictBehavior = MergeConflictBehavior.PREFER_NEW
```

### 4.3 Execution Result

```python
# src/ruvon/javascript/types.py

from dataclasses import dataclass
from typing import Dict, Any, Optional, List

@dataclass
class JSExecutionResult:
    """Result of JavaScript execution."""
    success: bool
    result: Optional[Dict[str, Any]]  # Return value from script
    error: Optional[str]               # Error message if failed
    error_type: Optional[str]          # 'timeout', 'memory', 'syntax', 'runtime'
    execution_time_ms: float           # Actual execution time
    memory_used_mb: float              # Peak memory usage
    logs: List[str]                    # Captured console.log outputs
```

---

## 5. Execution Flow

### 5.1 Step-by-Step Flow

```
1. YAML Parsing (WorkflowBuilder)
   ├── Detect type="JAVASCRIPT"
   ├── Parse js_config
   ├── Validate configuration
   └── Create JavaScriptWorkflowStep

2. Step Execution (ExecutionProvider)
   ├── Receive JavaScriptWorkflowStep
   ├── Serialize workflow state to JSON
   ├── Serialize step context to JSON
   └── Call JavaScriptExecutor.execute()

3. Script Loading (ScriptLoader)
   ├── Check cache for compiled script
   ├── If cache miss:
   │   ├── Read file from disk (or use inline code)
   │   ├── If .ts file: transpile with esbuild
   │   ├── Wrap in execution harness
   │   └── Cache compiled script
   └── Return compiled script

4. Context Preparation (RuntimeBridge)
   ├── Create V8 context from pool
   ├── Inject 'state' global (frozen object)
   ├── Inject 'context' global (frozen object)
   ├── Inject 'ruvon' utilities (frozen object)
   └── Return prepared context

5. Script Execution (V8ContextPool)
   ├── Set timeout alarm
   ├── Set memory limit
   ├── Execute script in isolate
   ├── Capture return value
   ├── Capture console.log outputs
   └── Return to pool (or destroy on error)

6. Result Processing (RuntimeBridge)
   ├── Parse return value from V8
   ├── Validate return is object/dict
   ├── Create JSExecutionResult
   └── Return to ExecutionProvider

7. State Merge (ExecutionProvider)
   ├── Apply merge_strategy
   ├── Handle merge conflicts
   ├── Update workflow state
   └── Continue to next step
```

### 5.2 Script Execution Wrapper

Scripts are wrapped in a harness that:
1. Provides consistent execution environment
2. Captures return value
3. Handles errors gracefully

```javascript
// Generated wrapper (internal)
"use strict";

// Injected by RuntimeBridge
const state = __RUVON_STATE__;
const context = __RUVON_CONTEXT__;
const ruvon = __RUVON_UTILS__;

// User script executed here
const __result__ = (function() {
    // === USER SCRIPT START ===
    ${userScript}
    // === USER SCRIPT END ===
})();

// Return result for extraction
__result__;
```

---

## 6. TypeScript Support

### 6.1 Transpilation Pipeline

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  .ts file       │ ──► │  esbuild        │ ──► │  .js (in-memory)│
│  (TypeScript)   │     │  transpile()    │     │  (ES2020)       │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

### 6.2 esbuild Configuration

```python
# src/ruvon/javascript/typescript.py

import subprocess
import json
from pathlib import Path
from typing import Optional

class TypeScriptTranspiler:
    """Transpiles TypeScript to JavaScript using esbuild."""

    def __init__(self, tsconfig_path: Optional[Path] = None):
        self.tsconfig_path = tsconfig_path
        self._verify_esbuild()

    def _verify_esbuild(self):
        """Verify esbuild is installed."""
        try:
            subprocess.run(
                ["esbuild", "--version"],
                capture_output=True,
                check=True
            )
        except FileNotFoundError:
            raise RuntimeError(
                "esbuild not found. Install with: pip install esbuild"
            )

    def transpile(self, source: str, filename: str = "script.ts") -> str:
        """Transpile TypeScript source to JavaScript."""
        result = subprocess.run(
            [
                "esbuild",
                "--bundle=false",        # Don't bundle imports (yet)
                "--format=iife",         # Wrap in IIFE
                "--target=es2020",       # Target ES2020 (V8 compatible)
                "--loader=ts",           # Input is TypeScript
                "--platform=neutral",    # No Node.js builtins
            ],
            input=source.encode('utf-8'),
            capture_output=True,
            check=True
        )
        return result.stdout.decode('utf-8')

    def transpile_file(self, file_path: Path) -> str:
        """Transpile TypeScript file to JavaScript."""
        source = file_path.read_text(encoding='utf-8')
        return self.transpile(source, filename=file_path.name)
```

### 6.3 Type Definitions for Ruvon Utilities

Provide `.d.ts` files for TypeScript intellisense:

```typescript
// types/ruvon.d.ts (shipped with SDK for IDE support)

declare global {
    /**
     * Current workflow state (read-only).
     * Type this in your script for full intellisense.
     */
    const state: Readonly<Record<string, any>>;

    /**
     * Step execution context (read-only).
     */
    const context: Readonly<{
        workflow_id: string;
        step_name: string;
        workflow_type: string;
        previous_step_result: Record<string, any> | null;
    }>;

    /**
     * Ruvon utility functions.
     */
    const ruvon: {
        /** Current ISO timestamp */
        now(): string;

        /** Generate UUID v4 */
        uuid(): string;

        /** Sum array of numbers */
        sum(arr: number[]): number;

        /** Average of array of numbers */
        avg(arr: number[]): number;

        /** Safe JSON parse (returns null on error) */
        parseJSON<T = any>(str: string): T | null;

        /** Log message (captured for audit) */
        log(message: string): void;

        /** Log warning (captured for audit) */
        warn(message: string): void;

        /** Log error (captured for audit) */
        error(message: string): void;
    };
}

export {};
```

### 6.4 Example TypeScript Script

```typescript
// scripts/calculate_discount.ts

interface OrderItem {
    sku: string;
    price: number;
    quantity: number;
}

interface DiscountResult {
    subtotal: number;
    discount_percent: number;
    discount_amount: number;
    final_total: number;
    applied_at: string;
}

// Type the state for this workflow
interface OrderState {
    customer_tier: 'bronze' | 'silver' | 'gold' | 'platinum';
    items: OrderItem[];
    promo_code?: string;
}

// Cast state to typed version
const orderState = state as OrderState;

// Calculate subtotal
const subtotal = orderState.items.reduce(
    (sum, item) => sum + (item.price * item.quantity),
    0
);

// Determine discount based on tier
const tierDiscounts: Record<string, number> = {
    bronze: 0,
    silver: 0.05,
    gold: 0.10,
    platinum: 0.15
};

let discountPercent = tierDiscounts[orderState.customer_tier] || 0;

// Apply promo code bonus
if (orderState.promo_code === 'EXTRA10') {
    discountPercent += 0.10;
}

// Cap discount at 25%
discountPercent = Math.min(discountPercent, 0.25);

const discountAmount = subtotal * discountPercent;
const finalTotal = subtotal - discountAmount;

ruvon.log(`Calculated discount: ${discountPercent * 100}% for ${orderState.customer_tier} tier`);

// Return result (will be merged into workflow state)
const result: DiscountResult = {
    subtotal: Math.round(subtotal * 100) / 100,
    discount_percent: discountPercent * 100,
    discount_amount: Math.round(discountAmount * 100) / 100,
    final_total: Math.round(finalTotal * 100) / 100,
    applied_at: ruvon.now()
};

return result;
```

---

## 7. Security Model

### 7.1 Sandboxing Layers

```
┌─────────────────────────────────────────────────────────────────┐
│  Layer 1: V8 Isolate Sandbox                                    │
│  - Separate memory space                                        │
│  - No access to Python runtime                                  │
│  - No access to file system                                     │
│  - No network access                                            │
└─────────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────────┐
│  Layer 2: API Restriction                                       │
│  - No eval() / Function() constructor                           │
│  - No setTimeout / setInterval                                  │
│  - No require() / import                                        │
│  - No global object modification                                │
└─────────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────────┐
│  Layer 3: Resource Limits                                       │
│  - Execution timeout (default: 5s, max: 5min)                   │
│  - Memory limit (default: 128MB, max: 1GB)                      │
│  - Script size limit (default: 1MB)                             │
└─────────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────────┐
│  Layer 4: Input/Output Validation                               │
│  - State is frozen (Object.freeze)                              │
│  - Return value must be JSON-serializable                       │
│  - No circular references                                       │
└─────────────────────────────────────────────────────────────────┘
```

### 7.2 Blocked APIs

```python
# src/ruvon/javascript/sandbox.py

BLOCKED_GLOBALS = [
    'eval',
    'Function',
    'setTimeout',
    'setInterval',
    'setImmediate',
    'clearTimeout',
    'clearInterval',
    'clearImmediate',
    'require',
    'import',
    'process',
    'global',
    'globalThis',  # Replaced with frozen version
    '__proto__',
    'constructor',
]

SANDBOX_SETUP = """
// Remove dangerous globals
const _blocked = %s;
for (const name of _blocked) {
    try {
        Object.defineProperty(globalThis, name, {
            value: undefined,
            writable: false,
            configurable: false
        });
    } catch (e) {}
}

// Freeze Object prototype to prevent pollution
Object.freeze(Object.prototype);
Object.freeze(Array.prototype);
Object.freeze(Function.prototype);
""" % json.dumps(BLOCKED_GLOBALS)
```

### 7.3 State Injection (Read-Only)

```python
def inject_state(ctx: MiniRacer, state: dict, context: dict) -> None:
    """Inject state as frozen read-only object."""
    ctx.eval(f"""
        const state = Object.freeze({json.dumps(state)});
        const context = Object.freeze({json.dumps(context)});
    """)
```

---

## 8. File Structure

```
src/ruvon/
├── javascript/
│   ├── __init__.py              # Public API exports
│   ├── executor.py              # JavaScriptExecutor main class
│   ├── loader.py                # ScriptLoader (file loading, caching)
│   ├── context_pool.py          # V8ContextPool (isolate management)
│   ├── bridge.py                # RuntimeBridge (state injection)
│   ├── typescript.py            # TypeScriptTranspiler
│   ├── sandbox.py               # Security sandbox setup
│   ├── builtins.py              # Ruvon utility functions
│   └── types.py                 # Type definitions (JSExecutionResult)
├── models.py                    # Add JavaScriptConfig, JavaScriptWorkflowStep
├── builder.py                   # Add JAVASCRIPT step type parsing
└── implementations/
    └── execution/
        └── sync.py              # Update to handle JS steps

types/
└── ruvon.d.ts                   # TypeScript declarations for IDE support

tests/
└── javascript/
    ├── __init__.py
    ├── test_executor.py         # Unit tests for executor
    ├── test_loader.py           # Unit tests for script loader
    ├── test_typescript.py       # TypeScript transpilation tests
    ├── test_sandbox.py          # Security sandbox tests
    ├── test_integration.py      # End-to-end workflow tests
    └── fixtures/
        ├── simple.js            # Test JavaScript file
        ├── typescript.ts        # Test TypeScript file
        ├── with_error.js        # Error handling test
        └── timeout.js           # Timeout test

examples/
└── javascript_workflow/
    ├── README.md
    ├── config/
    │   ├── workflow_registry.yaml
    │   └── data_transform_workflow.yaml
    ├── scripts/
    │   ├── validate_input.ts
    │   ├── calculate_totals.ts
    │   └── format_output.js
    ├── state_models.py
    └── main.py
```

---

## 9. Implementation Phases

### Phase 1: Core Infrastructure (MVP)

**Duration**: ~3-4 hours of focused implementation

| Task | Files | Description |
|------|-------|-------------|
| 1.1 | `models.py` | Add `JavaScriptConfig`, `JavaScriptWorkflowStep` |
| 1.2 | `javascript/types.py` | Add `JSExecutionResult` dataclass |
| 1.3 | `javascript/sandbox.py` | Security sandbox setup code |
| 1.4 | `javascript/builtins.py` | Ruvon utility functions (JS code) |
| 1.5 | `javascript/bridge.py` | State injection, result extraction |
| 1.6 | `javascript/context_pool.py` | V8 context pool management |
| 1.7 | `javascript/loader.py` | Script file loading with caching |
| 1.8 | `javascript/executor.py` | Main executor orchestration |
| 1.9 | `javascript/__init__.py` | Public API exports |

### Phase 2: TypeScript Support

**Duration**: ~1-2 hours

| Task | Files | Description |
|------|-------|-------------|
| 2.1 | `javascript/typescript.py` | esbuild-based transpilation |
| 2.2 | `javascript/loader.py` | Update to handle .ts files |
| 2.3 | `types/ruvon.d.ts` | TypeScript declarations |
| 2.4 | `requirements.txt` | Add esbuild dependency |

### Phase 3: Integration

**Duration**: ~2 hours

| Task | Files | Description |
|------|-------|-------------|
| 3.1 | `builder.py` | Parse JAVASCRIPT step type |
| 3.2 | `implementations/execution/sync.py` | Handle JS step execution |
| 3.3 | CLI validation | Validate JS step configuration |

### Phase 4: Testing

**Duration**: ~2-3 hours

| Task | Files | Description |
|------|-------|-------------|
| 4.1 | `tests/javascript/test_executor.py` | Unit tests |
| 4.2 | `tests/javascript/test_typescript.py` | TS transpilation tests |
| 4.3 | `tests/javascript/test_sandbox.py` | Security tests |
| 4.4 | `tests/javascript/test_integration.py` | E2E workflow tests |
| 4.5 | `tests/javascript/fixtures/` | Test scripts |

### Phase 5: Documentation & Examples

**Duration**: ~1-2 hours

| Task | Files | Description |
|------|-------|-------------|
| 5.1 | `USAGE_GUIDE.md` | Section 8.2: JavaScript Steps |
| 5.2 | `API_REFERENCE.md` | JavaScriptWorkflowStep docs |
| 5.3 | `CLAUDE.md` | Quick reference |
| 5.4 | `examples/javascript_workflow/` | Complete working example |

---

## 10. YAML Configuration

### 10.1 File-Based Script (Recommended)

```yaml
workflow_type: "DataTransformWorkflow"
initial_state_model: "my_app.models.TransformState"

steps:
  - name: "Calculate_Totals"
    type: "JAVASCRIPT"
    js_config:
      script_path: "scripts/calculate_totals.ts"  # Relative to config_dir
      timeout_ms: 5000
      memory_limit_mb: 128
    automate_next: true

  - name: "Format_Output"
    type: "JAVASCRIPT"
    js_config:
      script_path: "scripts/format_output.js"
      output_key: "formatted_data"  # Store result under this key
    automate_next: true
```

### 10.2 Inline Script (For Simple Logic)

```yaml
steps:
  - name: "Quick_Calculation"
    type: "JAVASCRIPT"
    js_config:
      code: |
        const total = state.items.reduce((sum, item) => sum + item.price, 0);
        const tax = total * 0.08;
        return {
          subtotal: total,
          tax: tax,
          grand_total: total + tax
        };
      timeout_ms: 1000
    automate_next: true
```

### 10.3 TypeScript with Custom Config

```yaml
steps:
  - name: "Complex_Transform"
    type: "JAVASCRIPT"
    js_config:
      script_path: "scripts/complex_transform.ts"
      typescript: true  # Force TS even without .ts extension
      tsconfig_path: "tsconfig.json"  # Custom TypeScript config
      timeout_ms: 10000
      memory_limit_mb: 256
    merge_strategy: "DEEP"
    automate_next: true
```

### 10.4 Full Configuration Reference

```yaml
- name: "Step_Name"
  type: "JAVASCRIPT"
  js_config:
    # Script source (one required)
    script_path: "path/to/script.js"  # OR
    code: "return { result: state.value * 2 };"

    # Execution limits
    timeout_ms: 5000        # Default: 5000, Range: 100-300000
    memory_limit_mb: 128    # Default: 128, Range: 16-1024

    # TypeScript options
    typescript: false       # Default: auto-detect from .ts extension
    tsconfig_path: null     # Optional: path to tsconfig.json

    # Output
    output_key: null        # Optional: key to store result (default: merge at root)

    # Advanced
    strict_mode: true       # Default: true (use strict)

  # Standard step options
  automate_next: true
  merge_strategy: "SHALLOW"  # SHALLOW or DEEP
  merge_conflict_behavior: "PREFER_NEW"  # PREFER_NEW, PREFER_OLD, RAISE_ERROR
```

---

## 11. Built-in Utilities (ruvon object)

### 11.1 JavaScript Implementation

```javascript
// src/ruvon/javascript/builtins.py -> RUVON_BUILTINS_JS

const ruvon = Object.freeze({
    // Logging (captured for audit)
    log: (msg) => __rufus_log__('info', String(msg)),
    warn: (msg) => __rufus_log__('warn', String(msg)),
    error: (msg) => __rufus_log__('error', String(msg)),

    // Date/Time
    now: () => new Date().toISOString(),
    timestamp: () => Date.now(),

    // Identifiers
    uuid: () => __rufus_uuid__(),

    // Math utilities
    sum: (arr) => {
        if (!Array.isArray(arr)) return 0;
        return arr.reduce((a, b) => a + (Number(b) || 0), 0);
    },
    avg: (arr) => {
        if (!Array.isArray(arr) || arr.length === 0) return 0;
        return ruvon.sum(arr) / arr.length;
    },
    min: (arr) => Array.isArray(arr) ? Math.min(...arr) : 0,
    max: (arr) => Array.isArray(arr) ? Math.max(...arr) : 0,
    round: (num, decimals = 0) => {
        const factor = Math.pow(10, decimals);
        return Math.round(num * factor) / factor;
    },

    // String utilities
    slugify: (str) => String(str)
        .toLowerCase()
        .trim()
        .replace(/[^\w\s-]/g, '')
        .replace(/[\s_-]+/g, '-')
        .replace(/^-+|-+$/g, ''),
    truncate: (str, len, suffix = '...') => {
        str = String(str);
        return str.length > len ? str.slice(0, len - suffix.length) + suffix : str;
    },

    // JSON utilities
    parseJSON: (str) => {
        try { return JSON.parse(str); }
        catch { return null; }
    },

    // Object utilities
    pick: (obj, keys) => {
        const result = {};
        for (const key of keys) {
            if (key in obj) result[key] = obj[key];
        }
        return result;
    },
    omit: (obj, keys) => {
        const result = { ...obj };
        for (const key of keys) delete result[key];
        return result;
    },

    // Array utilities
    unique: (arr) => [...new Set(arr)],
    groupBy: (arr, key) => {
        return arr.reduce((acc, item) => {
            const group = item[key];
            (acc[group] = acc[group] || []).push(item);
            return acc;
        }, {});
    },
    sortBy: (arr, key, desc = false) => {
        return [...arr].sort((a, b) => {
            const aVal = a[key], bVal = b[key];
            const cmp = aVal < bVal ? -1 : aVal > bVal ? 1 : 0;
            return desc ? -cmp : cmp;
        });
    },

    // Validation utilities
    isEmail: (str) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(String(str)),
    isURL: (str) => {
        try { new URL(String(str)); return true; }
        catch { return false; }
    },
    isEmpty: (val) => {
        if (val == null) return true;
        if (Array.isArray(val) || typeof val === 'string') return val.length === 0;
        if (typeof val === 'object') return Object.keys(val).length === 0;
        return false;
    }
});
```

### 11.2 Python Bridge Functions

```python
# src/ruvon/javascript/builtins.py

import uuid
from typing import List, Tuple

class BuiltinsBridge:
    """Python-side implementation of ruvon.* functions that need Python."""

    def __init__(self):
        self.logs: List[Tuple[str, str]] = []  # (level, message)

    def log(self, level: str, message: str) -> None:
        """Capture log message."""
        self.logs.append((level, message))

    def uuid(self) -> str:
        """Generate UUID v4."""
        return str(uuid.uuid4())

    def get_logs(self) -> List[Tuple[str, str]]:
        """Return captured logs."""
        return self.logs.copy()

    def clear_logs(self) -> None:
        """Clear captured logs."""
        self.logs.clear()
```

---

## 12. Error Handling

### 12.1 Error Types

| Error Type | Cause | Workflow Status |
|------------|-------|-----------------|
| `syntax` | JavaScript syntax error | FAILED |
| `runtime` | Runtime exception (TypeError, etc.) | FAILED |
| `timeout` | Execution exceeded timeout_ms | FAILED |
| `memory` | V8 heap exceeded memory_limit_mb | FAILED |
| `file_not_found` | Script file doesn't exist | FAILED |
| `transpile` | TypeScript transpilation failed | FAILED |

### 12.2 Error Response Format

```python
@dataclass
class JSExecutionResult:
    success: bool = False
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    error_type: Optional[str] = None  # 'syntax', 'runtime', 'timeout', 'memory', etc.
    error_line: Optional[int] = None  # Line number if available
    error_column: Optional[int] = None  # Column number if available
    stack_trace: Optional[str] = None  # JS stack trace
    execution_time_ms: float = 0.0
    memory_used_mb: float = 0.0
    logs: List[Tuple[str, str]] = field(default_factory=list)
```

### 12.3 Error Handling in Workflow

```yaml
steps:
  - name: "Run_Script"
    type: "JAVASCRIPT"
    js_config:
      script_path: "scripts/process.js"
    automate_next: true

  - name: "Check_Script_Result"
    type: "DECISION"
    function: "steps.check_js_result"
    routes:
      - condition: "state._js_error is not None"
        target: "Handle_Script_Error"
      - default: "Continue_Processing"
```

---

## 13. Testing Strategy

### 13.1 Unit Tests

```python
# tests/javascript/test_executor.py

import pytest
from ruvon.javascript import JavaScriptExecutor
from ruvon.javascript.types import JSExecutionResult

class TestJavaScriptExecutor:

    @pytest.fixture
    def executor(self):
        return JavaScriptExecutor()

    def test_simple_return(self, executor):
        """Test simple value return."""
        result = executor.execute(
            code="return { value: 42 };",
            state={},
            context={}
        )
        assert result.success
        assert result.result == {"value": 42}

    def test_state_access(self, executor):
        """Test accessing workflow state."""
        result = executor.execute(
            code="return { doubled: state.value * 2 };",
            state={"value": 21},
            context={}
        )
        assert result.success
        assert result.result == {"doubled": 42}

    def test_ruvon_utilities(self, executor):
        """Test ruvon.* utility functions."""
        result = executor.execute(
            code="""
                const total = ruvon.sum([1, 2, 3, 4, 5]);
                return { total, timestamp: ruvon.now() };
            """,
            state={},
            context={}
        )
        assert result.success
        assert result.result["total"] == 15
        assert "timestamp" in result.result

    def test_timeout(self, executor):
        """Test execution timeout."""
        result = executor.execute(
            code="while(true) {}",  # Infinite loop
            state={},
            context={},
            timeout_ms=100
        )
        assert not result.success
        assert result.error_type == "timeout"

    def test_syntax_error(self, executor):
        """Test syntax error handling."""
        result = executor.execute(
            code="return { invalid syntax",
            state={},
            context={}
        )
        assert not result.success
        assert result.error_type == "syntax"

    def test_runtime_error(self, executor):
        """Test runtime error handling."""
        result = executor.execute(
            code="return { value: nonexistent.property };",
            state={},
            context={}
        )
        assert not result.success
        assert result.error_type == "runtime"

    def test_state_immutable(self, executor):
        """Test that state cannot be modified."""
        result = executor.execute(
            code="""
                try {
                    state.value = 999;  // Should fail
                    return { modified: true };
                } catch (e) {
                    return { modified: false, error: e.message };
                }
            """,
            state={"value": 42},
            context={}
        )
        assert result.success
        assert result.result["modified"] == False

    def test_blocked_apis(self, executor):
        """Test that dangerous APIs are blocked."""
        for blocked in ['eval', 'Function', 'setTimeout']:
            result = executor.execute(
                code=f"return {{ available: typeof {blocked} !== 'undefined' }};",
                state={},
                context={}
            )
            assert result.success
            assert result.result["available"] == False, f"{blocked} should be blocked"
```

### 13.2 TypeScript Tests

```python
# tests/javascript/test_typescript.py

import pytest
from ruvon.javascript.typescript import TypeScriptTranspiler

class TestTypeScriptTranspiler:

    @pytest.fixture
    def transpiler(self):
        return TypeScriptTranspiler()

    def test_basic_transpilation(self, transpiler):
        """Test basic TypeScript transpilation."""
        ts_code = """
            interface Result {
                value: number;
            }
            const result: Result = { value: 42 };
            return result;
        """
        js_code = transpiler.transpile(ts_code)
        assert "interface" not in js_code  # Type stripped
        assert "value" in js_code

    def test_type_annotations_stripped(self, transpiler):
        """Test that type annotations are removed."""
        ts_code = """
            function add(a: number, b: number): number {
                return a + b;
            }
            return { sum: add(1, 2) };
        """
        js_code = transpiler.transpile(ts_code)
        assert ": number" not in js_code

    def test_syntax_error(self, transpiler):
        """Test TypeScript syntax error handling."""
        with pytest.raises(Exception) as exc_info:
            transpiler.transpile("const x: = 5;")  # Invalid syntax
        assert "error" in str(exc_info.value).lower()
```

### 13.3 Integration Tests

```python
# tests/javascript/test_integration.py

import pytest
from pathlib import Path
from ruvon.builder import WorkflowBuilder
from ruvon.implementations.persistence.memory import InMemoryPersistence
from ruvon.implementations.execution.sync import SyncExecutor

class TestJavaScriptWorkflowIntegration:

    @pytest.fixture
    def workflow_builder(self, tmp_path):
        """Create workflow builder with test config."""
        # Create test workflow YAML
        config_dir = tmp_path / "config"
        config_dir.mkdir()

        # Create scripts directory
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()

        # Write test script
        (scripts_dir / "calculate.js").write_text("""
            const total = ruvon.sum(state.items.map(i => i.price));
            return {
                total: total,
                item_count: state.items.length,
                calculated_at: ruvon.now()
            };
        """)

        # Write workflow YAML
        (config_dir / "js_workflow.yaml").write_text("""
            workflow_type: "JSTestWorkflow"
            initial_state_model: "pydantic.BaseModel"
            steps:
              - name: "Calculate_Totals"
                type: "JAVASCRIPT"
                js_config:
                  script_path: "../scripts/calculate.js"
                automate_next: true
        """)

        # Write registry
        (config_dir / "workflow_registry.yaml").write_text("""
            workflows:
              - type: "JSTestWorkflow"
                config_file: "js_workflow.yaml"
        """)

        return WorkflowBuilder(
            config_dir=str(config_dir),
            persistence=InMemoryPersistence(),
            executor=SyncExecutor()
        )

    @pytest.mark.asyncio
    async def test_javascript_workflow_execution(self, workflow_builder):
        """Test full JavaScript workflow execution."""
        workflow = await workflow_builder.create_workflow(
            workflow_type="JSTestWorkflow",
            initial_data={
                "items": [
                    {"name": "Item A", "price": 10},
                    {"name": "Item B", "price": 20},
                    {"name": "Item C", "price": 30}
                ]
            }
        )

        result, next_step = await workflow.next_step({})

        assert workflow.state.total == 60
        assert workflow.state.item_count == 3
        assert "calculated_at" in workflow.state.dict()
```

---

## 14. Documentation Updates

### 14.1 Files to Update

| File | Section | Changes |
|------|---------|---------|
| `USAGE_GUIDE.md` | New Section 8.2 | JavaScript Steps documentation |
| `API_REFERENCE.md` | Models section | JavaScriptWorkflowStep, JavaScriptConfig |
| `CLAUDE.md` | Key Patterns | JavaScript step quick reference |
| `README.md` | Features | Mention JS step support |
| `TECHNICAL_DOCUMENTATION.md` | New section | JavaScript execution architecture |

### 14.2 USAGE_GUIDE.md Section 8.2

```markdown
### 8.2 JavaScript Steps (Embedded Scripting)

JavaScript steps allow you to execute JavaScript or TypeScript code directly within your workflow, without external services or HTTP calls. Scripts run in a sandboxed V8 environment with no system access.

#### When to Use JavaScript Steps

| Use Case | JavaScript Step | HTTP Step |
|----------|-----------------|-----------|
| Data transformation | ✅ Ideal | Overkill |
| Business rules | ✅ Ideal | Overkill |
| Validation logic | ✅ Ideal | Overkill |
| Complex calculations | ✅ Good | Alternative |
| External API calls | ❌ No network | ✅ Required |
| System operations | ❌ No access | ✅ Via service |

#### Basic Example (File-Based)

**Workflow YAML:**
```yaml
steps:
  - name: "Calculate_Discount"
    type: "JAVASCRIPT"
    js_config:
      script_path: "scripts/calculate_discount.js"
      timeout_ms: 5000
    automate_next: true
```

**scripts/calculate_discount.js:**
```javascript
// Access workflow state
const subtotal = state.items.reduce((sum, item) => sum + item.price, 0);

// Use ruvon utilities
const discountRate = state.is_member ? 0.10 : 0;
ruvon.log(`Applying ${discountRate * 100}% discount`);

// Return result (merged into workflow state)
return {
    subtotal: subtotal,
    discount: subtotal * discountRate,
    total: subtotal * (1 - discountRate),
    calculated_at: ruvon.now()
};
```

#### TypeScript Support

JavaScript steps fully support TypeScript. Files with `.ts` extension are automatically transpiled.

**scripts/calculate_discount.ts:**
```typescript
interface CartItem {
    name: string;
    price: number;
    quantity: number;
}

interface DiscountResult {
    subtotal: number;
    discount: number;
    total: number;
}

const items = state.items as CartItem[];
const subtotal = items.reduce((sum, item) => sum + item.price * item.quantity, 0);

const result: DiscountResult = {
    subtotal,
    discount: subtotal * 0.1,
    total: subtotal * 0.9
};

return result;
```

#### Available Globals

| Global | Description |
|--------|-------------|
| `state` | Workflow state (read-only) |
| `context` | Step context (workflow_id, step_name, etc.) |
| `ruvon` | Utility functions (see below) |

#### Ruvon Utilities

```javascript
// Logging
ruvon.log("Info message");
ruvon.warn("Warning message");
ruvon.error("Error message");

// Date/Time
ruvon.now();        // ISO timestamp
ruvon.timestamp();  // Unix milliseconds

// Identifiers
ruvon.uuid();       // UUID v4

// Math
ruvon.sum([1, 2, 3]);      // 6
ruvon.avg([1, 2, 3]);      // 2
ruvon.min([1, 2, 3]);      // 1
ruvon.max([1, 2, 3]);      // 3
ruvon.round(3.14159, 2);   // 3.14

// Strings
ruvon.slugify("Hello World");     // "hello-world"
ruvon.truncate("Long text", 10);  // "Long te..."

// JSON
ruvon.parseJSON('{"a":1}');  // {a: 1} or null on error

// Objects
ruvon.pick(obj, ['a', 'b']);  // Pick keys
ruvon.omit(obj, ['c', 'd']);  // Omit keys

// Arrays
ruvon.unique([1, 1, 2]);           // [1, 2]
ruvon.groupBy(arr, 'category');    // Group by key
ruvon.sortBy(arr, 'name');         // Sort by key

// Validation
ruvon.isEmail("test@example.com");  // true
ruvon.isURL("https://...");         // true
ruvon.isEmpty(value);               // true if null/empty
```

#### Security Model

JavaScript steps run in a sandboxed V8 isolate with:

- ❌ No file system access
- ❌ No network access
- ❌ No `eval()` or `Function()` constructor
- ❌ No `setTimeout`/`setInterval`
- ❌ No `require()` or `import`
- ✅ Read-only access to workflow state
- ✅ Configurable timeout (default: 5s)
- ✅ Configurable memory limit (default: 128MB)
```

---

## 15. Example Implementation

### 15.1 Directory Structure

```
examples/javascript_workflow/
├── README.md
├── requirements.txt
├── config/
│   ├── workflow_registry.yaml
│   └── order_processing.yaml
├── scripts/
│   ├── validate_order.ts
│   ├── calculate_totals.ts
│   ├── apply_promotions.js
│   └── format_receipt.js
├── state_models.py
└── main.py
```

### 15.2 Example Workflow YAML

```yaml
# config/order_processing.yaml
workflow_type: "OrderProcessing"
workflow_version: "1.0.0"
initial_state_model: "state_models.OrderState"
description: "Process orders using JavaScript for business logic"

steps:
  # TypeScript: Validate order input
  - name: "Validate_Order"
    type: "JAVASCRIPT"
    js_config:
      script_path: "../scripts/validate_order.ts"
      timeout_ms: 2000
    automate_next: true

  # TypeScript: Calculate totals with tax
  - name: "Calculate_Totals"
    type: "JAVASCRIPT"
    js_config:
      script_path: "../scripts/calculate_totals.ts"
      timeout_ms: 3000
    automate_next: true

  # JavaScript: Apply promotional discounts
  - name: "Apply_Promotions"
    type: "JAVASCRIPT"
    js_config:
      script_path: "../scripts/apply_promotions.js"
      timeout_ms: 2000
    automate_next: true

  # JavaScript: Format receipt output
  - name: "Format_Receipt"
    type: "JAVASCRIPT"
    js_config:
      script_path: "../scripts/format_receipt.js"
      output_key: "receipt"
    automate_next: true

  # Python: Final processing (database, notifications)
  - name: "Finalize_Order"
    type: "STANDARD"
    function: "steps.finalize_order"
```

### 15.3 Example TypeScript Script

```typescript
// scripts/validate_order.ts

interface OrderItem {
    sku: string;
    name: string;
    price: number;
    quantity: number;
}

interface OrderState {
    customer_id: string;
    items: OrderItem[];
    shipping_address?: {
        street: string;
        city: string;
        zip: string;
        country: string;
    };
}

interface ValidationResult {
    is_valid: boolean;
    errors: string[];
    validated_at: string;
}

// Cast state to typed version
const order = state as OrderState;
const errors: string[] = [];

// Validate customer
if (!order.customer_id || order.customer_id.trim() === '') {
    errors.push('Customer ID is required');
}

// Validate items
if (!order.items || order.items.length === 0) {
    errors.push('Order must contain at least one item');
} else {
    order.items.forEach((item, index) => {
        if (item.price < 0) {
            errors.push(`Item ${index + 1}: Price cannot be negative`);
        }
        if (item.quantity < 1) {
            errors.push(`Item ${index + 1}: Quantity must be at least 1`);
        }
        if (!item.sku || item.sku.trim() === '') {
            errors.push(`Item ${index + 1}: SKU is required`);
        }
    });
}

// Validate shipping address
if (order.shipping_address) {
    const addr = order.shipping_address;
    if (!addr.street) errors.push('Shipping street is required');
    if (!addr.city) errors.push('Shipping city is required');
    if (!addr.zip) errors.push('Shipping ZIP code is required');
    if (!addr.country) errors.push('Shipping country is required');
}

// Log validation result
if (errors.length > 0) {
    ruvon.warn(`Order validation failed: ${errors.length} errors`);
} else {
    ruvon.log('Order validation passed');
}

// Return validation result
const result: ValidationResult = {
    is_valid: errors.length === 0,
    errors: errors,
    validated_at: ruvon.now()
};

return result;
```

---

## 16. Future: NPM Package Support

### 16.1 Architecture for Phase 2

```
┌─────────────────────────────────────────────────────────────────┐
│  Phase 2: NPM Package Support                                   │
│                                                                 │
│  scripts/                                                       │
│  ├── package.json          # NPM dependencies                  │
│  ├── node_modules/         # Installed packages (gitignored)   │
│  └── my_script.ts          # Can import from node_modules      │
│                                                                 │
│  Build Process:                                                 │
│  1. npm install (or pnpm/yarn)                                 │
│  2. esbuild bundles script + dependencies                      │
│  3. Bundled JS executed in V8 isolate                          │
│                                                                 │
│  Supported packages:                                           │
│  - Pure JavaScript (lodash, date-fns, etc.)                   │
│  - No Node.js built-ins (fs, http, etc.)                      │
│  - No native modules (compiled C/C++)                         │
└─────────────────────────────────────────────────────────────────┘
```

### 16.2 Configuration for Phase 2

```yaml
# Future syntax (Phase 2)
- name: "Complex_Transform"
  type: "JAVASCRIPT"
  js_config:
    script_path: "scripts/transform.ts"

    # NPM package configuration
    npm:
      enabled: true
      package_json: "scripts/package.json"
      install_on_startup: true  # Run npm install if needed

    # Bundle options
    bundle:
      enabled: true
      external: []  # Packages to NOT bundle
      minify: false
```

### 16.3 Preparation in Phase 1

- Design `ScriptLoader` to support future bundling
- Keep esbuild for TypeScript (it handles bundling too)
- Document npm support as planned feature
- Architecture supports adding `BundleManager` component

---

## 17. Migration Path

### 17.1 From Inline Code to File-Based

```yaml
# Before (inline)
- name: "Calculate"
  type: "JAVASCRIPT"
  js_config:
    code: |
      const total = state.items.reduce((s, i) => s + i.price, 0);
      return { total };

# After (file-based)
- name: "Calculate"
  type: "JAVASCRIPT"
  js_config:
    script_path: "scripts/calculate.js"
```

### 17.2 From HTTP Step to JavaScript Step

```yaml
# Before (HTTP step calling internal service)
- name: "Calculate_Discount"
  type: "HTTP"
  http_config:
    method: "POST"
    url: "http://discount-service/api/calculate"
    body:
      customer_tier: "{{state.customer_tier}}"
      subtotal: "{{state.subtotal}}"

# After (JavaScript step - no service needed)
- name: "Calculate_Discount"
  type: "JAVASCRIPT"
  js_config:
    script_path: "scripts/calculate_discount.ts"
```

---

## 18. Open Questions

### For Review

1. **Runtime selection**: PyMiniRacer vs QuickJS - confirm PyMiniRacer as primary?

2. **TypeScript transpiler**: esbuild vs tsc - confirm esbuild?

3. **Script path resolution**: Relative to config_dir or workflow YAML file?

4. **Default timeout**: 5 seconds reasonable? Or should it be 10s?

5. **Memory limit**: 128MB default reasonable? Range 16MB-1GB?

6. **Inline code limit**: Should we limit inline code size? (e.g., 10KB max)

7. **Script caching**: Cache compiled scripts in memory? LRU with size limit?

8. **Log capture**: Capture `console.log` or only `ruvon.log`?

9. **Error details**: How much error detail to expose? Stack traces in production?

10. **TypeScript declarations**: Ship `ruvon.d.ts` with SDK? Or separate package?

---

## Approval Checklist

- [ ] Runtime selection approved
- [ ] TypeScript approach approved
- [ ] YAML configuration format approved
- [ ] Security model approved
- [ ] Built-in utilities approved
- [ ] File structure approved
- [ ] Testing strategy approved
- [ ] Documentation plan approved
- [ ] Example scope approved
- [ ] Open questions resolved

---

**Next Steps After Approval:**
1. Create feature branch
2. Implement Phase 1 (Core Infrastructure)
3. Implement Phase 2 (TypeScript Support)
4. Implement Phase 3 (Integration)
5. Implement Phase 4 (Testing)
6. Implement Phase 5 (Documentation & Examples)
7. Code review
8. Merge to main branch

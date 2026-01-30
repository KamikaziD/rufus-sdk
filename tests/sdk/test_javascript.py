"""Tests for JavaScript step execution."""

import os
import pytest
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

from rufus.models import JavaScriptConfig, JavaScriptWorkflowStep, MergeStrategy, MergeConflictBehavior


class TestJavaScriptConfig:
    """Tests for JavaScriptConfig model."""

    def test_config_with_script_path(self):
        """Test config with script path."""
        config = JavaScriptConfig(script_path="scripts/process.js")
        assert config.script_path == "scripts/process.js"
        assert config.code is None
        assert config.timeout_ms == 5000
        assert config.memory_limit_mb == 128

    def test_config_with_inline_code(self):
        """Test config with inline code."""
        config = JavaScriptConfig(code="return { value: state.x * 2 };")
        assert config.code == "return { value: state.x * 2 };"
        assert config.script_path is None

    def test_config_requires_source(self):
        """Test that config requires either script_path or code."""
        with pytest.raises(ValueError, match="Either 'script_path' or 'code' must be provided"):
            JavaScriptConfig()

    def test_config_rejects_both_sources(self):
        """Test that config rejects both script_path and code."""
        with pytest.raises(ValueError, match="Cannot specify both 'script_path' and 'code'"):
            JavaScriptConfig(script_path="test.js", code="return {};")

    def test_config_timeout_limits(self):
        """Test timeout validation."""
        # Valid timeout
        config = JavaScriptConfig(code="return {};", timeout_ms=1000)
        assert config.timeout_ms == 1000

        # Min timeout
        config = JavaScriptConfig(code="return {};", timeout_ms=100)
        assert config.timeout_ms == 100

        # Max timeout
        config = JavaScriptConfig(code="return {};", timeout_ms=300000)
        assert config.timeout_ms == 300000

        # Below min
        with pytest.raises(ValueError):
            JavaScriptConfig(code="return {};", timeout_ms=50)

        # Above max
        with pytest.raises(ValueError):
            JavaScriptConfig(code="return {};", timeout_ms=400000)

    def test_config_memory_limits(self):
        """Test memory limit validation."""
        # Valid memory
        config = JavaScriptConfig(code="return {};", memory_limit_mb=256)
        assert config.memory_limit_mb == 256

        # Min memory
        config = JavaScriptConfig(code="return {};", memory_limit_mb=16)
        assert config.memory_limit_mb == 16

        # Max memory
        config = JavaScriptConfig(code="return {};", memory_limit_mb=1024)
        assert config.memory_limit_mb == 1024

    def test_config_typescript_options(self):
        """Test TypeScript options."""
        config = JavaScriptConfig(
            script_path="process.ts",
            typescript=True,
            tsconfig_path="./tsconfig.json"
        )
        assert config.typescript is True
        assert config.tsconfig_path == "./tsconfig.json"

    def test_config_output_key(self):
        """Test output key configuration."""
        config = JavaScriptConfig(code="return {};", output_key="result_data")
        assert config.output_key == "result_data"


class TestJavaScriptWorkflowStep:
    """Tests for JavaScriptWorkflowStep model."""

    def test_step_creation(self):
        """Test step creation with config."""
        config = JavaScriptConfig(code="return { doubled: state.value * 2 };")
        step = JavaScriptWorkflowStep(name="Double_Value", js_config=config)

        assert step.name == "Double_Value"
        assert step.js_config == config
        assert step.merge_strategy == MergeStrategy.SHALLOW
        assert step.merge_conflict_behavior == MergeConflictBehavior.PREFER_NEW

    def test_step_with_merge_options(self):
        """Test step with custom merge options."""
        config = JavaScriptConfig(code="return {};")
        step = JavaScriptWorkflowStep(
            name="Test_Step",
            js_config=config,
            merge_strategy=MergeStrategy.DEEP,
            merge_conflict_behavior=MergeConflictBehavior.PREFER_EXISTING
        )

        assert step.merge_strategy == MergeStrategy.DEEP
        assert step.merge_conflict_behavior == MergeConflictBehavior.PREFER_EXISTING


# Conditionally run tests that require py_mini_racer
try:
    from rufus.javascript import (
        JavaScriptExecutor, JSExecutionResult, ScriptLoader,
        V8ContextPool, V8Context, RuntimeBridge, is_mini_racer_available
    )
    HAS_MINI_RACER = is_mini_racer_available()
except ImportError:
    HAS_MINI_RACER = False

try:
    from rufus.javascript.typescript import is_esbuild_available
    HAS_ESBUILD = is_esbuild_available()
except ImportError:
    HAS_ESBUILD = False


@pytest.mark.skipif(not HAS_MINI_RACER, reason="py_mini_racer not installed")
class TestJavaScriptExecutor:
    """Tests for JavaScriptExecutor (requires py_mini_racer)."""

    def test_execute_simple_code(self):
        """Test executing simple JavaScript code."""
        executor = JavaScriptExecutor()
        result = executor.execute(
            code="return { doubled: state.value * 2 };",
            state={"value": 21},
            context={"workflow_id": "test-123", "step_name": "double"}
        )

        assert result.success is True
        assert result.result == {"doubled": 42}
        assert result.error is None

    def test_execute_with_state_access(self):
        """Test that scripts can access workflow state."""
        executor = JavaScriptExecutor()
        result = executor.execute(
            code="""
            const items = state.items;
            const total = items.reduce((sum, item) => sum + item.price, 0);
            return { total: total, count: items.length };
            """,
            state={
                "items": [
                    {"name": "A", "price": 10},
                    {"name": "B", "price": 20},
                    {"name": "C", "price": 30}
                ]
            },
            context={"workflow_id": "test-123", "step_name": "calculate"}
        )

        assert result.success is True
        assert result.result == {"total": 60, "count": 3}

    def test_execute_with_context_access(self):
        """Test that scripts can access step context."""
        executor = JavaScriptExecutor()
        result = executor.execute(
            code="return { workflow: context.workflow_id, step: context.step_name };",
            state={},
            context={"workflow_id": "wf-abc", "step_name": "test_step"}
        )

        assert result.success is True
        assert result.result["workflow"] == "wf-abc"
        assert result.result["step"] == "test_step"

    def test_execute_with_rufus_utilities(self):
        """Test that rufus utilities are available."""
        executor = JavaScriptExecutor()

        # Test rufus utilities
        result = executor.execute(
            code="return { rounded: rufus.round(3.7), clamped: rufus.clamp(15, 0, 10) };",
            state={},
            context={}
        )
        assert result.success is True
        assert result.result["rounded"] == 4
        assert result.result["clamped"] == 10

    def test_execute_with_logging(self):
        """Test that console.log is captured."""
        executor = JavaScriptExecutor()
        result = executor.execute(
            code="""
            console.log("Starting calculation");
            const result = state.x + state.y;
            console.log("Result:", result);
            return { sum: result };
            """,
            state={"x": 5, "y": 3},
            context={}
        )

        assert result.success is True
        assert result.result == {"sum": 8}
        assert len(result.logs) >= 2

    def test_execute_timeout(self):
        """Test that timeout is enforced."""
        executor = JavaScriptExecutor()
        result = executor.execute(
            code="while(true) {}; return {};",
            state={},
            context={},
            timeout_ms=100
        )

        assert result.success is False
        assert result.error_type == "timeout"

    def test_execute_syntax_error(self):
        """Test handling of syntax errors."""
        executor = JavaScriptExecutor()
        result = executor.execute(
            code="return { invalid syntax here",
            state={},
            context={}
        )

        assert result.success is False
        assert "syntax" in result.error_type.lower() or "Unexpected" in result.error

    def test_execute_runtime_error(self):
        """Test handling of runtime errors."""
        executor = JavaScriptExecutor()
        result = executor.execute(
            code="return { value: undefinedVariable.property };",
            state={},
            context={}
        )

        assert result.success is False

    def test_execute_returns_primitive(self):
        """Test that primitive return values are wrapped."""
        executor = JavaScriptExecutor()
        result = executor.execute(
            code="return 42;",
            state={},
            context={}
        )

        assert result.success is True
        assert result.result == {"result": 42}

    def test_execute_returns_array(self):
        """Test that array return values are wrapped."""
        executor = JavaScriptExecutor()
        result = executor.execute(
            code="return [1, 2, 3];",
            state={},
            context={}
        )

        assert result.success is True
        assert result.result == {"result": [1, 2, 3]}

    def test_state_is_frozen(self):
        """Test that state cannot be modified."""
        executor = JavaScriptExecutor()
        result = executor.execute(
            code="""
            try {
                state.value = 999;
                return { modified: true };
            } catch (e) {
                return { modified: false, error: e.message };
            }
            """,
            state={"value": 42},
            context={}
        )

        assert result.success is True
        # In strict mode, modifying frozen object throws
        assert result.result.get("modified") is False or result.result.get("error") is not None


@pytest.mark.skipif(not HAS_MINI_RACER, reason="py_mini_racer not installed")
class TestJavaScriptExecutorFiles:
    """Tests for file-based JavaScript execution."""

    def test_execute_file(self):
        """Test executing JavaScript from file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test script
            script_path = Path(tmpdir) / "process.js"
            script_path.write_text("""
                const multiplied = state.value * 3;
                return { result: multiplied };
            """)

            executor = JavaScriptExecutor(config_dir=tmpdir)
            result = executor.execute_file(
                script_path=str(script_path),
                state={"value": 7},
                context={}
            )

            assert result.success is True
            assert result.result == {"result": 21}

    def test_execute_file_not_found(self):
        """Test error handling for missing file."""
        executor = JavaScriptExecutor()
        result = executor.execute_file(
            script_path="/nonexistent/path/script.js",
            state={},
            context={}
        )

        assert result.success is False
        assert result.error_type == "file_not_found"

    def test_execute_relative_path(self):
        """Test executing file with relative path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create scripts subdirectory
            scripts_dir = Path(tmpdir) / "scripts"
            scripts_dir.mkdir()

            script_path = scripts_dir / "transform.js"
            script_path.write_text("return { transformed: true };")

            executor = JavaScriptExecutor(config_dir=tmpdir)
            result = executor.execute_file(
                script_path="scripts/transform.js",
                state={},
                context={}
            )

            assert result.success is True
            assert result.result == {"transformed": True}


class TestScriptLoader:
    """Tests for ScriptLoader (no py_mini_racer required)."""

    def test_load_inline_code(self):
        """Test loading inline code."""
        loader = ScriptLoader()
        compiled = loader.load(code="return { x: 1 };")

        assert compiled.source == "return { x: 1 };"
        assert compiled.original_path is None
        assert compiled.is_typescript is False

    def test_load_file(self):
        """Test loading from file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "test.js"
            script_path.write_text("return { loaded: true };")

            loader = ScriptLoader(config_dir=tmpdir)
            compiled = loader.load(script_path="test.js")

            assert "loaded: true" in compiled.source
            assert compiled.original_path is not None
            assert compiled.is_typescript is False

    @pytest.mark.skipif(not HAS_ESBUILD, reason="esbuild not installed")
    def test_load_detects_typescript(self):
        """Test that .ts extension triggers TypeScript detection."""
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "process.ts"
            script_path.write_text("const x: number = 1; return { x };")

            loader = ScriptLoader(config_dir=tmpdir)
            compiled = loader.load(script_path="process.ts")

            assert compiled.is_typescript is True

    def test_cache_hit(self):
        """Test that scripts are cached."""
        loader = ScriptLoader()

        # First load
        compiled1 = loader.load(code="return { cached: true };")

        # Second load - should hit cache
        compiled2 = loader.load(code="return { cached: true };")

        # Same source
        assert compiled1.source == compiled2.source

        # Cache stats
        stats = loader.get_cache_stats()
        assert stats["size"] == 1

    def test_cache_invalidation_on_file_change(self):
        """Test that cache is invalidated when file changes."""
        import time

        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "test.js"
            script_path.write_text("return { version: 1 };")

            loader = ScriptLoader(config_dir=tmpdir, cache_ttl_seconds=60)

            # First load
            compiled1 = loader.load(script_path="test.js")
            assert "version: 1" in compiled1.source

            # Modify file (need small delay for mtime to change)
            time.sleep(0.1)
            script_path.write_text("return { version: 2 };")

            # Second load - should reload due to mtime change
            compiled2 = loader.load(script_path="test.js")
            assert "version: 2" in compiled2.source

    def test_requires_source(self):
        """Test that either script_path or code is required."""
        loader = ScriptLoader()

        with pytest.raises(ValueError, match="Either 'script_path' or 'code' must be provided"):
            loader.load()


class TestRuntimeBridge:
    """Tests for RuntimeBridge (no py_mini_racer required)."""

    def test_prepare_context_code(self):
        """Test context code generation."""
        bridge = RuntimeBridge()
        code = bridge.prepare_context_code(
            state={"user_id": "123", "amount": 100},
            context={"workflow_id": "wf-abc"}
        )

        # Should contain state injection
        assert "const state = Object.freeze" in code
        assert '"user_id"' in code
        assert '"amount"' in code

        # Should contain context injection
        assert "const context = Object.freeze" in code
        assert '"workflow_id"' in code

    def test_wrap_user_code(self):
        """Test user code wrapping."""
        bridge = RuntimeBridge()
        wrapped = bridge.wrap_user_code("return { x: 1 };")

        # Should be wrapped in IIFE or similar
        assert "return { x: 1 };" in wrapped

    def test_extract_result_dict(self):
        """Test result extraction for dict."""
        bridge = RuntimeBridge()
        result = bridge.extract_result({"key": "value"})
        assert result == {"key": "value"}

    def test_extract_result_primitive(self):
        """Test result extraction for primitives."""
        bridge = RuntimeBridge()

        assert bridge.extract_result(42) == {"result": 42}
        assert bridge.extract_result("hello") == {"result": "hello"}
        assert bridge.extract_result(True) == {"result": True}

    def test_extract_result_list(self):
        """Test result extraction for lists."""
        bridge = RuntimeBridge()
        result = bridge.extract_result([1, 2, 3])
        assert result == {"result": [1, 2, 3]}

    def test_extract_result_none(self):
        """Test result extraction for None."""
        bridge = RuntimeBridge()
        result = bridge.extract_result(None)
        assert result is None


@pytest.mark.skipif(not HAS_MINI_RACER, reason="py_mini_racer not installed")
class TestV8Context:
    """Tests for V8Context."""

    def test_basic_eval(self):
        """Test basic JavaScript evaluation."""
        ctx = V8Context()
        result = ctx.eval("1 + 2")
        assert result == 3

    def test_eval_with_timeout(self):
        """Test timeout enforcement."""
        ctx = V8Context()

        with pytest.raises(TimeoutError):
            ctx.eval("while(true) {}", timeout_ms=100)

    def test_execution_count(self):
        """Test execution counting."""
        ctx = V8Context()
        assert ctx.execution_count == 0

        ctx.eval("1")
        assert ctx.execution_count == 1

        ctx.eval("2")
        assert ctx.execution_count == 2


@pytest.mark.skipif(not HAS_MINI_RACER, reason="py_mini_racer not installed")
class TestV8ContextPool:
    """Tests for V8ContextPool."""

    def test_get_context(self):
        """Test getting context from pool."""
        pool = V8ContextPool()

        with pool.get_context() as ctx:
            result = ctx.eval("5 * 5")
            assert result == 25

    def test_pool_stats(self):
        """Test pool statistics."""
        pool = V8ContextPool()

        initial_stats = pool.get_stats()
        assert initial_stats["contexts_created"] == 0

        with pool.get_context() as ctx:
            ctx.eval("1")

        stats = pool.get_stats()
        assert stats["contexts_created"] == 1
        assert stats["contexts_destroyed"] == 1


class TestWorkflowBuilderIntegration:
    """Tests for WorkflowBuilder JAVASCRIPT step type support."""

    def test_build_javascript_step_from_config(self):
        """Test that WorkflowBuilder can create JavaScript steps from config."""
        from rufus.builder import WorkflowBuilder

        config = [{
            "name": "Transform_Data",
            "type": "JAVASCRIPT",
            "js_config": {
                "code": "return { transformed: state.value * 2 };",
                "timeout_ms": 3000,
                "memory_limit_mb": 64
            },
            "automate_next": True
        }]

        steps = WorkflowBuilder._build_steps_from_config(config)

        assert len(steps) == 1
        step = steps[0]

        assert isinstance(step, JavaScriptWorkflowStep)
        assert step.name == "Transform_Data"
        assert step.js_config.code == "return { transformed: state.value * 2 };"
        assert step.js_config.timeout_ms == 3000
        assert step.js_config.memory_limit_mb == 64
        assert step.automate_next is True

    def test_build_javascript_step_with_file(self):
        """Test JavaScript step with script_path."""
        from rufus.builder import WorkflowBuilder

        config = [{
            "name": "Process_File",
            "type": "JAVASCRIPT",
            "js_config": {
                "script_path": "scripts/process.js",
                "timeout_ms": 10000
            }
        }]

        steps = WorkflowBuilder._build_steps_from_config(config)

        assert len(steps) == 1
        step = steps[0]

        assert isinstance(step, JavaScriptWorkflowStep)
        assert step.js_config.script_path == "scripts/process.js"
        assert step.js_config.timeout_ms == 10000

    def test_build_javascript_step_with_typescript(self):
        """Test JavaScript step with TypeScript options."""
        from rufus.builder import WorkflowBuilder

        config = [{
            "name": "TypeScript_Step",
            "type": "JAVASCRIPT",
            "js_config": {
                "script_path": "scripts/process.ts",
                "typescript": True,
                "tsconfig_path": "./tsconfig.json"
            }
        }]

        steps = WorkflowBuilder._build_steps_from_config(config)

        step = steps[0]
        assert step.js_config.typescript is True
        assert step.js_config.tsconfig_path == "./tsconfig.json"

    def test_build_javascript_step_with_merge_options(self):
        """Test JavaScript step with merge options."""
        from rufus.builder import WorkflowBuilder

        config = [{
            "name": "Merge_Test",
            "type": "JAVASCRIPT",
            "js_config": {
                "code": "return { data: 123 };"
            },
            "merge_strategy": "deep",
            "merge_conflict_behavior": "prefer_existing"
        }]

        steps = WorkflowBuilder._build_steps_from_config(config)

        step = steps[0]
        assert step.merge_strategy == MergeStrategy.DEEP
        assert step.merge_conflict_behavior == MergeConflictBehavior.PREFER_EXISTING


class TestSandboxSecurity:
    """Tests for JavaScript sandbox security."""

    def test_blocked_globals_list(self):
        """Test that dangerous globals are blocked."""
        from rufus.javascript.sandbox import BLOCKED_GLOBALS

        # Check that dangerous functions are blocked
        assert "eval" in BLOCKED_GLOBALS
        assert "Function" in BLOCKED_GLOBALS
        assert "require" in BLOCKED_GLOBALS
        assert "process" in BLOCKED_GLOBALS
        assert "setTimeout" in BLOCKED_GLOBALS
        assert "setInterval" in BLOCKED_GLOBALS

    @pytest.mark.skipif(not HAS_MINI_RACER, reason="py_mini_racer not installed")
    def test_cannot_access_eval(self):
        """Test that eval is blocked in sandbox."""
        executor = JavaScriptExecutor()
        result = executor.execute(
            code="""
            try {
                eval('1 + 1');
                return { eval_works: true };
            } catch (e) {
                return { eval_works: false, error: e.name };
            }
            """,
            state={},
            context={}
        )

        assert result.success is True
        # eval should be blocked
        assert result.result.get("eval_works") is False

    @pytest.mark.skipif(not HAS_MINI_RACER, reason="py_mini_racer not installed")
    def test_cannot_access_function_constructor(self):
        """Test that Function constructor is blocked."""
        executor = JavaScriptExecutor()
        result = executor.execute(
            code="""
            try {
                const fn = new Function('return 42');
                return { function_works: true, result: fn() };
            } catch (e) {
                return { function_works: false, error: e.name };
            }
            """,
            state={},
            context={}
        )

        assert result.success is True
        # Function constructor should be blocked
        assert result.result.get("function_works") is False


class TestTypeScriptTranspilation:
    """Tests for TypeScript transpilation."""

    def test_transpiler_import(self):
        """Test that transpiler can be imported."""
        from rufus.javascript.typescript import TypeScriptTranspiler
        assert TypeScriptTranspiler is not None

    def test_fallback_transpiler(self):
        """Test fallback transpiler strips type annotations."""
        from rufus.javascript.typescript import FallbackTranspiler

        transpiler = FallbackTranspiler()

        # Simple type annotation
        ts_code = "const x: number = 42;"
        js_code = transpiler.transpile(ts_code)
        assert ": number" not in js_code
        assert "const x" in js_code

    def test_fallback_handles_interfaces(self):
        """Test fallback transpiler removes interface declarations."""
        from rufus.javascript.typescript import FallbackTranspiler

        transpiler = FallbackTranspiler()

        ts_code = """
interface User {
    name: string;
    age: number;
}
const user: User = { name: "Test", age: 30 };
"""
        js_code = transpiler.transpile(ts_code)

        # Interface should be removed
        assert "interface User" not in js_code
        # Variable should remain (without type)
        assert "const user" in js_code

"""JavaScript executor for workflow steps."""

import logging
import time
from typing import Dict, Any, Optional

from .types import JSExecutionResult
from .bridge import RuntimeBridge
from .loader import ScriptLoader
from .context_pool import V8ContextPool, get_default_pool, is_mini_racer_available
from .sandbox import validate_script

logger = logging.getLogger(__name__)


class JavaScriptExecutor:
    """
    Executes JavaScript/TypeScript code in a sandboxed V8 environment.

    This is the main entry point for JavaScript step execution.

    Usage:
        executor = JavaScriptExecutor()

        # Execute inline code
        result = executor.execute(
            code="return { doubled: state.value * 2 };",
            state={"value": 21},
            context={"workflow_id": "abc123", "step_name": "double"}
        )

        # Execute file
        result = executor.execute_file(
            script_path="scripts/process.js",
            state=workflow_state,
            context=step_context
        )
    """

    def __init__(
        self,
        config_dir: Optional[str] = None,
        pool: Optional[V8ContextPool] = None,
    ):
        """
        Initialize JavaScript executor.

        Args:
            config_dir: Base directory for resolving script paths
            pool: V8 context pool (uses default if not provided)
        """
        self._config_dir = config_dir
        self._pool = pool or get_default_pool()
        self._loader = ScriptLoader(config_dir=config_dir)
        self._bridge = RuntimeBridge()

    def execute(
        self,
        code: str,
        state: Dict[str, Any],
        context: Dict[str, Any],
        timeout_ms: int = 5000,
        memory_limit_mb: int = 128,
        strict_mode: bool = True,
    ) -> JSExecutionResult:
        """
        Execute inline JavaScript code.

        Args:
            code: JavaScript code to execute
            state: Workflow state (available as 'state' in script)
            context: Step context (available as 'context' in script)
            timeout_ms: Maximum execution time in milliseconds
            memory_limit_mb: Maximum V8 heap size in megabytes
            strict_mode: Execute in JavaScript strict mode

        Returns:
            JSExecutionResult with execution outcome
        """
        if not is_mini_racer_available():
            return JSExecutionResult(
                success=False,
                error="py_mini_racer is not installed. Install with: pip install py-mini-racer",
                error_type="runtime",
            )

        start_time = time.time()

        try:
            # Validate script
            validate_script(code)

            # Load/compile script (for inline code, this just returns it)
            compiled = self._loader.load(code=code)

            # Generate full script with context
            full_script = self._bridge.get_full_script(
                user_code=compiled.source,
                state=state,
                context=context,
                strict_mode=strict_mode,
            )

            # Execute in V8 context
            with self._pool.get_context(memory_limit_mb=memory_limit_mb) as ctx:
                raw_result = ctx.eval(full_script, timeout_ms=timeout_ms)

                # Extract logs
                logs = self._bridge.extract_logs(ctx)

                # Extract result
                result = self._bridge.extract_result(raw_result)

                execution_time_ms = (time.time() - start_time) * 1000
                memory_used_mb = ctx.get_memory_usage_mb()

                return JSExecutionResult(
                    success=True,
                    result=result,
                    execution_time_ms=execution_time_ms,
                    memory_used_mb=memory_used_mb,
                    logs=logs,
                )

        except TimeoutError as e:
            execution_time_ms = (time.time() - start_time) * 1000
            return JSExecutionResult(
                success=False,
                error=str(e),
                error_type="timeout",
                execution_time_ms=execution_time_ms,
            )

        except FileNotFoundError as e:
            return JSExecutionResult(
                success=False,
                error=str(e),
                error_type="file_not_found",
            )

        except ValueError as e:
            return JSExecutionResult(
                success=False,
                error=str(e),
                error_type="validation",
            )

        except Exception as e:
            execution_time_ms = (time.time() - start_time) * 1000
            error_str = str(e)

            # Determine error type
            error_type = "runtime"
            if "SyntaxError" in error_str or "Unexpected" in error_str:
                error_type = "syntax"
            elif "ReferenceError" in error_str:
                error_type = "runtime"
            elif "TypeError" in error_str:
                error_type = "runtime"

            # Try to extract line/column info
            error_line = None
            error_column = None
            # PyMiniRacer errors often include line info like "at line 42"

            return JSExecutionResult(
                success=False,
                error=error_str,
                error_type=error_type,
                error_line=error_line,
                error_column=error_column,
                stack_trace=error_str,
                execution_time_ms=execution_time_ms,
            )

    def execute_file(
        self,
        script_path: str,
        state: Dict[str, Any],
        context: Dict[str, Any],
        timeout_ms: int = 5000,
        memory_limit_mb: int = 128,
        strict_mode: bool = True,
        force_typescript: bool = False,
        tsconfig_path: Optional[str] = None,
    ) -> JSExecutionResult:
        """
        Execute JavaScript/TypeScript file.

        Args:
            script_path: Path to .js or .ts file
            state: Workflow state
            context: Step context
            timeout_ms: Maximum execution time
            memory_limit_mb: Maximum V8 heap size
            strict_mode: Execute in strict mode
            force_typescript: Force TypeScript transpilation
            tsconfig_path: Path to tsconfig.json

        Returns:
            JSExecutionResult with execution outcome
        """
        if not is_mini_racer_available():
            return JSExecutionResult(
                success=False,
                error="py_mini_racer is not installed. Install with: pip install py-mini-racer",
                error_type="runtime",
            )

        start_time = time.time()

        try:
            # Load and compile script
            compiled = self._loader.load(
                script_path=script_path,
                force_typescript=force_typescript,
                tsconfig_path=tsconfig_path,
            )

            # Validate compiled script
            validate_script(compiled.source)

            # Generate full script with context
            full_script = self._bridge.get_full_script(
                user_code=compiled.source,
                state=state,
                context=context,
                strict_mode=strict_mode,
            )

            # Execute in V8 context
            with self._pool.get_context(memory_limit_mb=memory_limit_mb) as ctx:
                raw_result = ctx.eval(full_script, timeout_ms=timeout_ms)

                # Extract logs
                logs = self._bridge.extract_logs(ctx)

                # Extract result
                result = self._bridge.extract_result(raw_result)

                execution_time_ms = (time.time() - start_time) * 1000
                memory_used_mb = ctx.get_memory_usage_mb()

                return JSExecutionResult(
                    success=True,
                    result=result,
                    execution_time_ms=execution_time_ms,
                    memory_used_mb=memory_used_mb,
                    logs=logs,
                )

        except TimeoutError as e:
            execution_time_ms = (time.time() - start_time) * 1000
            return JSExecutionResult(
                success=False,
                error=str(e),
                error_type="timeout",
                execution_time_ms=execution_time_ms,
            )

        except FileNotFoundError as e:
            return JSExecutionResult(
                success=False,
                error=str(e),
                error_type="file_not_found",
            )

        except RuntimeError as e:
            # Transpilation errors
            if "transpil" in str(e).lower():
                return JSExecutionResult(
                    success=False,
                    error=str(e),
                    error_type="transpile",
                )
            raise

        except ValueError as e:
            return JSExecutionResult(
                success=False,
                error=str(e),
                error_type="validation",
            )

        except Exception as e:
            execution_time_ms = (time.time() - start_time) * 1000
            error_str = str(e)

            error_type = "runtime"
            if "SyntaxError" in error_str:
                error_type = "syntax"

            return JSExecutionResult(
                success=False,
                error=error_str,
                error_type=error_type,
                stack_trace=error_str,
                execution_time_ms=execution_time_ms,
            )

    def execute_config(
        self,
        js_config: "JavaScriptConfig",
        state: Dict[str, Any],
        context: Dict[str, Any],
    ) -> JSExecutionResult:
        """
        Execute JavaScript step from configuration.

        This is the main entry point used by the workflow engine.

        Args:
            js_config: JavaScriptConfig from workflow step
            state: Workflow state
            context: Step context

        Returns:
            JSExecutionResult with execution outcome
        """
        if js_config.script_path:
            return self.execute_file(
                script_path=js_config.script_path,
                state=state,
                context=context,
                timeout_ms=js_config.timeout_ms,
                memory_limit_mb=js_config.memory_limit_mb,
                strict_mode=js_config.strict_mode,
                force_typescript=js_config.typescript,
                tsconfig_path=js_config.tsconfig_path,
            )
        elif js_config.code:
            return self.execute(
                code=js_config.code,
                state=state,
                context=context,
                timeout_ms=js_config.timeout_ms,
                memory_limit_mb=js_config.memory_limit_mb,
                strict_mode=js_config.strict_mode,
            )
        else:
            return JSExecutionResult(
                success=False,
                error="Either 'script_path' or 'code' must be provided in js_config",
                error_type="validation",
            )

    def clear_cache(self) -> None:
        """Clear the script cache."""
        self._loader.clear_cache()

    def get_stats(self) -> dict:
        """Get executor statistics."""
        return {
            "loader_cache": self._loader.get_cache_stats(),
            "context_pool": self._pool.get_stats(),
            "mini_racer_available": is_mini_racer_available(),
        }

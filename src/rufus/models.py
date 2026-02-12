from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional, Callable, Type
from enum import Enum

# --- Step Models ---


class MergeStrategy(str, Enum):
    """Defines how results from asynchronous or parallel steps should be merged into the workflow state."""
    SHALLOW = "shallow"    # Only top-level keys are merged; existing keys are overwritten.
    DEEP = "deep"          # Recursive merge for nested dictionaries.
    REPLACE = "replace"    # The entire state object is replaced by the result.
    # If target is a list, result items are appended. Non-list types use SHALLOW.
    APPEND = "append"
    # Existing keys are overwritten, new keys are added.
    OVERWRITE_EXISTING = "overwrite_existing"
    # Only new keys are added; existing keys are kept.
    PRESERVE_EXISTING = "preserve_existing"


class MergeConflictBehavior(str, Enum):
    """Defines how to handle conflicts during state merging."""
    RAISE_ERROR = "raise_error"   # Raise an error if a conflict occurs.
    PREFER_NEW = "prefer_new"     # New value overwrites existing value.
    # Existing value is preserved over new value.
    PREFER_EXISTING = "prefer_existing"


class StepContext(BaseModel):
    workflow_id: str
    step_name: str
    validated_input: Optional[Any] = None
    previous_step_result: Optional[Dict[str, Any]] = None


class WorkflowStep(BaseModel):
    name: str
    func: Optional[Callable] = None
    input_schema: Optional[Type[BaseModel]] = None
    required_input: List[str] = Field(default_factory=list)
    automate_next: bool = False
    routes: Optional[List[Dict[str, str]]] = None  # For decision steps

    # Placeholder for dynamic injection config
    dynamic_injection: Optional[Dict[str, Any]] = None


class CompensatableStep(WorkflowStep):
    compensate_func: Callable


class AsyncWorkflowStep(WorkflowStep):
    func_path: str  # Path to the function for async execution
    merge_strategy: MergeStrategy = MergeStrategy.SHALLOW
    merge_conflict_behavior: MergeConflictBehavior = MergeConflictBehavior.PREFER_NEW


class HttpWorkflowStep(WorkflowStep):
    http_config: Dict[str, Any]  # Configuration for HTTP request
    merge_strategy: MergeStrategy = MergeStrategy.SHALLOW
    merge_conflict_behavior: MergeConflictBehavior = MergeConflictBehavior.PREFER_NEW


class JavaScriptConfig(BaseModel):
    """Configuration for JavaScript/TypeScript step execution."""

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

    model_config = {"extra": "forbid"}

    def model_post_init(self, __context: Any) -> None:
        """Validate that either script_path or code is provided, but not both."""
        if not self.script_path and not self.code:
            raise ValueError("Either 'script_path' or 'code' must be provided")
        if self.script_path and self.code:
            raise ValueError("Cannot specify both 'script_path' and 'code'")


class JavaScriptWorkflowStep(WorkflowStep):
    """Workflow step that executes JavaScript/TypeScript code in a sandboxed V8 environment."""

    js_config: JavaScriptConfig
    merge_strategy: MergeStrategy = MergeStrategy.SHALLOW
    merge_conflict_behavior: MergeConflictBehavior = MergeConflictBehavior.PREFER_NEW


class AIInferenceConfig(BaseModel):
    """Configuration for AI/ML inference step execution."""

    # Allow model_ prefix for ML model fields
    model_config["protected_namespaces"] = ()

    # Model identification
    model_name: str = Field(
        ...,
        description="Unique name for the model (matches loaded model name)"
    )
    model_path: Optional[str] = Field(
        None,
        description="Path to model file (if not pre-loaded)"
    )
    model_version: str = Field(
        "1.0.0",
        description="Model version for tracking"
    )

    # Runtime selection
    runtime: str = Field(
        "tflite",
        description="Inference runtime: 'tflite', 'onnx', or 'custom'"
    )

    # Input configuration
    input_source: str = Field(
        ...,
        description="State path to input data (e.g., 'state.sensor_data')"
    )
    preprocessing: Optional[str] = Field(
        None,
        description="Preprocessing to apply: 'normalize', 'resize', 'none'"
    )
    preprocessing_params: Dict[str, Any] = Field(
        default_factory=dict,
        description="Parameters for preprocessing (e.g., {'mean': 0.5, 'std': 0.5})"
    )

    # Output configuration
    output_key: str = Field(
        "inference_result",
        description="Key to store inference result in state"
    )
    postprocessing: Optional[str] = Field(
        None,
        description="Postprocessing to apply: 'softmax', 'threshold', 'argmax', 'none'"
    )
    postprocessing_params: Dict[str, Any] = Field(
        default_factory=dict,
        description="Parameters for postprocessing (e.g., {'threshold': 0.5})"
    )

    # Thresholding for decision routing
    threshold: Optional[float] = Field(
        None,
        description="Threshold for binary classification decisions"
    )
    threshold_key: str = Field(
        "prediction",
        description="Key in result to apply threshold to"
    )

    # Error handling
    fallback_on_error: str = Field(
        "skip",
        description="Behavior on error: 'skip', 'fail', 'default'"
    )
    default_result: Optional[Dict[str, Any]] = Field(
        None,
        description="Default result to use when fallback_on_error='default'"
    )

    # Performance options
    timeout_ms: int = Field(
        5000,
        ge=100,
        le=60000,
        description="Maximum inference time in milliseconds"
    )

    model_config = {"extra": "forbid"}


class AIInferenceWorkflowStep(WorkflowStep):
    """
    Workflow step that runs AI/ML model inference.

    Supports TensorFlow Lite, ONNX Runtime, and custom inference providers.
    Automatically handles model loading, preprocessing, inference, and postprocessing.

    Example YAML:
        - name: "Detect_Anomaly"
          type: "AI_INFERENCE"
          ai_config:
            model_name: "anomaly_detector"
            model_path: "models/anomaly_detector.tflite"
            runtime: "tflite"
            input_source: "state.sensor_readings"
            preprocessing: "normalize"
            output_key: "anomaly_result"
            postprocessing: "threshold"
            postprocessing_params:
              threshold: 0.7
            threshold: 0.7
          automate_next: true
    """

    ai_config: AIInferenceConfig
    merge_strategy: MergeStrategy = MergeStrategy.SHALLOW
    merge_conflict_behavior: MergeConflictBehavior = MergeConflictBehavior.PREFER_NEW


class ParallelExecutionTask(BaseModel):
    name: str
    func_path: str  # Path to the function for parallel execution


class ParallelWorkflowStep(WorkflowStep):
    tasks: List[ParallelExecutionTask]
    merge_function_path: Optional[str] = None
    merge_strategy: MergeStrategy = MergeStrategy.SHALLOW
    merge_conflict_behavior: MergeConflictBehavior = MergeConflictBehavior.PREFER_NEW


class FireAndForgetWorkflowStep(WorkflowStep):
    target_workflow_type: str
    initial_data_template: Dict[str, Any]


class LoopStep(WorkflowStep):
    loop_body: List[WorkflowStep]
    mode: str  # ITERATE or WHILE
    iterate_over: Optional[str] = None  # State path to list for iteration
    item_var_name: str = "item"
    while_condition: Optional[str] = None  # Expression for while loop
    max_iterations: int = 1000


class CronScheduleWorkflowStep(WorkflowStep):
    target_workflow_type: str
    cron_expression: str
    initial_data_template: Dict[str, Any]
    schedule_name: Optional[str] = None

# --- Directives and Exceptions ---


class WorkflowJumpDirective(Exception):
    def __init__(self, target_step_name: str):
        self.target_step_name = target_step_name


class WorkflowPauseDirective(Exception):
    def __init__(self, result: Dict[str, Any]):
        self.result = result


class StartSubWorkflowDirective(Exception):
    def __init__(self, workflow_type: str, initial_data: Dict[str, Any], data_region: Optional[str] = None):
        self.workflow_type = workflow_type
        self.initial_data = initial_data
        self.data_region = data_region


class WorkflowNextStepDirective(Exception):
    """Internal directive to indicate that the workflow should proceed to the next step."""
    pass


class SagaWorkflowException(Exception):
    def __init__(self, step_name: str, original_exception: Exception):
        self.step_name = step_name
        self.original_exception = original_exception
        super().__init__(
            f"Saga step '{step_name}' failed: {original_exception}")


class WorkflowFailedException(Exception):
    def __init__(self, workflow_id: str, step_name: str, original_exception: Exception):
        self.workflow_id = workflow_id
        self.step_name = step_name
        self.original_exception = original_exception
        super().__init__(
            f"Workflow {workflow_id} failed at step '{step_name}': {original_exception}")

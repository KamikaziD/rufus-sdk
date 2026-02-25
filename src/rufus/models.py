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
    """Context object passed to each step function, containing metadata and utilities."""
    workflow_id: str
    step_name: str
    validated_input: Optional[Any] = None
    previous_step_result: Optional[Dict[str, Any]] = None
    loop_item: Optional[Any] = None    # Current item in an ITERATE loop
    loop_index: Optional[int] = None   # Current index in an ITERATE loop


class WorkflowStep(BaseModel):
    """Base model for a workflow step. Specific step types will extend this with additional fields."""
    name: str
    func: Optional[Callable] = None
    input_schema: Optional[Type[BaseModel]] = None
    required_input: List[str] = Field(default_factory=list)
    automate_next: bool = False
    routes: Optional[List[Dict[str, str]]] = None  # For decision steps

    # Placeholder for dynamic injection config
    dynamic_injection: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize step to dictionary for WebSocket/API responses."""
        step_dict = {
            "name": self.name,
            "type": type(self).__name__,
            "required_input": self.required_input,
            "automate_next": self.automate_next,
        }

        if self.routes:
            step_dict["routes"] = self.routes

        if self.dynamic_injection:
            step_dict["dynamic_injection"] = self.dynamic_injection

        return step_dict


class CompensatableStep(WorkflowStep):
    """Workflow step that includes a compensation function for saga patterns."""
    compensate_func: Callable


class AsyncWorkflowStep(WorkflowStep):
    """Workflow step that executes asynchronously, allowing the workflow to pause and wait for an external event or callback."""
    func_path: str  # Path to the function for async execution
    merge_strategy: MergeStrategy = MergeStrategy.SHALLOW
    merge_conflict_behavior: MergeConflictBehavior = MergeConflictBehavior.PREFER_NEW


class HttpWorkflowStep(WorkflowStep):
    """Workflow step that makes an HTTP request to an external API."""
    http_config: Dict[str, Any]  # Configuration for HTTP request
    merge_strategy: MergeStrategy = MergeStrategy.SHALLOW
    merge_conflict_behavior: MergeConflictBehavior = MergeConflictBehavior.PREFER_NEW


class AIInferenceConfig(BaseModel):
    """Configuration for AI/ML inference step execution."""

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

    model_config = {"extra": "forbid", 'protected_namespaces': ()}
    # Allow model_ prefix for ML model fields


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
    kwargs: Dict[str, Any] = Field(default_factory=dict)  # Per-task kwargs (used for dynamic fan-out)


class ParallelWorkflowStep(WorkflowStep):
    tasks: List[ParallelExecutionTask] = Field(default_factory=list)
    # Dynamic fan-out: iterate over a state list and call task_function once per item
    iterate_over: Optional[str] = None       # Dot-notation state path to a list
    task_function: Optional[str] = None      # Function called for each item
    item_var_name: str = "item"              # Kwarg name passed to the function per item
    batch_size: int = Field(
        default=0,
        ge=0,
        description="Process iterate_over list in chunks of this size (0 = all at once). "
                    "Only supported with SyncExecutor/ThreadPoolExecutor."
    )
    allow_partial_success: bool = Field(
        default=False,
        description="If True, the parallel step succeeds even if some tasks fail. "
                    "Failed task errors are logged but do not raise an exception."
    )
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

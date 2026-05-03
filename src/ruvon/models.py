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

    async def compensate(self, state: Any, context: Any = None, **kwargs) -> dict:
        """Invoke the compensation function, handling both sync and async callables."""
        import asyncio
        if asyncio.iscoroutinefunction(self.compensate_func):
            result = await self.compensate_func(state, context, **kwargs)
        else:
            result = self.compensate_func(state, context, **kwargs)
        return result if isinstance(result, dict) else {}


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

    # Paged inference (shard-level paging for memory-constrained edge/browser)
    paging_strategy: str = Field(
        "none",
        description="Paging strategy: 'none' (disabled), 'shard' (file-level), 'layer' (future)"
    )
    max_resident_shards: int = Field(
        2,
        ge=1,
        description="Maximum number of GGUF shards resident in WASM/memory simultaneously"
    )
    prefetch_shards: int = Field(
        1,
        ge=0,
        description="Number of shards to prefetch ahead of the active window"
    )
    shard_urls: Optional[List[str]] = Field(
        None,
        description="Explicit shard URLs for browser paging (required when paging_strategy='shard')"
    )
    shard_size_mb: int = Field(
        120,
        ge=10,
        description="Target shard split size in MB (used when splitting model locally)"
    )
    logic_gate_threshold: float = Field(
        0.0,
        ge=0.0,
        le=1.0,
        description="Complexity threshold below which only shard-0 is loaded (fast path). 0.0 = disabled."
    )
    max_tokens: Optional[int] = Field(
        None,
        ge=1,
        description="Maximum tokens to generate for generative steps"
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


class WasmConfig(BaseModel):
    """Configuration for a WASM step execution via WASI stdin/stdout interface."""

    wasm_hash: str = Field(
        ...,
        description="SHA-256 hex digest of the .wasm binary (used to resolve the binary)"
    )
    entrypoint: str = Field(
        "execute",
        description="Exported WASM function name to invoke"
    )
    state_mapping: Dict[str, str] = Field(
        default_factory=dict,
        description="Map of workflow state key → WASM input key. If empty, full state is passed."
    )
    timeout_ms: int = Field(
        5000,
        ge=100,
        le=60000,
        description="Maximum execution time in milliseconds"
    )
    fallback_on_error: str = Field(
        "fail",
        description="Behavior on error: 'fail' raises, 'skip' returns {}, 'default' returns default_result"
    )
    default_result: Optional[Dict[str, Any]] = Field(
        None,
        description="Result to return when fallback_on_error='default'"
    )

    model_config = {"extra": "forbid"}


class WasmWorkflowStep(WorkflowStep):
    """
    Workflow step that executes a pre-compiled WebAssembly binary via the WASI interface.

    The WASM module receives workflow state as JSON on stdin and must write its result
    as JSON to stdout. State is selectively mapped via state_mapping, or the full state
    dict is passed if state_mapping is empty.

    Example YAML:
        - name: "Calculate_Risk"
          type: "WASM"
          wasm_config:
            wasm_hash: "a3f5c2d1..."
            entrypoint: "execute"
            state_mapping:
              transaction_amount: "amount"
              card_country: "country"
            timeout_ms: 3000
            fallback_on_error: "fail"
          automate_next: true
    """
    wasm_config: WasmConfig
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


class HumanWorkflowStep(WorkflowStep):
    """Self-contained HITL step.

    Lifecycle:
    - First call (no user_input): framework auto-pauses, sets status to WAITING_HUMAN,
      exposes this step's input_schema to the API.
    - Resume (user_input provided): validates against input_schema (if set), calls func
      with **user_input, merges result into state, then advances.

    func is optional — if omitted, user_input is merged directly into state on resume.
    """
    pass  # Inherits func, input_schema, required_input, automate_next, routes from WorkflowStep


# --- AI Workflow Builder Step Types ---


class AILLMInferenceConfig(BaseModel):
    """Configuration for LLM inference (cloud or local) within a workflow step."""
    model: str = Field(..., description="Model name, e.g. 'claude-sonnet-4-6', 'llama3', 'bitnet-3b'")
    model_location: str = Field("cloud", description="'cloud' | 'ollama' | 'edge' | 'auto'")
    ollama_base_url: str = Field("http://localhost:11434", description="Ollama server URL")
    system_prompt: str = Field(..., description="System prompt for the LLM")
    user_prompt: str = Field(..., description="User prompt; supports $.steps.X.output selectors")
    output_schema: Optional[Dict[str, Any]] = Field(None, description="JSON Schema for structured output validation")
    temperature: float = Field(0.3, ge=0.0, le=2.0)
    max_tokens: int = Field(1000, ge=1)
    fallback_model: Optional[str] = Field(None, description="Model to try if primary is unavailable")
    pii_detected: bool = Field(False, description="Set true to enforce downstream AUDIT_EMIT (GOV-001)")
    data_sovereignty: str = Field("cloud", description="'local' | 'cloud' | 'any'")
    model_config = {"extra": "forbid", "protected_namespaces": ()}


class AILLMInferenceWorkflowStep(WorkflowStep):
    """Workflow step that calls an LLM (Anthropic cloud, Ollama local, or BitNet edge).

    Distinct from AI_INFERENCE (TFLite/ONNX) — this step is for text generation models.

    Example YAML:
        - name: "Score_Bid"
          type: "AI_LLM_INFERENCE"
          llm_config:
            model: claude-sonnet-4-6
            model_location: cloud
            system_prompt: "You are a procurement evaluator."
            user_prompt: "Score this bid: {{$.steps.parse_bid.output}}"
            temperature: 0.2
          automate_next: true
    """
    llm_config: AILLMInferenceConfig
    merge_strategy: MergeStrategy = MergeStrategy.SHALLOW
    merge_conflict_behavior: MergeConflictBehavior = MergeConflictBehavior.PREFER_NEW


class HumanApprovalConfig(BaseModel):
    """Configuration for a human approval gate with channels, timeout, and escalation."""
    title: str = Field(..., description="Display title shown to approvers")
    description: str = Field("", description="Context for the decision; supports selectors")
    approvers: List[str] = Field(default_factory=list, description="User IDs or role names")
    timeout_hours: int = Field(24, ge=1, description="Hours before timeout action fires")
    on_timeout: str = Field("auto_reject", description="'auto_reject' | 'auto_approve' | 'escalate'")
    escalate_to: Optional[str] = Field(None, description="User/role to escalate to on timeout")
    channels: List[str] = Field(default_factory=list, description="Notification channels: 'slack', 'email', 'dashboard'")
    data_to_show: List[str] = Field(default_factory=list, description="$.steps.X selectors for context data")
    model_config = {"extra": "forbid"}


class HumanApprovalWorkflowStep(WorkflowStep):
    """Workflow step that pauses for a human approval decision with rich configuration.

    Unlike HUMAN_IN_LOOP, supports multi-channel notifications, timeout escalation,
    and structured approval metadata. Outputs: decision, approver_id, approved_at, notes.

    Example YAML:
        - name: "Committee_Review"
          type: "HUMAN_APPROVAL"
          approval_config:
            title: "Bid Evaluation Review"
            approvers: [role:procurement-committee]
            timeout_hours: 48
            on_timeout: auto_reject
            channels: [slack, email, dashboard]
    """
    approval_config: HumanApprovalConfig


class AuditEmitConfig(BaseModel):
    """Configuration for an immutable WORM audit record emission."""
    event_type: str = Field(..., description="Audit event identifier, e.g. 'bid.evaluated'")
    severity: str = Field("INFO", description="'INFO' | 'WARN' | 'CRITICAL'")
    payload: Dict[str, Any] = Field(default_factory=dict, description="Audit payload; supports selectors")
    retention_days: int = Field(2555, ge=1, description="Retention period (default: 7 years)")
    tags: List[str] = Field(default_factory=list)
    pii_fields: List[str] = Field(default_factory=list, description="Fields to SHA-256 hash before storage")
    model_config = {"extra": "forbid"}


class AuditEmitWorkflowStep(WorkflowStep):
    """Workflow step that emits an immutable audit record to the Ruvon audit trail.

    Records are append-only (WORM). Required downstream of any AI_LLM_INFERENCE step
    with pii_detected=true (enforced by GOV-001 governance rule).

    Example YAML:
        - name: "Audit_Bid_Decision"
          type: "AUDIT_EMIT"
          audit_config:
            event_type: bid.evaluated
            severity: INFO
            retention_days: 2555
            tags: [bid-evaluation, uae-procurement]
    """
    audit_config: AuditEmitConfig


class ComplianceCheckConfig(BaseModel):
    """Configuration for a declarative compliance ruleset evaluation."""
    ruleset: str = Field(..., description="Path to a compliance ruleset YAML file")
    input_data: Dict[str, Any] = Field(default_factory=dict, description="Selectors for data to evaluate")
    jurisdiction: List[str] = Field(default_factory=list, description="e.g. ['UAE', 'GDPR', 'HIPAA']")
    model: str = Field("claude-sonnet-4-6", description="LLM model for ambiguous rule application")
    confidence_threshold: float = Field(0.85, ge=0.0, le=1.0)
    model_config = {"extra": "forbid", "protected_namespaces": ()}


class ComplianceCheckWorkflowStep(WorkflowStep):
    """Workflow step that evaluates a declarative compliance ruleset against workflow data.

    Returns: passed (bool), score (float 0-1), violations (list).

    Example YAML:
        - name: "UAE_Compliance"
          type: "COMPLIANCE_CHECK"
          compliance_config:
            ruleset: ./rulesets/uae-procurement-v2.yaml
            jurisdiction: [UAE]
            confidence_threshold: 0.85
    """
    compliance_config: ComplianceCheckConfig
    merge_strategy: MergeStrategy = MergeStrategy.SHALLOW
    merge_conflict_behavior: MergeConflictBehavior = MergeConflictBehavior.PREFER_NEW


class EdgeModelCallConfig(BaseModel):
    """Configuration for a local-only edge model inference call (data sovereignty guaranteed)."""
    model_id: str = Field(..., description="Registered local model ID")
    prompt: str = Field(..., description="Prompt text; supports $.steps.X selectors")
    output_schema: Optional[Dict[str, Any]] = Field(None, description="Expected output JSON Schema")
    max_tokens: int = Field(512, ge=1, description="Conservative token limit for edge hardware")
    device_check: bool = Field(True, description="Verify model is loaded before calling")
    offline_only: bool = Field(False, description="If true, fail if network is detected")
    model_config = {"extra": "forbid", "protected_namespaces": ()}


class EdgeModelCallWorkflowStep(WorkflowStep):
    """Workflow step that calls a locally-running model with a data sovereignty guarantee.

    Data never leaves the device. Distinct from AI_LLM_INFERENCE to make the offline
    contract explicit in the workflow definition.

    Example YAML:
        - name: "Local_Classify"
          type: "EDGE_MODEL_CALL"
          edge_config:
            model_id: bitnet-neelo-classifier-v2
            prompt: "Classify this bid: {{$.steps.parse_bid.output}}"
            max_tokens: 256
    """
    edge_config: EdgeModelCallConfig
    merge_strategy: MergeStrategy = MergeStrategy.SHALLOW
    merge_conflict_behavior: MergeConflictBehavior = MergeConflictBehavior.PREFER_NEW


class WorkflowBuilderMetaConfig(BaseModel):
    """AI generation provenance metadata stored in the workflow definition."""
    generated_by: str = Field("ruvon-workflow-builder/0.1")
    original_prompt: str = Field("", description="The exact user prompt used to generate this workflow")
    pipeline_version: str = Field("0.1.0")
    model_versions: Dict[str, str] = Field(default_factory=dict, description="e.g. {intent_parse: 'claude-sonnet-4-6'}")
    lint_results: Dict[str, Any] = Field(default_factory=dict, description="Governance lint report summary")
    human_reviewed: bool = Field(False)
    reviewed_by: Optional[str] = Field(None)
    reviewed_at: Optional[str] = Field(None)
    model_config = {"extra": "forbid", "protected_namespaces": ()}


class WorkflowBuilderMetaStep(WorkflowStep):
    """No-op metadata step injected by the AI Workflow Builder into every generated workflow.

    Stores generation provenance: original prompt, model versions, lint results.
    Provides auditability — regulators can ask 'how was this workflow created?'
    and find the answer inside the workflow itself.

    Example YAML:
        - name: "_builder_meta"
          type: "WORKFLOW_BUILDER_META"
          meta_config:
            generated_by: ruvon-workflow-builder/0.1
            original_prompt: "handle incoming bid submissions"
            human_reviewed: false
    """
    meta_config: WorkflowBuilderMetaConfig


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

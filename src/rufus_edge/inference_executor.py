"""
AI Inference Executor for Rufus Edge

Handles execution of AI_INFERENCE workflow steps, including:
- Model loading and caching
- Input preprocessing
- Inference execution
- Output postprocessing
- Error handling and fallbacks
"""

import logging
import asyncio
from typing import Any, Dict, Optional, Union
import numpy as np

from rufus.providers.inference import (
    InferenceProvider,
    InferenceRuntime,
    InferenceResult,
    ModelMetadata,
    NormalizePreprocessor,
    ThresholdPostprocessor,
    ArgmaxPostprocessor,
    SoftmaxPostprocessor,
)
from rufus.models import AIInferenceConfig, StepContext

logger = logging.getLogger(__name__)


class InferenceExecutor:
    """
    Executes AI inference steps within workflows.

    Manages multiple inference providers (TFLite, ONNX) and handles
    the full inference pipeline: preprocessing -> inference -> postprocessing.

    Example:
        executor = InferenceExecutor()
        await executor.initialize()

        # Register a provider
        from rufus.implementations.inference.tflite import TFLiteInferenceProvider
        executor.register_provider(TFLiteInferenceProvider())

        # Execute inference step
        result = await executor.execute_inference(
            config=ai_config,
            state=workflow_state,
            context=step_context
        )
    """

    def __init__(self):
        self._providers: Dict[str, InferenceProvider] = {}
        self._initialized = False
        self._model_cache: Dict[str, str] = {}  # model_name -> runtime

    async def initialize(self) -> None:
        """Initialize all registered providers."""
        if self._initialized:
            return

        for runtime, provider in self._providers.items():
            await provider.initialize()

        self._initialized = True
        logger.info(f"InferenceExecutor initialized with providers: {list(self._providers.keys())}")

    async def close(self) -> None:
        """Close all providers and clean up resources."""
        for provider in self._providers.values():
            await provider.close()
        self._providers.clear()
        self._model_cache.clear()
        self._initialized = False
        logger.info("InferenceExecutor closed")

    def register_provider(self, provider: InferenceProvider) -> None:
        """
        Register an inference provider.

        Args:
            provider: InferenceProvider implementation (TFLite, ONNX, etc.)
        """
        runtime = provider.runtime.value
        self._providers[runtime] = provider
        logger.info(f"Registered inference provider: {runtime}")

    def get_provider(self, runtime: str) -> Optional[InferenceProvider]:
        """Get provider for a specific runtime."""
        return self._providers.get(runtime)

    def _get_value_from_path(self, obj: Any, path: str) -> Any:
        """
        Get a value from an object using a dot-separated path.

        Examples:
            _get_value_from_path(state, "sensor_data") -> state.sensor_data
            _get_value_from_path(state, "readings.temperature") -> state.readings.temperature
        """
        # Handle 'state.' prefix
        if path.startswith("state."):
            path = path[6:]

        parts = path.split(".")
        value = obj

        for part in parts:
            if hasattr(value, part):
                value = getattr(value, part)
            elif isinstance(value, dict) and part in value:
                value = value[part]
            else:
                raise ValueError(f"Cannot access '{part}' in path '{path}'")

        return value

    def _preprocess_input(
        self,
        data: Any,
        preprocessing: Optional[str],
        params: Dict[str, Any]
    ) -> np.ndarray:
        """Apply preprocessing to input data."""
        # Convert to numpy array
        if isinstance(data, (list, tuple)):
            arr = np.array(data, dtype=np.float32)
        elif isinstance(data, np.ndarray):
            arr = data.astype(np.float32)
        elif hasattr(data, 'model_dump'):
            # Pydantic model - dump to dict then extract values
            arr = np.array(list(data.model_dump().values()), dtype=np.float32)
        else:
            arr = np.array([data], dtype=np.float32)

        if preprocessing is None or preprocessing == "none":
            return arr

        if preprocessing == "normalize":
            mean = params.get("mean", 0.0)
            std = params.get("std", 1.0)
            scale = params.get("scale", 1.0)
            preprocessor = NormalizePreprocessor(mean=mean, std=std, scale=scale)
            return preprocessor(arr)

        if preprocessing == "resize":
            target_size = params.get("target_size")
            if target_size:
                # Simple reshape - production would use proper interpolation
                return arr.reshape(target_size)
            return arr

        if preprocessing == "flatten":
            return arr.flatten()

        if preprocessing == "expand_dims":
            axis = params.get("axis", 0)
            return np.expand_dims(arr, axis=axis)

        logger.warning(f"Unknown preprocessing type: {preprocessing}")
        return arr

    def _postprocess_output(
        self,
        result: InferenceResult,
        postprocessing: Optional[str],
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Apply postprocessing to inference output."""
        output = result.get_primary_output()

        if output is None:
            return {
                "raw_outputs": result.outputs,
                "inference_time_ms": result.inference_time_ms,
            }

        base_result = {
            "raw_output": output.tolist() if isinstance(output, np.ndarray) else output,
            "inference_time_ms": result.inference_time_ms,
            "model_name": result.model_name,
            "model_version": result.model_version,
        }

        if postprocessing is None or postprocessing == "none":
            return base_result

        if postprocessing == "threshold":
            threshold = params.get("threshold", 0.5)
            processor = ThresholdPostprocessor(threshold=threshold)
            processed = processor(output)
            base_result.update(processed)
            return base_result

        if postprocessing == "argmax":
            labels = params.get("labels")
            processor = ArgmaxPostprocessor(labels=labels)
            processed = processor(output)
            base_result.update(processed)
            return base_result

        if postprocessing == "softmax":
            processor = SoftmaxPostprocessor()
            probabilities = processor(output)
            base_result["probabilities"] = probabilities.tolist()
            base_result["prediction"] = int(np.argmax(probabilities))
            base_result["confidence"] = float(np.max(probabilities))
            return base_result

        if postprocessing == "binary":
            threshold = params.get("threshold", 0.5)
            score = float(output.flatten()[0])
            base_result["score"] = score
            base_result["prediction"] = score > threshold
            base_result["confidence"] = score if score > threshold else (1 - score)
            return base_result

        logger.warning(f"Unknown postprocessing type: {postprocessing}")
        return base_result

    async def execute_inference(
        self,
        config: AIInferenceConfig,
        state: Any,
        context: StepContext
    ) -> Dict[str, Any]:
        """
        Execute an AI inference step.

        Args:
            config: AIInferenceConfig with model and processing settings
            state: Current workflow state
            context: Step execution context

        Returns:
            Dict with inference results to merge into state
        """
        runtime = config.runtime
        model_name = config.model_name

        logger.info(f"Executing AI inference: model={model_name}, runtime={runtime}")

        # Get provider
        provider = self.get_provider(runtime)
        if provider is None:
            error_msg = f"No provider registered for runtime: {runtime}"
            logger.error(error_msg)
            return self._handle_error(config, error_msg)

        try:
            # Load model if not already loaded
            if not provider.is_model_loaded(model_name):
                if config.model_path:
                    await provider.load_model(
                        model_path=config.model_path,
                        model_name=model_name,
                        model_version=config.model_version,
                    )
                    self._model_cache[model_name] = runtime
                else:
                    error_msg = f"Model {model_name} not loaded and no model_path provided"
                    logger.error(error_msg)
                    return self._handle_error(config, error_msg)

            # Get input data from state
            input_data = self._get_value_from_path(state, config.input_source)

            # Preprocess input
            processed_input = self._preprocess_input(
                data=input_data,
                preprocessing=config.preprocessing,
                params=config.preprocessing_params,
            )

            # Run inference with timeout
            try:
                inference_task = provider.run_inference(
                    model_name=model_name,
                    inputs={"input": processed_input},
                )
                result = await asyncio.wait_for(
                    inference_task,
                    timeout=config.timeout_ms / 1000.0
                )
            except asyncio.TimeoutError:
                error_msg = f"Inference timeout after {config.timeout_ms}ms"
                logger.error(error_msg)
                return self._handle_error(config, error_msg)

            if not result.success:
                return self._handle_error(config, result.error_message or "Inference failed")

            # Postprocess output
            processed_result = self._postprocess_output(
                result=result,
                postprocessing=config.postprocessing,
                params=config.postprocessing_params,
            )

            # Apply threshold if configured (for routing decisions)
            if config.threshold is not None:
                threshold_value = processed_result.get(config.threshold_key)
                if threshold_value is not None:
                    if isinstance(threshold_value, bool):
                        processed_result["above_threshold"] = threshold_value
                    else:
                        processed_result["above_threshold"] = float(threshold_value) > config.threshold

            # Return result under configured output key
            return {config.output_key: processed_result}

        except Exception as e:
            logger.exception(f"Inference execution failed: {e}")
            return self._handle_error(config, str(e))

    def _handle_error(self, config: AIInferenceConfig, error_msg: str) -> Dict[str, Any]:
        """Handle inference errors based on configuration."""
        fallback = config.fallback_on_error

        if fallback == "fail":
            raise RuntimeError(f"AI inference failed: {error_msg}")

        if fallback == "default" and config.default_result:
            logger.warning(f"Using default result due to error: {error_msg}")
            return {config.output_key: config.default_result}

        # "skip" - return empty result
        logger.warning(f"Skipping inference due to error: {error_msg}")
        return {
            config.output_key: {
                "error": error_msg,
                "skipped": True,
            }
        }


# Global singleton for edge agent
_inference_executor: Optional[InferenceExecutor] = None


def get_inference_executor() -> InferenceExecutor:
    """Get or create the global inference executor."""
    global _inference_executor
    if _inference_executor is None:
        _inference_executor = InferenceExecutor()
    return _inference_executor


async def initialize_inference_executor(
    use_tflite: bool = True,
    use_onnx: bool = False,
    tflite_threads: int = 4,
    onnx_threads: int = 4,
) -> InferenceExecutor:
    """
    Initialize the global inference executor with specified providers.

    Args:
        use_tflite: Enable TensorFlow Lite provider
        use_onnx: Enable ONNX Runtime provider
        tflite_threads: Thread count for TFLite
        onnx_threads: Thread count for ONNX

    Returns:
        Initialized InferenceExecutor
    """
    executor = get_inference_executor()

    if use_tflite:
        try:
            from rufus.implementations.inference.tflite import TFLiteInferenceProvider, is_tflite_available
            if is_tflite_available():
                provider = TFLiteInferenceProvider(num_threads=tflite_threads)
                executor.register_provider(provider)
        except Exception as e:
            logger.warning(f"Could not initialize TFLite provider: {e}")

    if use_onnx:
        try:
            from rufus.implementations.inference.onnx import ONNXInferenceProvider, is_onnx_available
            if is_onnx_available():
                provider = ONNXInferenceProvider(intra_op_threads=onnx_threads)
                executor.register_provider(provider)
        except Exception as e:
            logger.warning(f"Could not initialize ONNX provider: {e}")

    await executor.initialize()
    return executor

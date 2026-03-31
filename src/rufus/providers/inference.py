"""
AI Inference Provider Interface

Defines the contract for on-device AI/ML inference engines.
Supports multiple runtimes: TensorFlow Lite, ONNX, and custom implementations.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Union
from dataclasses import dataclass
from enum import Enum
try:
    import numpy as np
    _NUMPY_AVAILABLE = True
except ImportError:  # pragma: no cover
    np = None  # type: ignore[assignment]
    _NUMPY_AVAILABLE = False


class InferenceRuntime(str, Enum):
    """Supported inference runtimes."""
    TFLITE = "tflite"
    ONNX = "onnx"
    CUSTOM = "custom"


@dataclass
class ModelMetadata:
    """Metadata about a loaded model."""
    name: str
    version: str
    runtime: InferenceRuntime
    input_shapes: Dict[str, List[int]]
    output_shapes: Dict[str, List[int]]
    input_dtypes: Dict[str, str]
    output_dtypes: Dict[str, str]
    size_bytes: int
    quantized: bool = False
    description: Optional[str] = None


@dataclass
class InferenceResult:
    """Result from model inference."""
    outputs: Dict[str, Any]  # Named outputs from the model
    inference_time_ms: float
    model_name: str
    model_version: str
    success: bool = True
    error_message: Optional[str] = None

    def get_primary_output(self) -> Any:
        """Get the first/primary output tensor."""
        if self.outputs:
            return next(iter(self.outputs.values()))
        return None

    def get_prediction(self, threshold: float = 0.5) -> Dict[str, Any]:
        """Get prediction with optional thresholding for classification."""
        primary = self.get_primary_output()
        if primary is None:
            return {"prediction": None, "confidence": 0.0}

        if isinstance(primary, np.ndarray):
            if primary.size == 1:
                # Binary classification or regression
                score = float(primary.flatten()[0])
                return {
                    "prediction": score > threshold,
                    "confidence": score,
                    "raw_score": score
                }
            else:
                # Multi-class classification
                probs = primary.flatten()
                class_idx = int(np.argmax(probs))
                confidence = float(probs[class_idx])
                return {
                    "prediction": class_idx,
                    "confidence": confidence,
                    "probabilities": probs.tolist()
                }

        return {"prediction": primary, "confidence": 1.0}


class InferenceProvider(ABC):
    """
    Abstract interface for AI/ML inference providers.

    Implementations handle model loading, inference execution,
    and resource management for specific runtimes (TFLite, ONNX, etc.)
    """

    @property
    @abstractmethod
    def runtime(self) -> InferenceRuntime:
        """Return the runtime type this provider implements."""
        pass

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize the inference runtime."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Clean up resources and unload models."""
        pass

    @abstractmethod
    async def load_model(
        self,
        model_path: str,
        model_name: str,
        model_version: str = "1.0.0",
        **kwargs
    ) -> ModelMetadata:
        """
        Load a model from disk or memory.

        Args:
            model_path: Path to the model file
            model_name: Unique identifier for the model
            model_version: Version string for the model
            **kwargs: Runtime-specific options (e.g., delegates, threads)

        Returns:
            ModelMetadata with model information
        """
        pass

    @abstractmethod
    async def unload_model(self, model_name: str) -> bool:
        """
        Unload a model from memory.

        Args:
            model_name: Name of the model to unload

        Returns:
            True if successfully unloaded
        """
        pass

    @abstractmethod
    async def run_inference(
        self,
        model_name: str,
        inputs: Dict[str, Any],
        **kwargs
    ) -> InferenceResult:
        """
        Run inference on a loaded model.

        Args:
            model_name: Name of the model to use
            inputs: Dictionary mapping input names to data
            **kwargs: Runtime-specific inference options

        Returns:
            InferenceResult with outputs and timing
        """
        pass

    @abstractmethod
    def is_model_loaded(self, model_name: str) -> bool:
        """Check if a model is currently loaded."""
        pass

    @abstractmethod
    def get_model_metadata(self, model_name: str) -> Optional[ModelMetadata]:
        """Get metadata for a loaded model."""
        pass

    @abstractmethod
    def list_loaded_models(self) -> List[str]:
        """List all currently loaded models."""
        pass


class PreprocessingFunction(ABC):
    """Base class for input preprocessing."""

    @abstractmethod
    def __call__(self, data: Any) -> np.ndarray:
        """Transform input data to model-ready format."""
        pass


class PostprocessingFunction(ABC):
    """Base class for output postprocessing."""

    @abstractmethod
    def __call__(self, output: np.ndarray, **kwargs) -> Any:
        """Transform model output to application format."""
        pass


# Common preprocessing functions
class NormalizePreprocessor(PreprocessingFunction):
    """Normalize input to [0, 1] or [-1, 1] range."""

    def __init__(self, mean: float = 0.0, std: float = 1.0, scale: float = 255.0):
        self.mean = mean
        self.std = std
        self.scale = scale

    def __call__(self, data: Any) -> np.ndarray:
        arr = np.array(data, dtype=np.float32)
        arr = arr / self.scale
        arr = (arr - self.mean) / self.std
        return arr


class ResizePreprocessor(PreprocessingFunction):
    """Resize image input to target dimensions."""

    def __init__(self, target_size: tuple):
        self.target_size = target_size

    def __call__(self, data: Any) -> np.ndarray:
        # Note: In production, use PIL or cv2 for proper resizing
        arr = np.array(data, dtype=np.float32)
        # Simple reshape - real implementation would interpolate
        return arr.reshape(self.target_size)


# Common postprocessing functions
class SoftmaxPostprocessor(PostprocessingFunction):
    """Apply softmax to convert logits to probabilities."""

    def __call__(self, output: np.ndarray, **kwargs) -> np.ndarray:
        exp_output = np.exp(output - np.max(output))
        return exp_output / exp_output.sum(axis=-1, keepdims=True)


class ThresholdPostprocessor(PostprocessingFunction):
    """Apply threshold for binary classification."""

    def __init__(self, threshold: float = 0.5):
        self.threshold = threshold

    def __call__(self, output: np.ndarray, **kwargs) -> Dict[str, Any]:
        score = float(output.flatten()[0])
        return {
            "prediction": score > self.threshold,
            "confidence": score,
            "threshold": self.threshold
        }


class ArgmaxPostprocessor(PostprocessingFunction):
    """Get class index with highest probability."""

    def __init__(self, labels: Optional[List[str]] = None):
        self.labels = labels

    def __call__(self, output: np.ndarray, **kwargs) -> Dict[str, Any]:
        probs = output.flatten()
        class_idx = int(np.argmax(probs))
        result = {
            "class_index": class_idx,
            "confidence": float(probs[class_idx]),
            "probabilities": probs.tolist()
        }
        if self.labels and class_idx < len(self.labels):
            result["class_label"] = self.labels[class_idx]
        return result

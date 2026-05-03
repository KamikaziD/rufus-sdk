"""
AI Inference Provider Implementations

Provides concrete implementations for different ML runtimes:
- TensorFlow Lite (tflite)
- ONNX Runtime (onnx)
- Inference Factory (auto-detection)

Hardware Support:
- NVIDIA (CUDA/TensorRT)
- Apple Silicon (CoreML/Neural Engine)
- Coral Edge TPU
- Generic CPU (x86/ARM)
"""

from ruvon.implementations.inference.tflite import TFLiteInferenceProvider
from ruvon.implementations.inference.onnx import ONNXInferenceProvider
from ruvon.implementations.inference.factory import (
    InferenceFactory,
    HardwareIdentity,
    ProviderPreference,
    create_inference_provider,
)

__all__ = [
    "TFLiteInferenceProvider",
    "ONNXInferenceProvider",
    "InferenceFactory",
    "HardwareIdentity",
    "ProviderPreference",
    "create_inference_provider",
]

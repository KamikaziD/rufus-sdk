"""
Platform Detection Utilities

Provides utilities for detecting hardware capabilities and selecting
optimal inference providers for the current platform.

Supports detection of:
- Apple Silicon (M1/M2/M3) with Neural Engine
- CUDA-capable GPUs
- Intel/AMD CPUs with AVX/AVX2
- Coral Edge TPU
"""

import logging
import os
import platform
import subprocess
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

logger = logging.getLogger(__name__)


class AcceleratorType(str, Enum):
    """Available hardware accelerators."""
    CPU = "cpu"
    APPLE_NEURAL_ENGINE = "apple_neural_engine"
    APPLE_GPU = "apple_gpu"
    CUDA = "cuda"
    TENSORRT = "tensorrt"
    EDGE_TPU = "edge_tpu"
    OPENVINO = "openvino"


@dataclass
class PlatformInfo:
    """Information about the current platform and available accelerators."""
    system: str  # 'Darwin', 'Linux', 'Windows'
    machine: str  # 'arm64', 'x86_64', etc.
    processor: str
    is_apple_silicon: bool
    is_arm: bool
    accelerators: List[AcceleratorType]
    recommended_onnx_providers: List[str]
    recommended_runtime: str  # 'onnx' or 'tflite'


def is_apple_silicon() -> bool:
    """
    Detect if running on Apple Silicon (M1, M2, M3, etc.).

    Returns:
        True if running on Apple Silicon, False otherwise.
    """
    if platform.system() != "Darwin":
        return False

    machine = platform.machine().lower()
    if machine in ("arm64", "aarch64"):
        return True

    # Double-check with sysctl for processor brand
    try:
        result = subprocess.run(
            ["sysctl", "-n", "machdep.cpu.brand_string"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            brand = result.stdout.strip().lower()
            return "apple" in brand
    except Exception:
        pass

    return False


def has_apple_neural_engine() -> bool:
    """
    Detect if Apple Neural Engine is available.

    The Neural Engine is available on:
    - Apple Silicon Macs (M1, M2, M3, etc.)
    - iPhones with A11 Bionic or later
    - iPads with A12 Bionic or later

    Returns:
        True if Neural Engine is likely available.
    """
    if not is_apple_silicon():
        return False

    # On Apple Silicon Macs, Neural Engine is always present
    # We can verify by checking for CoreML framework availability
    try:
        # Check if CoreML framework exists
        coreml_path = "/System/Library/Frameworks/CoreML.framework"
        if os.path.exists(coreml_path):
            return True
    except Exception:
        pass

    return True  # Assume available on Apple Silicon


def has_cuda() -> bool:
    """
    Detect if CUDA is available.

    Returns:
        True if CUDA is available.
    """
    # Check for CUDA libraries
    cuda_paths = [
        "/usr/local/cuda",
        "/usr/lib/cuda",
        os.environ.get("CUDA_HOME", ""),
    ]

    for path in cuda_paths:
        if path and os.path.exists(os.path.join(path, "lib64", "libcudart.so")):
            return True

    # Try to detect via nvidia-smi
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True,
            timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            return True
    except Exception:
        pass

    return False


def has_edge_tpu() -> bool:
    """
    Detect if Coral Edge TPU is available.

    Returns:
        True if Edge TPU is detected.
    """
    try:
        # Check for Edge TPU library
        if os.path.exists("/usr/lib/libedgetpu.so.1"):
            return True

        # Check for Coral USB device
        result = subprocess.run(
            ["lsusb"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            if "18d1:9302" in result.stdout or "Google" in result.stdout:
                return True
    except Exception:
        pass

    return False


def detect_accelerators() -> List[AcceleratorType]:
    """
    Detect all available hardware accelerators.

    Returns:
        List of available accelerator types.
    """
    accelerators = [AcceleratorType.CPU]  # CPU is always available

    if is_apple_silicon():
        accelerators.append(AcceleratorType.APPLE_GPU)
        if has_apple_neural_engine():
            accelerators.append(AcceleratorType.APPLE_NEURAL_ENGINE)

    if has_cuda():
        accelerators.append(AcceleratorType.CUDA)
        # TensorRT often available with CUDA
        try:
            import tensorrt
            accelerators.append(AcceleratorType.TENSORRT)
        except ImportError:
            pass

    if has_edge_tpu():
        accelerators.append(AcceleratorType.EDGE_TPU)

    return accelerators


def get_recommended_onnx_providers(accelerators: Optional[List[AcceleratorType]] = None) -> List[str]:
    """
    Get recommended ONNX Runtime execution providers for this platform.

    Args:
        accelerators: Optional list of accelerators (auto-detected if not provided)

    Returns:
        List of ONNX execution provider names in priority order.
    """
    if accelerators is None:
        accelerators = detect_accelerators()

    providers = []

    # Add providers in priority order
    if AcceleratorType.APPLE_NEURAL_ENGINE in accelerators:
        providers.append("CoreMLExecutionProvider")

    if AcceleratorType.TENSORRT in accelerators:
        providers.append("TensorrtExecutionProvider")

    if AcceleratorType.CUDA in accelerators:
        providers.append("CUDAExecutionProvider")

    if AcceleratorType.OPENVINO in accelerators:
        providers.append("OpenVINOExecutionProvider")

    # Always include CPU as fallback
    providers.append("CPUExecutionProvider")

    return providers


def get_recommended_runtime(accelerators: Optional[List[AcceleratorType]] = None) -> str:
    """
    Get recommended ML runtime for this platform.

    Args:
        accelerators: Optional list of accelerators (auto-detected if not provided)

    Returns:
        'onnx' or 'tflite'
    """
    if accelerators is None:
        accelerators = detect_accelerators()

    # Apple Silicon: prefer ONNX with CoreML
    if AcceleratorType.APPLE_NEURAL_ENGINE in accelerators:
        return "onnx"

    # CUDA: ONNX has better GPU support
    if AcceleratorType.CUDA in accelerators:
        return "onnx"

    # Edge TPU: TFLite has native support
    if AcceleratorType.EDGE_TPU in accelerators:
        return "tflite"

    # Default: TFLite is lighter-weight
    return "tflite"


def get_platform_info() -> PlatformInfo:
    """
    Get comprehensive platform information.

    Returns:
        PlatformInfo with system details and recommendations.
    """
    accelerators = detect_accelerators()
    machine = platform.machine().lower()

    return PlatformInfo(
        system=platform.system(),
        machine=platform.machine(),
        processor=platform.processor(),
        is_apple_silicon=is_apple_silicon(),
        is_arm=machine in ("arm64", "aarch64", "armv7l", "armv8l"),
        accelerators=accelerators,
        recommended_onnx_providers=get_recommended_onnx_providers(accelerators),
        recommended_runtime=get_recommended_runtime(accelerators),
    )


def get_coreml_options(
    use_neural_engine: bool = True,
    use_cpu_only: bool = False,
    enable_on_subgraph: bool = True
) -> dict:
    """
    Get CoreML execution provider options for ONNX Runtime.

    Note: coreml_flags was introduced in ONNX Runtime 1.16+.
    For older versions, CoreML will use default settings.

    Args:
        use_neural_engine: Use Apple Neural Engine when possible
        use_cpu_only: Force CPU-only execution (disable GPU/ANE)
        enable_on_subgraph: Enable CoreML on subgraphs

    Returns:
        Dict of CoreML provider options for ONNX Runtime.
        Returns empty dict if coreml_flags not supported.
    """
    # Check if ONNX Runtime version supports coreml_flags
    try:
        import onnxruntime as ort
        version = tuple(map(int, ort.__version__.split('.')[:2]))

        # coreml_flags introduced in 1.16, but became stable in 1.17+
        if version < (1, 17):
            logger.debug(f"ONNX Runtime {ort.__version__} doesn't support coreml_flags, using defaults")
            return {}
    except Exception:
        # Can't determine version, return empty to be safe
        return {}

    options = {
        "coreml_flags": 0,
    }

    if use_cpu_only:
        # COREML_FLAG_USE_CPU_ONLY = 0x001
        options["coreml_flags"] |= 0x001
    elif use_neural_engine:
        # COREML_FLAG_ONLY_ENABLE_DEVICE_WITH_ANE = 0x004
        # This prefers Neural Engine when available
        options["coreml_flags"] |= 0x004

    if enable_on_subgraph:
        # COREML_FLAG_ENABLE_ON_SUBGRAPH = 0x002
        options["coreml_flags"] |= 0x002

    return options


def log_platform_info():
    """Log platform information for debugging."""
    info = get_platform_info()

    logger.info(f"Platform: {info.system} {info.machine}")
    logger.info(f"Apple Silicon: {info.is_apple_silicon}")
    logger.info(f"Accelerators: {[a.value for a in info.accelerators]}")
    logger.info(f"Recommended ONNX providers: {info.recommended_onnx_providers}")
    logger.info(f"Recommended runtime: {info.recommended_runtime}")


# Convenience exports
__all__ = [
    "AcceleratorType",
    "PlatformInfo",
    "is_apple_silicon",
    "has_apple_neural_engine",
    "has_cuda",
    "has_edge_tpu",
    "detect_accelerators",
    "get_recommended_onnx_providers",
    "get_recommended_runtime",
    "get_platform_info",
    "get_coreml_options",
    "log_platform_info",
]

"""
Inference Factory - Automatic Hardware-Optimized Provider Selection

The InferenceFactory is the core of Rufus's "Write Once, Run Anywhere" promise.
It dynamically detects available hardware accelerators and creates the optimal
inference provider for the current platform.

Supported Hardware:
- NVIDIA Jetson/CUDA: TensorRT or CUDA execution provider
- Apple Silicon: CoreML execution provider with Neural Engine
- Coral Edge TPU: TFLite with Edge TPU delegate
- Generic x86/ARM: ONNX Runtime CPU or TFLite

Example:
    factory = InferenceFactory()
    provider = await factory.create_provider()
    # Automatically selects best provider for current hardware
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from rufus.providers.inference import InferenceProvider, InferenceRuntime
from rufus.utils.platform import (
    AcceleratorType,
    PlatformInfo,
    detect_accelerators,
    get_coreml_options,
    get_platform_info,
    get_recommended_onnx_providers,
    get_recommended_runtime,
    is_apple_silicon,
)

logger = logging.getLogger(__name__)


class ProviderPreference(str, Enum):
    """Provider selection preference."""
    AUTO = "auto"  # Automatic detection
    PERFORMANCE = "performance"  # Prefer fastest (GPU/ANE)
    EFFICIENCY = "efficiency"  # Prefer power-efficient
    COMPATIBILITY = "compatibility"  # Prefer most compatible (CPU)
    TFLITE = "tflite"  # Force TFLite
    ONNX = "onnx"  # Force ONNX


@dataclass
class HardwareIdentity:
    """
    Hardware identity for device registration and policy matching.

    This is sent to the Cloud Policy Engine during check-in to determine
    which artifact/model to deploy to this device.
    """
    device_id: str
    hardware_type: str  # 'NVIDIA', 'APPLE_SILICON', 'EDGE_TPU', 'CPU'
    accelerators: List[str]
    platform: str  # 'Darwin', 'Linux', 'Windows'
    architecture: str  # 'arm64', 'x86_64'

    # Resource availability
    vram_total_mb: Optional[int] = None
    vram_free_mb: Optional[int] = None
    ram_total_mb: Optional[int] = None
    ram_free_mb: Optional[int] = None

    # Capabilities
    supports_fp16: bool = False
    supports_int8: bool = True
    supports_neural_engine: bool = False

    # Runtime info
    onnx_providers: List[str] = field(default_factory=list)
    tflite_delegates: List[str] = field(default_factory=list)

    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API transmission."""
        return {
            "device_id": self.device_id,
            "hw": self.hardware_type,
            "accelerators": self.accelerators,
            "platform": self.platform,
            "arch": self.architecture,
            "vram_total": self.vram_total_mb,
            "vram_free": self.vram_free_mb,
            "ram_total": self.ram_total_mb,
            "ram_free": self.ram_free_mb,
            "supports_fp16": self.supports_fp16,
            "supports_int8": self.supports_int8,
            "supports_neural_engine": self.supports_neural_engine,
            "onnx_providers": self.onnx_providers,
            "tflite_delegates": self.tflite_delegates,
            "metadata": self.metadata,
        }

    def matches_condition(self, condition: str) -> bool:
        """
        Evaluate a policy condition against this hardware identity.

        Args:
            condition: Condition string like "hardware == 'NVIDIA' and vram_free >= 4096"

        Returns:
            True if condition matches this device.
        """
        if condition == "default":
            return True

        # Build evaluation context
        context = {
            "hardware": self.hardware_type,
            "platform": self.platform,
            "arch": self.architecture,
            "vram_total": self.vram_total_mb or 0,
            "vram_free": self.vram_free_mb or 0,
            "ram_total": self.ram_total_mb or 0,
            "ram_free": self.ram_free_mb or 0,
            "supports_fp16": self.supports_fp16,
            "supports_int8": self.supports_int8,
            "supports_neural_engine": self.supports_neural_engine,
            "has_gpu": self.hardware_type in ("NVIDIA", "APPLE_SILICON"),
            "has_ane": self.supports_neural_engine,
        }

        # Add accelerator checks
        for acc in self.accelerators:
            context[f"has_{acc.lower()}"] = True

        try:
            # Safe evaluation with restricted builtins
            return bool(eval(condition, {"__builtins__": {}}, context))
        except Exception as e:
            logger.warning(f"Failed to evaluate condition '{condition}': {e}")
            return False


class InferenceFactory:
    """
    Factory for creating hardware-optimized inference providers.

    Automatically detects available accelerators and creates the best
    inference provider for the current platform.

    Example:
        factory = InferenceFactory()

        # Auto-detect and create optimal provider
        provider = await factory.create_provider()

        # Or specify preference
        provider = await factory.create_provider(preference=ProviderPreference.EFFICIENCY)

        # Get hardware identity for policy engine
        identity = factory.get_hardware_identity("device-001")
    """

    def __init__(self):
        """Initialize the factory with platform detection."""
        self._platform_info: Optional[PlatformInfo] = None
        self._accelerators: Optional[List[AcceleratorType]] = None

    @property
    def platform_info(self) -> PlatformInfo:
        """Get cached platform information."""
        if self._platform_info is None:
            self._platform_info = get_platform_info()
        return self._platform_info

    @property
    def accelerators(self) -> List[AcceleratorType]:
        """Get detected accelerators."""
        if self._accelerators is None:
            self._accelerators = detect_accelerators()
        return self._accelerators

    def get_hardware_type(self) -> str:
        """
        Get the primary hardware type for policy matching.

        Returns:
            Hardware type string: 'NVIDIA', 'APPLE_SILICON', 'EDGE_TPU', or 'CPU'
        """
        if AcceleratorType.CUDA in self.accelerators:
            return "NVIDIA"
        elif AcceleratorType.APPLE_NEURAL_ENGINE in self.accelerators:
            return "APPLE_SILICON"
        elif AcceleratorType.EDGE_TPU in self.accelerators:
            return "EDGE_TPU"
        return "CPU"

    def get_hardware_identity(
        self,
        device_id: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> HardwareIdentity:
        """
        Generate hardware identity for device registration.

        Args:
            device_id: Unique device identifier
            metadata: Optional additional metadata

        Returns:
            HardwareIdentity for policy engine check-in
        """
        info = self.platform_info

        # Detect VRAM for NVIDIA
        vram_total = None
        vram_free = None
        if AcceleratorType.CUDA in self.accelerators:
            vram_total, vram_free = self._detect_nvidia_vram()

        # Detect RAM
        ram_total, ram_free = self._detect_system_ram()

        # Determine supported features
        supports_fp16 = (
            AcceleratorType.CUDA in self.accelerators or
            AcceleratorType.APPLE_NEURAL_ENGINE in self.accelerators
        )

        # Get available ONNX providers
        onnx_providers = []
        try:
            from rufus.implementations.inference.onnx import get_available_providers
            onnx_providers = get_available_providers()
        except Exception:
            pass

        # Get TFLite delegate info
        tflite_delegates = []
        if AcceleratorType.EDGE_TPU in self.accelerators:
            tflite_delegates.append("edge_tpu")
        if AcceleratorType.CUDA in self.accelerators:
            tflite_delegates.append("gpu")

        return HardwareIdentity(
            device_id=device_id,
            hardware_type=self.get_hardware_type(),
            accelerators=[a.value for a in self.accelerators],
            platform=info.system,
            architecture=info.machine,
            vram_total_mb=vram_total,
            vram_free_mb=vram_free,
            ram_total_mb=ram_total,
            ram_free_mb=ram_free,
            supports_fp16=supports_fp16,
            supports_int8=True,  # All platforms support INT8
            supports_neural_engine=AcceleratorType.APPLE_NEURAL_ENGINE in self.accelerators,
            onnx_providers=onnx_providers,
            tflite_delegates=tflite_delegates,
            metadata=metadata or {},
        )

    def _detect_nvidia_vram(self) -> tuple:
        """Detect NVIDIA GPU VRAM."""
        try:
            import subprocess
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.total,memory.free",
                 "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                line = result.stdout.strip().split("\n")[0]
                total, free = line.split(",")
                return int(total.strip()), int(free.strip())
        except Exception:
            pass
        return None, None

    def _detect_system_ram(self) -> tuple:
        """Detect system RAM."""
        try:
            import os
            if hasattr(os, 'sysconf'):
                # Linux/macOS
                page_size = os.sysconf('SC_PAGE_SIZE')
                total_pages = os.sysconf('SC_PHYS_PAGES')
                avail_pages = os.sysconf('SC_AVPHYS_PAGES')
                total_mb = (page_size * total_pages) // (1024 * 1024)
                free_mb = (page_size * avail_pages) // (1024 * 1024)
                return total_mb, free_mb
        except Exception:
            pass
        return None, None

    async def create_provider(
        self,
        preference: ProviderPreference = ProviderPreference.AUTO,
        **kwargs
    ) -> InferenceProvider:
        """
        Create an inference provider optimized for current hardware.

        Args:
            preference: Provider selection preference
            **kwargs: Additional provider-specific options

        Returns:
            Initialized InferenceProvider
        """
        if preference == ProviderPreference.TFLITE:
            return await self._create_tflite_provider(**kwargs)
        elif preference == ProviderPreference.ONNX:
            return await self._create_onnx_provider(**kwargs)
        elif preference == ProviderPreference.COMPATIBILITY:
            return await self._create_cpu_provider(**kwargs)
        elif preference == ProviderPreference.EFFICIENCY:
            return await self._create_efficient_provider(**kwargs)
        elif preference == ProviderPreference.PERFORMANCE:
            return await self._create_performance_provider(**kwargs)
        else:
            # AUTO - use platform recommendation
            return await self._create_auto_provider(**kwargs)

    async def _create_auto_provider(self, **kwargs) -> InferenceProvider:
        """Create provider based on automatic detection."""
        runtime = get_recommended_runtime(self.accelerators)

        if runtime == "onnx":
            return await self._create_onnx_provider(**kwargs)
        else:
            return await self._create_tflite_provider(**kwargs)

    async def _create_performance_provider(self, **kwargs) -> InferenceProvider:
        """Create provider optimized for performance."""
        # Prefer ONNX with GPU providers
        if AcceleratorType.CUDA in self.accelerators:
            return await self._create_onnx_provider(
                providers=["TensorrtExecutionProvider", "CUDAExecutionProvider", "CPUExecutionProvider"],
                **kwargs
            )
        elif AcceleratorType.APPLE_NEURAL_ENGINE in self.accelerators:
            return await self._create_onnx_provider(
                providers=["CoreMLExecutionProvider", "CPUExecutionProvider"],
                use_neural_engine=True,
                **kwargs
            )
        elif AcceleratorType.EDGE_TPU in self.accelerators:
            return await self._create_tflite_provider(use_edgetpu=True, **kwargs)
        else:
            return await self._create_onnx_provider(**kwargs)

    async def _create_efficient_provider(self, **kwargs) -> InferenceProvider:
        """Create provider optimized for power efficiency."""
        # Apple Neural Engine is very power efficient
        if AcceleratorType.APPLE_NEURAL_ENGINE in self.accelerators:
            return await self._create_onnx_provider(
                providers=["CoreMLExecutionProvider", "CPUExecutionProvider"],
                use_neural_engine=True,
                **kwargs
            )
        # Edge TPU is also efficient
        elif AcceleratorType.EDGE_TPU in self.accelerators:
            return await self._create_tflite_provider(use_edgetpu=True, **kwargs)
        # Default to TFLite (lighter runtime)
        else:
            return await self._create_tflite_provider(**kwargs)

    async def _create_cpu_provider(self, **kwargs) -> InferenceProvider:
        """Create CPU-only provider for maximum compatibility."""
        from rufus.implementations.inference.onnx import ONNXInferenceProvider, is_onnx_available
        from rufus.implementations.inference.tflite import TFLiteInferenceProvider, is_tflite_available

        # Prefer ONNX for CPU (better optimization)
        if is_onnx_available():
            provider = ONNXInferenceProvider(
                providers=["CPUExecutionProvider"],
                intra_op_threads=kwargs.get("num_threads", 4),
            )
        elif is_tflite_available():
            provider = TFLiteInferenceProvider(
                num_threads=kwargs.get("num_threads", 4),
                use_gpu=False,
                use_edgetpu=False,
            )
        else:
            raise RuntimeError("No inference runtime available. Install onnxruntime or tflite-runtime")

        await provider.initialize()
        return provider

    async def _create_onnx_provider(self, **kwargs) -> InferenceProvider:
        """Create ONNX Runtime provider with optimal settings."""
        from rufus.implementations.inference.onnx import ONNXInferenceProvider, is_onnx_available

        if not is_onnx_available():
            raise RuntimeError("ONNX Runtime not available. Install with: pip install onnxruntime")

        # Get providers
        providers = kwargs.pop("providers", None)
        if providers is None:
            providers = get_recommended_onnx_providers(self.accelerators)

        # Configure CoreML options for Apple Silicon
        use_neural_engine = kwargs.pop("use_neural_engine", False)
        provider_options = None

        if "CoreMLExecutionProvider" in providers and is_apple_silicon():
            coreml_opts = get_coreml_options(
                use_neural_engine=use_neural_engine,
                use_cpu_only=False,
            )
            provider_options = [
                coreml_opts if p == "CoreMLExecutionProvider" else {}
                for p in providers
            ]

        provider = ONNXInferenceProvider(
            providers=providers,
            intra_op_threads=kwargs.get("num_threads", 4),
            inter_op_threads=kwargs.get("inter_op_threads", 1),
            graph_optimization_level=kwargs.get("optimization_level", "all"),
        )

        # Store provider options for session creation
        if provider_options:
            provider._provider_options = provider_options

        await provider.initialize()

        logger.info(
            f"Created ONNX provider: providers={providers}, "
            f"neural_engine={use_neural_engine}"
        )

        return provider

    async def _create_tflite_provider(self, **kwargs) -> InferenceProvider:
        """Create TFLite provider with optimal settings."""
        from rufus.implementations.inference.tflite import TFLiteInferenceProvider, is_tflite_available

        if not is_tflite_available():
            raise RuntimeError("TFLite not available. Install with: pip install tflite-runtime")

        # Determine delegate usage
        use_gpu = kwargs.get("use_gpu", AcceleratorType.CUDA in self.accelerators)
        use_edgetpu = kwargs.get("use_edgetpu", AcceleratorType.EDGE_TPU in self.accelerators)

        # Note: TFLite CoreML delegate is iOS-only, not available in Python on macOS
        if is_apple_silicon() and use_gpu:
            logger.warning(
                "TFLite GPU delegate not available on Apple Silicon in Python. "
                "Consider using ONNX Runtime with CoreMLExecutionProvider instead."
            )
            use_gpu = False

        provider = TFLiteInferenceProvider(
            num_threads=kwargs.get("num_threads", 4),
            use_gpu=use_gpu,
            use_edgetpu=use_edgetpu,
        )

        await provider.initialize()

        logger.info(
            f"Created TFLite provider: gpu={use_gpu}, edgetpu={use_edgetpu}"
        )

        return provider


# Convenience function
async def create_inference_provider(
    preference: ProviderPreference = ProviderPreference.AUTO,
    **kwargs
) -> InferenceProvider:
    """
    Create an inference provider optimized for current hardware.

    This is a convenience function that creates an InferenceFactory
    and returns the appropriate provider.

    Args:
        preference: Provider selection preference
        **kwargs: Provider-specific options

    Returns:
        Initialized InferenceProvider

    Example:
        provider = await create_inference_provider()
        await provider.load_model("model.onnx", "my_model")
        result = await provider.run_inference("my_model", {"input": data})
    """
    factory = InferenceFactory()
    return await factory.create_provider(preference, **kwargs)


__all__ = [
    "InferenceFactory",
    "HardwareIdentity",
    "ProviderPreference",
    "create_inference_provider",
]

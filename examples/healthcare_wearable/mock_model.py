"""
Mock Model Generator for Healthcare Demo

Creates a simple numpy-based mock model that mimics TFLite behavior
for testing the AI inference pipeline without actual TFLite dependencies.
"""

import numpy as np
from typing import Dict, Any, List, Optional
import time
import logging

logger = logging.getLogger(__name__)


class MockAnomalyDetector:
    """
    Mock anomaly detection model for testing.

    Simulates a trained model that detects anomalies in vital signs
    based on simple threshold rules + random variation.
    """

    def __init__(self, threshold: float = 0.7):
        self.threshold = threshold
        self.version = "1.0.0-mock"
        self.input_shape = [1, 6]  # batch, features
        self.output_shape = [1, 1]  # batch, score

    def predict(self, features: np.ndarray) -> Dict[str, Any]:
        """
        Run mock inference on input features.

        Args:
            features: numpy array of shape [6] or [1, 6]
                     [hr_norm, spo2_norm, temp_norm, accel, hrv, activity]

        Returns:
            Dict with prediction results
        """
        start_time = time.perf_counter()

        # Ensure correct shape
        if features.ndim == 1:
            features = features.reshape(1, -1)

        # Extract normalized features
        hr = features[0, 0]      # Heart rate normalized
        spo2 = features[0, 1]    # SpO2 normalized
        temp = features[0, 2]    # Temperature normalized
        accel = features[0, 3]   # Accelerometer magnitude
        hrv = features[0, 4]     # HRV normalized
        activity = features[0, 5]  # Activity level

        # Calculate anomaly score based on deviation from normal
        # Normal: hr~0.25 (70bpm), spo2~0.87 (98%), temp~0.36 (36.8C)
        score = 0.0

        # Heart rate contribution
        hr_deviation = abs(hr - 0.25)
        if hr < 0.07 or hr > 0.64:  # <50 or >130 bpm
            score += hr_deviation * 1.5

        # SpO2 contribution (low SpO2 is critical)
        if spo2 < 0.33:  # <90%
            score += (0.33 - spo2) * 3.0

        # Temperature contribution
        temp_deviation = abs(temp - 0.36)
        if temp < 0.0 or temp > 0.7:  # <35 or >38.5C
            score += temp_deviation * 1.2

        # Fall detection (high acceleration)
        if accel > 2.0:
            score += (accel - 1.0) * 0.5

        # Add small random variation for realism
        score += np.random.uniform(-0.05, 0.05)

        # Normalize to [0, 1]
        score = np.clip(score, 0.0, 1.0)

        inference_time = (time.perf_counter() - start_time) * 1000

        return {
            "score": float(score),
            "is_anomaly": score > self.threshold,
            "confidence": float(score),
            "inference_time_ms": inference_time,
            "model_version": self.version,
        }


class MockInferenceProvider:
    """
    Mock inference provider that uses MockAnomalyDetector.

    Can be used in place of TFLiteInferenceProvider for testing.
    """

    def __init__(self):
        self._models: Dict[str, MockAnomalyDetector] = {}
        self._initialized = False

    async def initialize(self) -> None:
        self._initialized = True
        logger.info("MockInferenceProvider initialized")

    async def close(self) -> None:
        self._models.clear()
        self._initialized = False

    async def load_model(
        self,
        model_path: str,
        model_name: str,
        model_version: str = "1.0.0",
        **kwargs
    ):
        """Load a mock model (ignores model_path)."""
        self._models[model_name] = MockAnomalyDetector()
        logger.info(f"Loaded mock model: {model_name}")
        return {
            "name": model_name,
            "version": model_version,
            "input_shapes": {"input": [1, 6]},
            "output_shapes": {"output": [1, 1]},
        }

    async def unload_model(self, model_name: str) -> bool:
        if model_name in self._models:
            del self._models[model_name]
            return True
        return False

    async def run_inference(
        self,
        model_name: str,
        inputs: Dict[str, Any],
        **kwargs
    ) -> Dict[str, Any]:
        """Run mock inference."""
        if model_name not in self._models:
            return {
                "success": False,
                "error": f"Model {model_name} not loaded",
            }

        model = self._models[model_name]
        input_data = inputs.get("input", next(iter(inputs.values())))
        features = np.array(input_data, dtype=np.float32)

        result = model.predict(features)

        return {
            "outputs": {"output": np.array([[result["score"]]])},
            "inference_time_ms": result["inference_time_ms"],
            "model_name": model_name,
            "model_version": result["model_version"],
            "success": True,
        }

    def is_model_loaded(self, model_name: str) -> bool:
        return model_name in self._models

    def get_model_metadata(self, model_name: str):
        if model_name in self._models:
            return {
                "name": model_name,
                "version": "1.0.0-mock",
                "runtime": "mock",
            }
        return None

    def list_loaded_models(self) -> List[str]:
        return list(self._models.keys())

    @property
    def runtime(self):
        from rufus.providers.inference import InferenceRuntime
        return InferenceRuntime.TFLITE  # Pretend to be TFLite


def create_mock_detector() -> MockAnomalyDetector:
    """Create and return a mock anomaly detector."""
    return MockAnomalyDetector()

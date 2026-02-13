"""
Mock Model Generator for Industrial IoT Demo

Creates a simple numpy-based mock model that mimics TFLite behavior
for testing the predictive maintenance pipeline.
"""

import numpy as np
from typing import Dict, Any, List
import time
import logging

logger = logging.getLogger(__name__)


class MockMaintenancePredictor:
    """
    Mock predictive maintenance model for testing.

    Simulates a trained model that predicts equipment failure
    based on vibration, temperature, and electrical features.
    """

    def __init__(self, threshold: float = 0.6):
        self.threshold = threshold
        self.version = "1.0.0-mock"
        self.input_shape = [1, 11]  # batch, features
        self.output_shape = [1, 1]  # batch, probability

    def predict(self, features: np.ndarray) -> Dict[str, Any]:
        """
        Run mock inference on input features.

        Args:
            features: numpy array of shape [11] or [1, 11]
                     [vib_overall, vib_x, vib_y, vib_z, accel,
                      motor_temp, bearing_temp, temp_rise,
                      current, power, pf_deviation]

        Returns:
            Dict with prediction results
        """
        start_time = time.perf_counter()

        if features.ndim == 1:
            features = features.reshape(1, -1)

        # Extract features
        vib_overall = features[0, 0]
        vib_x = features[0, 1]
        vib_y = features[0, 2]
        vib_z = features[0, 3]
        accel = features[0, 4]
        motor_temp = features[0, 5]
        bearing_temp = features[0, 6]
        temp_rise = features[0, 7]
        current = features[0, 8]
        power = features[0, 9]
        pf_deviation = features[0, 10]

        # Calculate failure probability based on multiple factors
        prob = 0.0

        # Vibration contribution (most important for rotating equipment)
        if vib_overall > 0.5:  # >7.5 mm/s
            prob += (vib_overall - 0.3) * 0.8
        elif vib_overall > 0.3:  # >4.5 mm/s
            prob += (vib_overall - 0.3) * 0.4

        # High acceleration peaks indicate impacting
        if accel > 0.4:
            prob += accel * 0.3

        # Temperature contribution
        if motor_temp > 0.6:  # >80°C
            prob += (motor_temp - 0.5) * 0.6
        if bearing_temp > 0.5:  # >70°C
            prob += (bearing_temp - 0.4) * 0.4

        # Electrical contribution
        if current > 0.85:  # Overloaded
            prob += (current - 0.7) * 0.3
        if pf_deviation > 0.3:
            prob += pf_deviation * 0.2

        # Add random variation
        prob += np.random.uniform(-0.03, 0.03)

        # Normalize to [0, 1]
        prob = np.clip(prob, 0.0, 1.0)

        inference_time = (time.perf_counter() - start_time) * 1000

        return {
            "failure_probability": float(prob),
            "is_failure_predicted": prob > self.threshold,
            "confidence": float(prob),
            "inference_time_ms": inference_time,
            "model_version": self.version,
        }


class MockMaintenanceProvider:
    """
    Mock inference provider for predictive maintenance.
    """

    def __init__(self):
        self._models: Dict[str, MockMaintenancePredictor] = {}
        self._initialized = False

    async def initialize(self) -> None:
        self._initialized = True
        logger.info("MockMaintenanceProvider initialized")

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
        self._models[model_name] = MockMaintenancePredictor()
        logger.info(f"Loaded mock model: {model_name}")
        return {
            "name": model_name,
            "version": model_version,
            "input_shapes": {"input": [1, 11]},
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
        if model_name not in self._models:
            return {"success": False, "error": f"Model {model_name} not loaded"}

        model = self._models[model_name]
        input_data = inputs.get("input", next(iter(inputs.values())))
        features = np.array(input_data, dtype=np.float32)

        result = model.predict(features)

        return {
            "outputs": {"output": np.array([[result["failure_probability"]]])},
            "inference_time_ms": result["inference_time_ms"],
            "model_name": model_name,
            "model_version": result["model_version"],
            "success": True,
        }

    def is_model_loaded(self, model_name: str) -> bool:
        return model_name in self._models

    def list_loaded_models(self) -> List[str]:
        return list(self._models.keys())

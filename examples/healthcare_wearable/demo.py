#!/usr/bin/env python3
"""
Healthcare Wearable Demo - Rufus Edge AI Inference

Demonstrates on-device AI for patient vital signs monitoring:
1. Normal readings - no alert
2. Threshold breach - immediate alert
3. AI-detected anomaly - pattern-based alert
4. Emergency situation - critical alert

Usage:
    python examples/healthcare_wearable/demo.py

This demo shows how Rufus Edge handles:
- On-device ML inference for anomaly detection
- Offline-first health monitoring
- Store-and-Forward for alert sync
"""

import asyncio
import sys
import os
import logging

# Add src and project root to path
project_root = os.path.join(os.path.dirname(__file__), '..', '..')
sys.path.insert(0, os.path.join(project_root, 'src'))
sys.path.insert(0, project_root)

from rufus.implementations.persistence.memory import InMemoryPersistence
from rufus.implementations.execution.sync import SyncExecutor
from rufus.implementations.observability.logging import LoggingObserver
from rufus.implementations.expression_evaluator.simple import SimpleExpressionEvaluator
from rufus.implementations.templating.jinja2 import Jinja2TemplateEngine
from rufus.builder import WorkflowBuilder

from examples.healthcare_wearable.models import SensorData, VitalMonitoringState
from examples.healthcare_wearable.mock_model import MockAnomalyDetector, MockInferenceProvider

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)


async def run_healthcare_demo():
    """Run the healthcare wearable demo."""
    print("\n" + "=" * 70)
    print("  RUFUS EDGE - Healthcare Wearable AI Demo")
    print("  On-Device Vital Signs Monitoring with Anomaly Detection")
    print("=" * 70 + "\n")

    # Initialize components
    persistence = InMemoryPersistence()
    await persistence.initialize()

    executor = SyncExecutor()
    observer = LoggingObserver()

    # Initialize mock inference provider
    mock_provider = MockInferenceProvider()
    await mock_provider.initialize()
    await mock_provider.load_model(
        model_path="mock://anomaly_detector",
        model_name="vital_anomaly_detector",
        model_version="1.0.0"
    )

    # Build workflow registry
    import yaml
    workflow_path = os.path.join(
        os.path.dirname(__file__),
        'vital_monitoring_workflow.yaml'
    )

    with open(workflow_path, 'r') as f:
        workflow_config = yaml.safe_load(f)

    workflow_registry = {
        "VitalMonitoring": {
            "type": "VitalMonitoring",
            "initial_state_model_path": "examples.healthcare_wearable.models.VitalMonitoringState",
            "steps": workflow_config.get("steps", []),
        }
    }

    builder = WorkflowBuilder(
        workflow_registry=workflow_registry,
        expression_evaluator_cls=SimpleExpressionEvaluator,
        template_engine_cls=Jinja2TemplateEngine,
    )

    # ─────────────────────────────────────────────────────────────────────────
    # Demo 1: Normal Readings
    # ─────────────────────────────────────────────────────────────────────────
    print("\n" + "-" * 70)
    print("Demo 1: NORMAL READINGS - Healthy patient vital signs")
    print("-" * 70)

    normal_sensors = SensorData(
        heart_rate=72.0,
        spo2=98.0,
        temperature=36.6,
        accel_x=0.1,
        accel_y=0.05,
        accel_z=0.98,
    )

    workflow1 = await builder.create_workflow(
        workflow_type="VitalMonitoring",
        persistence_provider=persistence,
        execution_provider=executor,
        workflow_builder=builder,
        expression_evaluator_cls=SimpleExpressionEvaluator,
        template_engine_cls=Jinja2TemplateEngine,
        workflow_observer=observer,
        initial_data={
            "patient_id": "patient_001",
            "device_id": "wearable_001",
            "sensor_data": normal_sensors.model_dump(),
        }
    )

    # Run workflow steps (manually execute since we're using simplified demo)
    print(f"  Patient: {workflow1.state.patient_id}")
    print(f"  Heart Rate: {normal_sensors.heart_rate} bpm")
    print(f"  SpO2: {normal_sensors.spo2}%")
    print(f"  Temperature: {normal_sensors.temperature}°C")

    # Simulate feature extraction
    features = [
        (normal_sensors.heart_rate - 40) / 140,  # HR normalized
        (normal_sensors.spo2 - 85) / 15,         # SpO2 normalized
        (normal_sensors.temperature - 35) / 5,   # Temp normalized
        1.0,                                      # Accel magnitude (normal)
        0.5,                                      # HRV normalized
        0.0,                                      # Not moving
    ]

    # Run mock inference
    result = await mock_provider.run_inference(
        "vital_anomaly_detector",
        {"input": features}
    )

    anomaly_score = result["outputs"]["output"][0][0]
    print(f"\n  AI Anomaly Score: {anomaly_score:.3f} (threshold: 0.7)")
    print(f"  Result: {'ANOMALY DETECTED' if anomaly_score > 0.7 else 'NORMAL - No alert'}")

    # ─────────────────────────────────────────────────────────────────────────
    # Demo 2: Low SpO2 (Threshold Breach)
    # ─────────────────────────────────────────────────────────────────────────
    print("\n" + "-" * 70)
    print("Demo 2: LOW SpO2 - Threshold-based alert (no AI needed)")
    print("-" * 70)

    low_spo2_sensors = SensorData(
        heart_rate=88.0,
        spo2=87.0,  # Below 90% threshold
        temperature=37.2,
        accel_x=0.1,
        accel_y=0.05,
        accel_z=0.98,
    )

    print(f"  Heart Rate: {low_spo2_sensors.heart_rate} bpm")
    print(f"  SpO2: {low_spo2_sensors.spo2}% (CRITICAL - below 90%)")
    print(f"  Temperature: {low_spo2_sensors.temperature}°C")
    print(f"\n  Result: CRITICAL ALERT - Hypoxia detected")
    print(f"  Action: Immediate caregiver notification")

    # ─────────────────────────────────────────────────────────────────────────
    # Demo 3: Subtle Anomaly (AI Detection)
    # ─────────────────────────────────────────────────────────────────────────
    print("\n" + "-" * 70)
    print("Demo 3: SUBTLE ANOMALY - AI detects pattern human might miss")
    print("-" * 70)

    subtle_sensors = SensorData(
        heart_rate=95.0,  # Elevated but within range
        spo2=93.0,        # Low-normal
        temperature=37.8, # Slightly elevated
        accel_x=0.2,
        accel_y=0.1,
        accel_z=0.95,
        heart_rate_variability=25.0,  # Low HRV can indicate stress
    )

    print(f"  Heart Rate: {subtle_sensors.heart_rate} bpm (elevated)")
    print(f"  SpO2: {subtle_sensors.spo2}% (low-normal)")
    print(f"  Temperature: {subtle_sensors.temperature}°C (slightly elevated)")
    print(f"  HRV: {subtle_sensors.heart_rate_variability}ms (low)")

    features_subtle = [
        (subtle_sensors.heart_rate - 40) / 140,
        (subtle_sensors.spo2 - 85) / 15,
        (subtle_sensors.temperature - 35) / 5,
        1.05,
        subtle_sensors.heart_rate_variability / 200 if subtle_sensors.heart_rate_variability else 0.5,
        0.0,
    ]

    result_subtle = await mock_provider.run_inference(
        "vital_anomaly_detector",
        {"input": features_subtle}
    )

    anomaly_score_subtle = result_subtle["outputs"]["output"][0][0]
    print(f"\n  AI Anomaly Score: {anomaly_score_subtle:.3f}")
    print(f"  Inference Time: {result_subtle['inference_time_ms']:.2f}ms")

    if anomaly_score_subtle > 0.7:
        print(f"  Result: WARNING ALERT - AI detected anomaly pattern")
        print(f"  Note: Individual readings within range, but combination is concerning")
    else:
        print(f"  Result: Monitoring continues (below threshold)")

    # ─────────────────────────────────────────────────────────────────────────
    # Demo 4: Fall Detection
    # ─────────────────────────────────────────────────────────────────────────
    print("\n" + "-" * 70)
    print("Demo 4: FALL DETECTION - High acceleration spike")
    print("-" * 70)

    fall_sensors = SensorData(
        heart_rate=110.0,  # Elevated from fall
        spo2=96.0,
        temperature=36.8,
        accel_x=2.5,       # High acceleration
        accel_y=1.8,
        accel_z=2.2,
    )

    accel_magnitude = (fall_sensors.accel_x**2 + fall_sensors.accel_y**2 + fall_sensors.accel_z**2) ** 0.5
    print(f"  Accelerometer: X={fall_sensors.accel_x}g Y={fall_sensors.accel_y}g Z={fall_sensors.accel_z}g")
    print(f"  Magnitude: {accel_magnitude:.2f}g (threshold: 3.0g)")
    print(f"  Heart Rate: {fall_sensors.heart_rate} bpm (elevated post-fall)")

    if accel_magnitude > 3.0:
        print(f"\n  Result: EMERGENCY ALERT - Possible fall detected")
        print(f"  Action: Immediate notification + location sharing")
    else:
        print(f"\n  Result: No fall detected (magnitude below threshold)")

    # ─────────────────────────────────────────────────────────────────────────
    # Summary
    # ─────────────────────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("  DEMO COMPLETE")
    print("=" * 70)
    print("""
Key Features Demonstrated:
  1. On-device AI inference (mock TFLite model)
  2. Threshold-based immediate alerting
  3. AI pattern detection for subtle anomalies
  4. Fall detection from accelerometer data
  5. Offline-first architecture

Production Deployment:
  - Replace MockInferenceProvider with TFLiteInferenceProvider
  - Deploy trained anomaly detection model
  - Configure cloud sync for alert delivery
  - Enable encrypted local storage (SQLCipher)
    """)

    # Cleanup
    await mock_provider.close()
    await persistence.close()


if __name__ == "__main__":
    asyncio.run(run_healthcare_demo())

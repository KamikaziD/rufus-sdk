#!/usr/bin/env python3
"""
Industrial IoT Predictive Maintenance Demo - Ruvon Edge AI Inference

Demonstrates on-device AI for manufacturing equipment monitoring:
1. Normal operation - routine monitoring
2. Elevated vibration - early warning
3. High temperature - alarm condition
4. AI-predicted failure - proactive work order

Usage:
    python examples/industrial_iot/demo.py

This demo shows how Ruvon Edge handles:
- On-device ML inference for failure prediction
- Threshold-based immediate alarms
- AI pattern recognition for subtle degradation
- Automated work order generation
"""

import asyncio
import sys
import os
import logging

# Add src and project root to path
project_root = os.path.join(os.path.dirname(__file__), '..', '..')
sys.path.insert(0, os.path.join(project_root, 'src'))
sys.path.insert(0, project_root)

from examples.industrial_iot.models import (
    VibrationData,
    ThermalData,
    ElectricalData,
    EquipmentType,
)
from examples.industrial_iot.mock_model import MockMaintenanceProvider

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)


async def run_industrial_demo():
    """Run the industrial IoT predictive maintenance demo."""
    print("\n" + "=" * 70)
    print("  RUFUS EDGE - Industrial IoT Predictive Maintenance Demo")
    print("  On-Device AI for Equipment Failure Prediction")
    print("=" * 70 + "\n")

    # Initialize mock inference provider
    mock_provider = MockMaintenanceProvider()
    await mock_provider.initialize()
    await mock_provider.load_model(
        model_path="mock://maintenance_predictor",
        model_name="maintenance_predictor",
        model_version="1.0.0"
    )

    # ─────────────────────────────────────────────────────────────────────────
    # Demo 1: Normal Operation
    # ─────────────────────────────────────────────────────────────────────────
    print("\n" + "-" * 70)
    print("Demo 1: NORMAL OPERATION - Healthy motor, routine monitoring")
    print("-" * 70)

    normal_vib = VibrationData(
        x_velocity_rms=1.5,
        y_velocity_rms=1.2,
        z_velocity_rms=1.8,
        x_accel_peak=0.3,
        y_accel_peak=0.25,
        z_accel_peak=0.35,
    )
    normal_vib.overall_velocity_rms = (
        normal_vib.x_velocity_rms**2 +
        normal_vib.y_velocity_rms**2 +
        normal_vib.z_velocity_rms**2
    ) ** 0.5

    normal_thermal = ThermalData(
        motor_temp_c=52.0,
        bearing_temp_c=45.0,
        ambient_temp_c=25.0,
    )

    normal_elec = ElectricalData(
        voltage_v=400.0,
        current_a=11.5,
        power_kw=7.2,
        power_factor=0.88,
    )

    print(f"  Equipment: Motor-001 (10kW Induction Motor)")
    print(f"  Vibration: {normal_vib.overall_velocity_rms:.2f} mm/s (limit: 4.5)")
    print(f"  Motor Temp: {normal_thermal.motor_temp_c}°C (limit: 70°C)")
    print(f"  Current: {normal_elec.current_a}A (rated: 15A)")

    # Normalize features
    features_normal = [
        normal_vib.overall_velocity_rms / 15.0,
        normal_vib.x_velocity_rms / 10.0,
        normal_vib.y_velocity_rms / 10.0,
        normal_vib.z_velocity_rms / 10.0,
        max(normal_vib.x_accel_peak, normal_vib.y_accel_peak, normal_vib.z_accel_peak) / 5.0,
        (normal_thermal.motor_temp_c - 20) / 100,
        (normal_thermal.bearing_temp_c - 20) / 100,
        (normal_thermal.motor_temp_c - normal_thermal.ambient_temp_c) / 60,
        normal_elec.current_a / 20.0,
        normal_elec.power_kw / 15.0,
        abs(normal_elec.power_factor - 0.9) / 0.2,
    ]

    result = await mock_provider.run_inference(
        "maintenance_predictor",
        {"input": features_normal}
    )

    failure_prob = result["outputs"]["output"][0][0]
    print(f"\n  AI Failure Probability: {failure_prob:.1%}")
    print(f"  Inference Time: {result['inference_time_ms']:.2f}ms")
    print(f"  Result: HEALTHY - Continue normal monitoring")

    # ─────────────────────────────────────────────────────────────────────────
    # Demo 2: Elevated Vibration (Early Warning)
    # ─────────────────────────────────────────────────────────────────────────
    print("\n" + "-" * 70)
    print("Demo 2: ELEVATED VIBRATION - Bearing wear starting")
    print("-" * 70)

    elevated_vib = VibrationData(
        x_velocity_rms=4.8,   # Above warning threshold
        y_velocity_rms=3.5,
        z_velocity_rms=5.2,
        x_accel_peak=1.2,
        y_accel_peak=0.9,
        z_accel_peak=1.5,
        dominant_frequency_hz=29.8,  # Shaft frequency
    )
    elevated_vib.overall_velocity_rms = (
        elevated_vib.x_velocity_rms**2 +
        elevated_vib.y_velocity_rms**2 +
        elevated_vib.z_velocity_rms**2
    ) ** 0.5

    print(f"  Vibration: {elevated_vib.overall_velocity_rms:.2f} mm/s (WARNING >4.5)")
    print(f"  Dominant Frequency: {elevated_vib.dominant_frequency_hz} Hz (shaft speed)")
    print(f"  Peak Acceleration: {max(elevated_vib.x_accel_peak, elevated_vib.y_accel_peak, elevated_vib.z_accel_peak):.2f}g")

    features_elevated = [
        elevated_vib.overall_velocity_rms / 15.0,
        elevated_vib.x_velocity_rms / 10.0,
        elevated_vib.y_velocity_rms / 10.0,
        elevated_vib.z_velocity_rms / 10.0,
        max(elevated_vib.x_accel_peak, elevated_vib.y_accel_peak, elevated_vib.z_accel_peak) / 5.0,
        (52.0 - 20) / 100,  # Normal temp
        (48.0 - 20) / 100,
        27 / 60,
        11.5 / 20.0,
        7.2 / 15.0,
        0.02 / 0.2,
    ]

    result_elevated = await mock_provider.run_inference(
        "maintenance_predictor",
        {"input": features_elevated}
    )

    failure_prob_elevated = result_elevated["outputs"]["output"][0][0]
    print(f"\n  AI Failure Probability: {failure_prob_elevated:.1%}")
    print(f"  Result: WARNING - Bearing wear detected")
    print(f"  Recommendation: Schedule inspection within 1 week")

    # ─────────────────────────────────────────────────────────────────────────
    # Demo 3: High Temperature (Alarm Condition)
    # ─────────────────────────────────────────────────────────────────────────
    print("\n" + "-" * 70)
    print("Demo 3: HIGH TEMPERATURE - Motor overheating")
    print("-" * 70)

    hot_thermal = ThermalData(
        motor_temp_c=88.0,   # Above alarm threshold
        bearing_temp_c=72.0,
        ambient_temp_c=30.0,
    )

    print(f"  Motor Temp: {hot_thermal.motor_temp_c}°C (ALARM >85°C)")
    print(f"  Bearing Temp: {hot_thermal.bearing_temp_c}°C (elevated)")
    print(f"  Temp Rise: {hot_thermal.motor_temp_c - hot_thermal.ambient_temp_c}°C")

    features_hot = [
        0.25,  # Normal vibration
        0.2, 0.15, 0.22,
        0.1,
        (hot_thermal.motor_temp_c - 20) / 100,  # High!
        (hot_thermal.bearing_temp_c - 20) / 100,  # High!
        (hot_thermal.motor_temp_c - hot_thermal.ambient_temp_c) / 60,
        14.5 / 20.0,  # Higher current draw
        9.5 / 15.0,
        0.08 / 0.2,
    ]

    result_hot = await mock_provider.run_inference(
        "maintenance_predictor",
        {"input": features_hot}
    )

    failure_prob_hot = result_hot["outputs"]["output"][0][0]
    print(f"\n  AI Failure Probability: {failure_prob_hot:.1%}")
    print(f"  Result: ALARM - Motor overheating")
    print(f"  Action: Immediate inspection required")
    print(f"  Work Order: Check ventilation, verify load, inspect windings")

    # ─────────────────────────────────────────────────────────────────────────
    # Demo 4: Multiple Degradation Signs (AI Pattern Detection)
    # ─────────────────────────────────────────────────────────────────────────
    print("\n" + "-" * 70)
    print("Demo 4: SUBTLE DEGRADATION - AI detects combined patterns")
    print("-" * 70)

    subtle_vib = VibrationData(
        x_velocity_rms=3.8,  # Below warning but trending up
        y_velocity_rms=3.2,
        z_velocity_rms=4.1,
        x_accel_peak=0.9,
        y_accel_peak=0.7,
        z_accel_peak=1.1,
    )
    subtle_vib.overall_velocity_rms = (
        subtle_vib.x_velocity_rms**2 +
        subtle_vib.y_velocity_rms**2 +
        subtle_vib.z_velocity_rms**2
    ) ** 0.5

    subtle_thermal = ThermalData(
        motor_temp_c=65.0,   # Elevated but not alarm
        bearing_temp_c=58.0, # Elevated
        ambient_temp_c=28.0,
    )

    subtle_elec = ElectricalData(
        voltage_v=395.0,     # Slightly low
        current_a=13.8,      # Higher than normal
        power_kw=8.5,
        power_factor=0.82,   # Poor power factor
    )

    print(f"  Vibration: {subtle_vib.overall_velocity_rms:.2f} mm/s (trending up)")
    print(f"  Motor Temp: {subtle_thermal.motor_temp_c}°C (elevated)")
    print(f"  Current: {subtle_elec.current_a}A (higher than normal)")
    print(f"  Power Factor: {subtle_elec.power_factor} (poor)")

    features_subtle = [
        subtle_vib.overall_velocity_rms / 15.0,
        subtle_vib.x_velocity_rms / 10.0,
        subtle_vib.y_velocity_rms / 10.0,
        subtle_vib.z_velocity_rms / 10.0,
        max(subtle_vib.x_accel_peak, subtle_vib.y_accel_peak, subtle_vib.z_accel_peak) / 5.0,
        (subtle_thermal.motor_temp_c - 20) / 100,
        (subtle_thermal.bearing_temp_c - 20) / 100,
        (subtle_thermal.motor_temp_c - subtle_thermal.ambient_temp_c) / 60,
        subtle_elec.current_a / 20.0,
        subtle_elec.power_kw / 15.0,
        abs(subtle_elec.power_factor - 0.9) / 0.2,
    ]

    result_subtle = await mock_provider.run_inference(
        "maintenance_predictor",
        {"input": features_subtle}
    )

    failure_prob_subtle = result_subtle["outputs"]["output"][0][0]
    print(f"\n  AI Failure Probability: {failure_prob_subtle:.1%}")
    print(f"  Inference Time: {result_subtle['inference_time_ms']:.2f}ms")

    if failure_prob_subtle > 0.5:
        print(f"  Result: PREDICTIVE ALERT")
        print(f"  Analysis: Combined degradation pattern detected")
        print(f"  Contributing Factors:")
        print(f"    - Elevated vibration (trending upward)")
        print(f"    - Higher operating temperature")
        print(f"    - Increased current draw")
        print(f"    - Poor power factor")
        print(f"  Recommendation: Schedule maintenance within 30 days")
    else:
        print(f"  Result: Monitor closely, not yet critical")

    # ─────────────────────────────────────────────────────────────────────────
    # Summary
    # ─────────────────────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("  DEMO COMPLETE")
    print("=" * 70)
    print("""
Key Features Demonstrated:
  1. On-device AI inference for failure prediction
  2. ISO 10816 vibration threshold monitoring
  3. Temperature alarm handling
  4. AI pattern recognition for multi-factor degradation
  5. Automated work order generation
  6. Offline-first architecture

Production Deployment:
  - Connect to real PLCs/sensors via OPC-UA or Modbus
  - Replace mock model with trained TensorFlow Lite model
  - Configure CMMS integration for work orders
  - Enable cloud sync for fleet-wide analytics
  - Deploy to industrial edge gateways (Raspberry Pi, Siemens IOT2050)
    """)

    # Cleanup
    await mock_provider.close()


if __name__ == "__main__":
    asyncio.run(run_industrial_demo())

"""
Healthcare Wearable Workflow Steps

Step functions for the VitalMonitoring workflow.
Includes sensor reading, feature extraction, anomaly detection,
and alert generation.
"""

import logging
import uuid
from datetime import datetime
from typing import Dict, Any, List

from rufus.models import StepContext, WorkflowJumpDirective

from examples.healthcare_wearable.models import (
    AlertSeverity,
    AnomalyResult,
    HealthAlert,
    SensorData,
)

logger = logging.getLogger(__name__)


def read_sensors(state, context: StepContext, **kwargs) -> Dict[str, Any]:
    """
    Read vital signs from wearable sensors.

    In production, this would interface with actual hardware.
    For demo, sensor_data is provided in initial state.
    """
    logger.info(f"Reading sensors for patient {state.patient_id}")

    if not state.sensor_data:
        # Demo: generate mock sensor data
        state.sensor_data = SensorData(
            heart_rate=75.0,
            spo2=98.0,
            temperature=36.8,
            accel_x=0.1,
            accel_y=0.05,
            accel_z=0.98,
            step_count=1234,
            is_moving=False,
        )

    logger.info(
        f"Sensor readings: HR={state.sensor_data.heart_rate}, "
        f"SpO2={state.sensor_data.spo2}, Temp={state.sensor_data.temperature}"
    )

    return {"sensor_data_captured": True}


def extract_features(state, context: StepContext, **kwargs) -> Dict[str, Any]:
    """
    Extract features from sensor data for model input.

    Converts raw sensor readings into a normalized feature vector
    suitable for the anomaly detection model.
    """
    logger.info("Extracting features from sensor data")

    if not state.sensor_data:
        raise ValueError("No sensor data available")

    sensor = state.sensor_data

    # Normalize features to [0, 1] range
    # Heart rate: normal range 40-180 bpm
    hr_normalized = (sensor.heart_rate - 40) / 140

    # SpO2: normal range 85-100%
    spo2_normalized = (sensor.spo2 - 85) / 15

    # Temperature: normal range 35-40 C
    temp_normalized = (sensor.temperature - 35) / 5

    # Accelerometer magnitude (fall detection)
    accel_magnitude = (
        sensor.accel_x ** 2 +
        sensor.accel_y ** 2 +
        sensor.accel_z ** 2
    ) ** 0.5

    # HRV normalized (if available)
    hrv_normalized = 0.5
    if sensor.heart_rate_variability:
        hrv_normalized = min(sensor.heart_rate_variability / 200, 1.0)

    # Activity level
    activity = 1.0 if sensor.is_moving else 0.0

    # Build feature vector
    state.features = [
        hr_normalized,
        spo2_normalized,
        temp_normalized,
        accel_magnitude,
        hrv_normalized,
        activity,
    ]

    logger.info(f"Features extracted: {len(state.features)} dimensions")

    return {"features": state.features}


def check_thresholds(state, context: StepContext, **kwargs) -> Dict[str, Any]:
    """
    Check vital signs against safety thresholds.

    This provides immediate alerting for clearly dangerous readings
    without requiring the AI model.
    """
    logger.info("Checking vital signs against thresholds")

    if not state.sensor_data:
        raise ValueError("No sensor data available")

    sensor = state.sensor_data
    alerts = []

    # Heart rate checks
    if sensor.heart_rate < state.heart_rate_min:
        alerts.append(("bradycardia", AlertSeverity.WARNING, f"Low heart rate: {sensor.heart_rate} bpm"))
    elif sensor.heart_rate < 40:
        alerts.append(("severe_bradycardia", AlertSeverity.CRITICAL, f"Critically low heart rate: {sensor.heart_rate} bpm"))
    elif sensor.heart_rate > state.heart_rate_max:
        alerts.append(("tachycardia", AlertSeverity.WARNING, f"High heart rate: {sensor.heart_rate} bpm"))
    elif sensor.heart_rate > 180:
        alerts.append(("severe_tachycardia", AlertSeverity.CRITICAL, f"Critically high heart rate: {sensor.heart_rate} bpm"))

    # SpO2 checks
    if sensor.spo2 < state.spo2_min:
        if sensor.spo2 < 85:
            alerts.append(("severe_hypoxia", AlertSeverity.EMERGENCY, f"Severe hypoxia: SpO2 {sensor.spo2}%"))
        else:
            alerts.append(("hypoxia", AlertSeverity.CRITICAL, f"Low oxygen: SpO2 {sensor.spo2}%"))

    # Temperature checks
    if sensor.temperature < state.temp_min:
        alerts.append(("hypothermia", AlertSeverity.WARNING, f"Low temperature: {sensor.temperature}°C"))
    elif sensor.temperature > state.temp_max:
        if sensor.temperature > 40:
            alerts.append(("hyperthermia", AlertSeverity.CRITICAL, f"High fever: {sensor.temperature}°C"))
        else:
            alerts.append(("fever", AlertSeverity.WARNING, f"Elevated temperature: {sensor.temperature}°C"))

    # Fall detection (high acceleration spike)
    accel_magnitude = (sensor.accel_x**2 + sensor.accel_y**2 + sensor.accel_z**2) ** 0.5
    if accel_magnitude > 3.0:  # 3g threshold for fall
        alerts.append(("fall_detected", AlertSeverity.EMERGENCY, "Possible fall detected"))

    if alerts:
        # Take the most severe alert
        alert_type, severity, message = max(alerts, key=lambda x: list(AlertSeverity).index(x[1]))

        logger.warning(f"Threshold alert: {alert_type} - {message}")

        state.alert = HealthAlert(
            alert_id=f"alert_{uuid.uuid4().hex[:8]}",
            patient_id=state.patient_id,
            device_id=state.device_id,
            severity=severity,
            alert_type=alert_type,
            message=message,
            vital_readings={
                "heart_rate": sensor.heart_rate,
                "spo2": sensor.spo2,
                "temperature": sensor.temperature,
            },
        )

        # Jump directly to alert if emergency/critical
        if severity in [AlertSeverity.EMERGENCY, AlertSeverity.CRITICAL]:
            raise WorkflowJumpDirective(target_step_name="Send_Alert")

    return {"threshold_alerts": len(alerts)}


def process_anomaly_result(state, context: StepContext, **kwargs) -> Dict[str, Any]:
    """
    Process the anomaly detection result and decide next action.

    Checks the inference result against threshold and generates
    alert if anomaly detected.
    """
    logger.info("Processing anomaly detection result")

    # Get inference result from state (set by AI_INFERENCE step)
    inference_result = getattr(state, 'inference_result', None)

    if not inference_result:
        logger.warning("No inference result available, skipping anomaly check")
        raise WorkflowJumpDirective(target_step_name="Log_Readings")

    # Build anomaly result from inference
    anomaly_score = inference_result.get('confidence', 0.0)
    is_anomaly = inference_result.get('prediction', False)

    if isinstance(is_anomaly, (int, float)):
        is_anomaly = anomaly_score > state.anomaly_threshold

    state.anomaly_result = AnomalyResult(
        is_anomaly=is_anomaly,
        anomaly_score=anomaly_score,
        confidence=anomaly_score,
        inference_time_ms=inference_result.get('inference_time_ms', 0.0),
        model_version=inference_result.get('model_version', 'unknown'),
    )

    logger.info(
        f"Anomaly detection: is_anomaly={is_anomaly}, "
        f"score={anomaly_score:.3f}, threshold={state.anomaly_threshold}"
    )

    if is_anomaly and not state.alert:
        # Generate alert for AI-detected anomaly
        state.alert = HealthAlert(
            alert_id=f"alert_{uuid.uuid4().hex[:8]}",
            patient_id=state.patient_id,
            device_id=state.device_id,
            severity=AlertSeverity.WARNING,
            alert_type="ai_anomaly_detected",
            message=f"AI detected anomaly pattern (score: {anomaly_score:.2f})",
            vital_readings={
                "heart_rate": state.sensor_data.heart_rate if state.sensor_data else 0,
                "spo2": state.sensor_data.spo2 if state.sensor_data else 0,
                "temperature": state.sensor_data.temperature if state.sensor_data else 0,
            },
            anomaly_result=state.anomaly_result,
        )
        raise WorkflowJumpDirective(target_step_name="Send_Alert")

    # No anomaly - proceed to logging
    raise WorkflowJumpDirective(target_step_name="Log_Readings")


def send_alert(state, context: StepContext, **kwargs) -> Dict[str, Any]:
    """
    Send health alert to caregivers/medical staff.

    In production, this would send via:
    - Push notification to caregiver app
    - SMS to emergency contacts
    - Integration with hospital systems

    For offline operation, alert is queued for sync.
    """
    if not state.alert:
        logger.warning("No alert to send")
        raise WorkflowJumpDirective(target_step_name="Log_Readings")

    logger.warning(
        f"HEALTH ALERT: [{state.alert.severity.value.upper()}] "
        f"Patient {state.patient_id} - {state.alert.message}"
    )

    # In production, attempt to send alert
    # If offline, queue for Store-and-Forward
    try:
        # Simulated send
        # await notification_service.send_alert(state.alert)
        state.alert_sent = True
        logger.info(f"Alert {state.alert.alert_id} sent successfully")
    except Exception as e:
        logger.warning(f"Alert send failed, queuing for sync: {e}")
        state.requires_sync = True

    return {
        "alert_id": state.alert.alert_id,
        "alert_sent": state.alert_sent,
        "severity": state.alert.severity.value,
    }


def log_readings(state, context: StepContext, **kwargs) -> Dict[str, Any]:
    """
    Log vital sign readings to local storage.

    All readings are persisted locally for:
    - Historical trend analysis
    - Offline operation
    - Later sync to cloud
    """
    logger.info(f"Logging readings for patient {state.patient_id}")

    state.status = "completed"
    state.workflow_completed_at = datetime.utcnow()

    # Mark for sync if we have alerts or it's time for periodic sync
    if state.alert or state.anomaly_result:
        state.requires_sync = True

    reading_summary = {}
    if state.sensor_data:
        reading_summary = {
            "heart_rate": state.sensor_data.heart_rate,
            "spo2": state.sensor_data.spo2,
            "temperature": state.sensor_data.temperature,
            "timestamp": state.sensor_data.timestamp.isoformat(),
        }

    return {
        "logged": True,
        "requires_sync": state.requires_sync,
        "reading_summary": reading_summary,
        "anomaly_detected": state.anomaly_result.is_anomaly if state.anomaly_result else False,
    }

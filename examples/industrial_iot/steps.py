"""
Industrial IoT Predictive Maintenance Workflow Steps

Step functions for the PredictiveMaintenance workflow.
Includes sensor reading, feature extraction, prediction,
and work order generation.
"""

import logging
import uuid
from datetime import datetime
from typing import Dict, Any, List

from ruvon.models import StepContext, WorkflowJumpDirective

from examples.industrial_iot.models import (
    FailureMode,
    MaintenanceUrgency,
    MaintenanceWorkOrder,
    PredictionResult,
    VibrationData,
    ThermalData,
    ElectricalData,
)

logger = logging.getLogger(__name__)


def read_sensors(state, context: StepContext, **kwargs) -> Dict[str, Any]:
    """
    Read sensor data from industrial equipment.

    In production, this would interface with PLCs, OPC-UA servers,
    or direct sensor connections.
    """
    logger.info(f"Reading sensors for equipment {state.equipment_id}")

    # Demo: use provided sensor data or generate defaults
    if not state.vibration_data:
        state.vibration_data = VibrationData(
            x_velocity_rms=2.1,
            y_velocity_rms=1.8,
            z_velocity_rms=2.5,
            x_accel_peak=0.5,
            y_accel_peak=0.4,
            z_accel_peak=0.6,
            dominant_frequency_hz=29.5,
        )

    if not state.thermal_data:
        state.thermal_data = ThermalData(
            motor_temp_c=55.0,
            bearing_temp_c=48.0,
            ambient_temp_c=25.0,
        )

    if not state.electrical_data:
        state.electrical_data = ElectricalData(
            voltage_v=400.0,
            current_a=12.5,
            power_kw=7.8,
            power_factor=0.87,
        )

    # Calculate derived values
    vib = state.vibration_data
    vib.overall_velocity_rms = (
        vib.x_velocity_rms**2 +
        vib.y_velocity_rms**2 +
        vib.z_velocity_rms**2
    ) ** 0.5

    state.thermal_data.temp_rise_c = (
        state.thermal_data.motor_temp_c - state.thermal_data.ambient_temp_c
    )

    logger.info(
        f"Sensors read: Vib={vib.overall_velocity_rms:.2f}mm/s, "
        f"Temp={state.thermal_data.motor_temp_c:.1f}°C, "
        f"Current={state.electrical_data.current_a:.1f}A"
    )

    return {"sensors_read": True}


def extract_features(state, context: StepContext, **kwargs) -> Dict[str, Any]:
    """
    Extract features from sensor data for model input.

    Converts raw sensor readings into a normalized feature vector
    suitable for the predictive maintenance model.
    """
    logger.info("Extracting features from sensor data")

    vib = state.vibration_data
    thermal = state.thermal_data
    elec = state.electrical_data

    if not all([vib, thermal, elec]):
        raise ValueError("Missing sensor data")

    # Normalize features to [0, 1] range based on typical operating ranges

    # Vibration features (0-15 mm/s range)
    vib_overall_norm = min(vib.overall_velocity_rms / 15.0, 1.0)
    vib_x_norm = min(vib.x_velocity_rms / 10.0, 1.0)
    vib_y_norm = min(vib.y_velocity_rms / 10.0, 1.0)
    vib_z_norm = min(vib.z_velocity_rms / 10.0, 1.0)

    # Peak acceleration (0-5g range)
    accel_peak = max(vib.x_accel_peak, vib.y_accel_peak, vib.z_accel_peak)
    accel_norm = min(accel_peak / 5.0, 1.0)

    # Temperature features (20-120°C range)
    motor_temp_norm = (thermal.motor_temp_c - 20) / 100
    bearing_temp_norm = (thermal.bearing_temp_c - 20) / 100
    temp_rise_norm = thermal.temp_rise_c / 60 if thermal.temp_rise_c else 0

    # Electrical features
    current_ratio = elec.current_a / 20.0  # Assuming 20A max
    power_ratio = elec.power_kw / 15.0     # Assuming 15kW max
    pf_deviation = abs(elec.power_factor - 0.9) / 0.2  # Deviation from ideal

    # Build feature vector
    state.features = [
        vib_overall_norm,
        vib_x_norm,
        vib_y_norm,
        vib_z_norm,
        accel_norm,
        motor_temp_norm,
        bearing_temp_norm,
        temp_rise_norm,
        current_ratio,
        power_ratio,
        pf_deviation,
    ]

    logger.info(f"Features extracted: {len(state.features)} dimensions")

    return {"features": state.features}


def check_thresholds(state, context: StepContext, **kwargs) -> Dict[str, Any]:
    """
    Check sensor values against alarm thresholds.

    Provides immediate alerting for clearly dangerous conditions
    without requiring the AI model.
    """
    logger.info("Checking sensor thresholds")

    alerts = []
    urgency = MaintenanceUrgency.ROUTINE
    failure_mode = FailureMode.UNKNOWN

    vib = state.vibration_data
    thermal = state.thermal_data

    # Vibration checks (ISO 10816)
    if vib and vib.overall_velocity_rms:
        if vib.overall_velocity_rms > state.vibration_alarm_threshold:
            alerts.append(f"ALARM: Vibration {vib.overall_velocity_rms:.1f}mm/s exceeds limit")
            urgency = MaintenanceUrgency.CRITICAL
            failure_mode = FailureMode.BEARING_WEAR
        elif vib.overall_velocity_rms > state.vibration_warning_threshold:
            alerts.append(f"WARNING: Elevated vibration {vib.overall_velocity_rms:.1f}mm/s")
            if urgency.value < MaintenanceUrgency.HIGH.value:
                urgency = MaintenanceUrgency.HIGH

    # Temperature checks
    if thermal:
        if thermal.motor_temp_c > state.temp_alarm_threshold:
            alerts.append(f"ALARM: Motor temp {thermal.motor_temp_c:.0f}°C exceeds limit")
            urgency = MaintenanceUrgency.CRITICAL
            failure_mode = FailureMode.MOTOR_OVERHEATING
        elif thermal.motor_temp_c > state.temp_warning_threshold:
            alerts.append(f"WARNING: Motor temp {thermal.motor_temp_c:.0f}°C elevated")
            if urgency.value < MaintenanceUrgency.HIGH.value:
                urgency = MaintenanceUrgency.HIGH

        if thermal.bearing_temp_c > 75:
            alerts.append(f"WARNING: Bearing temp {thermal.bearing_temp_c:.0f}°C elevated")
            if urgency.value < MaintenanceUrgency.ELEVATED.value:
                urgency = MaintenanceUrgency.ELEVATED
            if failure_mode == FailureMode.UNKNOWN:
                failure_mode = FailureMode.LUBRICATION_FAILURE

    if alerts and urgency in [MaintenanceUrgency.CRITICAL, MaintenanceUrgency.EMERGENCY]:
        # Create immediate work order
        state.work_order = MaintenanceWorkOrder(
            work_order_id=f"WO_{uuid.uuid4().hex[:8]}",
            equipment_id=state.equipment_id,
            urgency=urgency,
            failure_mode=failure_mode,
            description="; ".join(alerts),
            recommended_actions=_get_recommended_actions(failure_mode),
            estimated_downtime_hours=2.0 if urgency == MaintenanceUrgency.CRITICAL else 4.0,
        )

        logger.warning(f"Threshold alarm: {state.work_order.description}")
        raise WorkflowJumpDirective(target_step_name="Create_Work_Order")

    return {"threshold_alerts": len(alerts), "max_urgency": urgency.value}


def process_prediction_result(state, context: StepContext, **kwargs) -> Dict[str, Any]:
    """
    Process the ML prediction result and decide next action.
    """
    logger.info("Processing prediction result")

    inference_result = getattr(state, 'inference_result', None)

    if not inference_result:
        logger.warning("No inference result, skipping prediction analysis")
        raise WorkflowJumpDirective(target_step_name="Log_Readings")

    # Extract prediction from inference result
    failure_prob = inference_result.get('confidence', 0.0)
    is_failure_predicted = inference_result.get('prediction', False)

    if isinstance(is_failure_predicted, (int, float)):
        is_failure_predicted = failure_prob > state.failure_probability_threshold

    # Analyze features to determine likely failure mode
    features = state.features or []
    failure_mode = _analyze_failure_mode(features)

    # Estimate days to failure based on probability
    days_to_failure = None
    if failure_prob > 0.8:
        days_to_failure = 7
    elif failure_prob > 0.6:
        days_to_failure = 30
    elif failure_prob > 0.4:
        days_to_failure = 90

    state.prediction_result = PredictionResult(
        failure_probability=failure_prob,
        predicted_failure_mode=failure_mode,
        days_to_failure=days_to_failure,
        confidence=failure_prob,
        contributing_factors=_get_contributing_factors(features),
        inference_time_ms=inference_result.get('inference_time_ms', 0.0),
        model_version=inference_result.get('model_version', 'unknown'),
    )

    logger.info(
        f"Prediction: failure_prob={failure_prob:.2%}, "
        f"mode={failure_mode.value if failure_mode else 'none'}, "
        f"days_to_failure={days_to_failure}"
    )

    if is_failure_predicted and not state.work_order:
        # Determine urgency based on probability
        if failure_prob > 0.8:
            urgency = MaintenanceUrgency.HIGH
        elif failure_prob > 0.6:
            urgency = MaintenanceUrgency.ELEVATED
        else:
            urgency = MaintenanceUrgency.ROUTINE

        state.work_order = MaintenanceWorkOrder(
            work_order_id=f"WO_{uuid.uuid4().hex[:8]}",
            equipment_id=state.equipment_id,
            urgency=urgency,
            failure_mode=failure_mode or FailureMode.UNKNOWN,
            description=f"Predicted failure: {failure_prob:.0%} probability within {days_to_failure or 90} days",
            recommended_actions=_get_recommended_actions(failure_mode),
            estimated_downtime_hours=1.0,
            prediction_result=state.prediction_result,
        )

        raise WorkflowJumpDirective(target_step_name="Create_Work_Order")

    raise WorkflowJumpDirective(target_step_name="Log_Readings")


def create_work_order(state, context: StepContext, **kwargs) -> Dict[str, Any]:
    """
    Finalize and submit work order to CMMS.
    """
    if not state.work_order:
        logger.warning("No work order to create")
        raise WorkflowJumpDirective(target_step_name="Log_Readings")

    logger.info(
        f"WORK ORDER CREATED: [{state.work_order.urgency.value.upper()}] "
        f"{state.equipment_id} - {state.work_order.failure_mode.value}"
    )
    logger.info(f"  Description: {state.work_order.description}")
    logger.info(f"  Actions: {', '.join(state.work_order.recommended_actions[:3])}")

    state.work_order_created = True
    state.requires_sync = True  # Queue for sync to CMMS

    return {
        "work_order_id": state.work_order.work_order_id,
        "urgency": state.work_order.urgency.value,
        "failure_mode": state.work_order.failure_mode.value,
    }


def log_readings(state, context: StepContext, **kwargs) -> Dict[str, Any]:
    """
    Log sensor readings to local historian.
    """
    logger.info(f"Logging readings for {state.equipment_id}")

    state.status = "completed"
    state.workflow_completed_at = datetime.utcnow()

    if state.work_order or state.prediction_result:
        state.requires_sync = True

    summary = {}
    if state.vibration_data:
        summary["vibration_rms"] = state.vibration_data.overall_velocity_rms
    if state.thermal_data:
        summary["motor_temp"] = state.thermal_data.motor_temp_c
    if state.electrical_data:
        summary["current"] = state.electrical_data.current_a

    return {
        "logged": True,
        "requires_sync": state.requires_sync,
        "summary": summary,
        "failure_predicted": state.prediction_result.failure_probability > 0.5 if state.prediction_result else False,
    }


def _analyze_failure_mode(features: List[float]) -> FailureMode:
    """Analyze features to determine likely failure mode."""
    if not features or len(features) < 11:
        return FailureMode.UNKNOWN

    vib_overall = features[0]
    motor_temp = features[5]
    bearing_temp = features[6]
    current_ratio = features[8]

    # High vibration suggests bearing or alignment issues
    if vib_overall > 0.5:
        return FailureMode.BEARING_WEAR

    # High motor temp suggests overheating
    if motor_temp > 0.6:
        return FailureMode.MOTOR_OVERHEATING

    # High bearing temp with normal motor temp suggests lubrication
    if bearing_temp > 0.5 and motor_temp < 0.5:
        return FailureMode.LUBRICATION_FAILURE

    # High current suggests electrical issues
    if current_ratio > 0.8:
        return FailureMode.ELECTRICAL_FAULT

    return FailureMode.UNKNOWN


def _get_contributing_factors(features: List[float]) -> List[str]:
    """Get list of contributing factors from features."""
    factors = []

    if not features or len(features) < 11:
        return factors

    if features[0] > 0.3:
        factors.append("Elevated vibration levels")
    if features[5] > 0.5:
        factors.append("High motor temperature")
    if features[6] > 0.4:
        factors.append("Elevated bearing temperature")
    if features[8] > 0.7:
        factors.append("High current draw")
    if features[10] > 0.3:
        factors.append("Poor power factor")

    return factors


def _get_recommended_actions(failure_mode: FailureMode) -> List[str]:
    """Get recommended maintenance actions for failure mode."""
    actions = {
        FailureMode.BEARING_WEAR: [
            "Inspect bearing condition",
            "Check lubrication level and quality",
            "Measure bearing clearances",
            "Replace bearings if worn",
            "Check shaft alignment",
        ],
        FailureMode.MOTOR_OVERHEATING: [
            "Check ventilation and cooling",
            "Inspect motor windings",
            "Verify load is within rated capacity",
            "Clean air filters and vents",
            "Check for voltage imbalance",
        ],
        FailureMode.SHAFT_MISALIGNMENT: [
            "Perform laser alignment check",
            "Adjust motor mounting",
            "Check coupling condition",
            "Verify foundation integrity",
        ],
        FailureMode.LUBRICATION_FAILURE: [
            "Replenish lubricant",
            "Check for contamination",
            "Verify lubricant type matches specification",
            "Inspect seals for leaks",
        ],
        FailureMode.ELECTRICAL_FAULT: [
            "Check electrical connections",
            "Measure insulation resistance",
            "Verify supply voltage stability",
            "Inspect motor starter/VFD",
        ],
    }

    return actions.get(failure_mode, [
        "Perform general inspection",
        "Review historical data",
        "Consult equipment manual",
    ])

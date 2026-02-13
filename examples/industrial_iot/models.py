"""
Industrial IoT State Models

Defines the data structures for predictive maintenance workflows.
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


class EquipmentType(str, Enum):
    """Types of industrial equipment."""
    MOTOR = "motor"
    PUMP = "pump"
    COMPRESSOR = "compressor"
    CONVEYOR = "conveyor"
    ROBOT_ARM = "robot_arm"
    CNC_MACHINE = "cnc_machine"


class MaintenanceUrgency(str, Enum):
    """Urgency levels for maintenance actions."""
    ROUTINE = "routine"          # Schedule during next maintenance window
    ELEVATED = "elevated"        # Schedule within 1 week
    HIGH = "high"               # Schedule within 24 hours
    CRITICAL = "critical"       # Immediate attention required
    EMERGENCY = "emergency"     # Stop equipment now


class FailureMode(str, Enum):
    """Common failure modes for industrial equipment."""
    BEARING_WEAR = "bearing_wear"
    MOTOR_OVERHEATING = "motor_overheating"
    SHAFT_MISALIGNMENT = "shaft_misalignment"
    IMBALANCE = "imbalance"
    LUBRICATION_FAILURE = "lubrication_failure"
    ELECTRICAL_FAULT = "electrical_fault"
    SEAL_LEAK = "seal_leak"
    UNKNOWN = "unknown"


class VibrationData(BaseModel):
    """Vibration sensor readings (tri-axial accelerometer)."""
    # RMS velocity (mm/s) - ISO 10816 standard
    x_velocity_rms: float = Field(..., description="X-axis velocity RMS (mm/s)")
    y_velocity_rms: float = Field(..., description="Y-axis velocity RMS (mm/s)")
    z_velocity_rms: float = Field(..., description="Z-axis velocity RMS (mm/s)")

    # Peak acceleration (g)
    x_accel_peak: float = 0.0
    y_accel_peak: float = 0.0
    z_accel_peak: float = 0.0

    # Frequency domain features
    dominant_frequency_hz: Optional[float] = None
    harmonics: List[float] = Field(default_factory=list)

    # Derived metrics
    overall_velocity_rms: Optional[float] = None
    crest_factor: Optional[float] = None  # Peak/RMS ratio

    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ThermalData(BaseModel):
    """Temperature sensor readings."""
    motor_temp_c: float = Field(..., description="Motor winding temperature (°C)")
    bearing_temp_c: float = Field(..., description="Bearing temperature (°C)")
    ambient_temp_c: float = Field(default=25.0, description="Ambient temperature (°C)")

    # Derived
    temp_rise_c: Optional[float] = None  # Motor temp - ambient

    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ElectricalData(BaseModel):
    """Electrical monitoring data."""
    voltage_v: float = Field(..., description="Supply voltage (V)")
    current_a: float = Field(..., description="Motor current (A)")
    power_kw: float = Field(..., description="Power consumption (kW)")
    power_factor: float = Field(default=0.85, description="Power factor")

    # Current signature analysis
    current_thd: Optional[float] = None  # Total harmonic distortion
    current_imbalance_pct: Optional[float] = None

    timestamp: datetime = Field(default_factory=datetime.utcnow)


class EquipmentInfo(BaseModel):
    """Equipment identification and specifications."""
    equipment_id: str
    equipment_type: EquipmentType
    location: str
    manufacturer: Optional[str] = None
    model: Optional[str] = None
    install_date: Optional[datetime] = None
    last_maintenance: Optional[datetime] = None
    operating_hours: float = 0.0

    # Operating parameters
    rated_speed_rpm: float = 1800.0
    rated_power_kw: float = 10.0
    rated_current_a: float = 15.0


class PredictionResult(BaseModel):
    """Result from predictive maintenance model."""
    failure_probability: float = 0.0  # 0-1
    predicted_failure_mode: Optional[FailureMode] = None
    days_to_failure: Optional[int] = None
    confidence: float = 0.0
    contributing_factors: List[str] = Field(default_factory=list)
    inference_time_ms: float = 0.0
    model_version: str = "unknown"


class MaintenanceWorkOrder(BaseModel):
    """Generated maintenance work order."""
    work_order_id: str
    equipment_id: str
    urgency: MaintenanceUrgency
    failure_mode: FailureMode
    description: str
    recommended_actions: List[str]
    estimated_downtime_hours: float = 1.0
    parts_required: List[str] = Field(default_factory=list)
    prediction_result: Optional[PredictionResult] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    synced: bool = False


class PredictiveMaintenanceState(BaseModel):
    """
    Workflow state for predictive maintenance.

    This state is used by the PredictiveMaintenance workflow to track
    sensor readings, predictions, and work order generation.
    """
    # Equipment info
    equipment_id: str
    equipment_type: EquipmentType = EquipmentType.MOTOR
    location: str = "unknown"
    equipment_info: Optional[EquipmentInfo] = None

    # Sensor readings
    vibration_data: Optional[VibrationData] = None
    thermal_data: Optional[ThermalData] = None
    electrical_data: Optional[ElectricalData] = None

    # Processed features
    features: Optional[List[float]] = None

    # Prediction result
    prediction_result: Optional[PredictionResult] = None

    # Work order if generated
    work_order: Optional[MaintenanceWorkOrder] = None
    work_order_created: bool = False

    # Status tracking
    status: str = "pending"
    error_message: Optional[str] = None

    # Sync status for offline operation
    requires_sync: bool = False
    synced_at: Optional[datetime] = None

    # Thresholds (from config or defaults)
    vibration_warning_threshold: float = 4.5  # mm/s ISO 10816 Class II
    vibration_alarm_threshold: float = 7.1    # mm/s
    temp_warning_threshold: float = 70.0       # °C
    temp_alarm_threshold: float = 85.0         # °C
    failure_probability_threshold: float = 0.6

    # Workflow metadata
    workflow_started_at: datetime = Field(default_factory=datetime.utcnow)
    workflow_completed_at: Optional[datetime] = None

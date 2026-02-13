"""
Healthcare Wearable State Models

Defines the data structures for patient monitoring workflows.
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from decimal import Decimal
from enum import Enum


class AlertSeverity(str, Enum):
    """Severity levels for health alerts."""
    NORMAL = "normal"
    WARNING = "warning"
    CRITICAL = "critical"
    EMERGENCY = "emergency"


class VitalType(str, Enum):
    """Types of vital sign measurements."""
    HEART_RATE = "heart_rate"
    SPO2 = "spo2"
    TEMPERATURE = "temperature"
    BLOOD_PRESSURE = "blood_pressure"
    RESPIRATORY_RATE = "respiratory_rate"


class VitalReading(BaseModel):
    """A single vital sign reading."""
    vital_type: VitalType
    value: float
    unit: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class SensorData(BaseModel):
    """Raw sensor data from wearable device."""
    # Heart rate from PPG sensor (beats per minute)
    heart_rate: float = Field(..., ge=0, le=300)
    heart_rate_variability: Optional[float] = None  # ms between beats

    # Oxygen saturation from pulse oximeter (percentage)
    spo2: float = Field(..., ge=0, le=100)

    # Body temperature (Celsius)
    temperature: float = Field(..., ge=20, le=45)

    # Accelerometer data for fall detection (g-force)
    accel_x: float = 0.0
    accel_y: float = 0.0
    accel_z: float = 1.0  # Normal gravity

    # Motion metrics
    step_count: int = 0
    is_moving: bool = False

    # Timestamp
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class PatientInfo(BaseModel):
    """Patient identification and baseline info."""
    patient_id: str
    device_id: str
    age: Optional[int] = None
    baseline_heart_rate: float = 70.0  # Personalized baseline
    baseline_spo2: float = 98.0
    baseline_temp: float = 36.6
    conditions: List[str] = Field(default_factory=list)  # e.g., ["diabetes", "hypertension"]


class AnomalyResult(BaseModel):
    """Result from anomaly detection model."""
    is_anomaly: bool = False
    anomaly_score: float = 0.0  # 0-1, higher = more anomalous
    anomaly_type: Optional[str] = None  # "bradycardia", "hypoxia", etc.
    confidence: float = 0.0
    inference_time_ms: float = 0.0
    model_version: str = "unknown"


class HealthAlert(BaseModel):
    """Health alert to be sent to caregivers/medical staff."""
    alert_id: str
    patient_id: str
    device_id: str
    severity: AlertSeverity
    alert_type: str  # "heart_rate_anomaly", "low_spo2", "fall_detected"
    message: str
    vital_readings: Dict[str, float]
    anomaly_result: Optional[AnomalyResult] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    synced: bool = False


class VitalMonitoringState(BaseModel):
    """
    Workflow state for vital signs monitoring.

    This state is used by the VitalMonitoring workflow to track
    sensor readings, anomaly detection, and alerting.
    """
    # Patient info
    patient_id: str
    device_id: str
    patient_info: Optional[PatientInfo] = None

    # Current sensor readings
    sensor_data: Optional[SensorData] = None

    # Processed features (for model input)
    features: Optional[List[float]] = None

    # Anomaly detection result
    anomaly_result: Optional[AnomalyResult] = None

    # Alert if generated
    alert: Optional[HealthAlert] = None
    alert_sent: bool = False

    # Status tracking
    status: str = "pending"  # pending, monitoring, alerting, completed
    error_message: Optional[str] = None

    # Sync status for offline operation
    requires_sync: bool = False
    synced_at: Optional[datetime] = None

    # Thresholds (from config or defaults)
    heart_rate_min: float = 50.0
    heart_rate_max: float = 120.0
    spo2_min: float = 90.0
    temp_min: float = 35.0
    temp_max: float = 38.5
    anomaly_threshold: float = 0.7

    # Workflow metadata
    workflow_started_at: datetime = Field(default_factory=datetime.utcnow)
    workflow_completed_at: Optional[datetime] = None

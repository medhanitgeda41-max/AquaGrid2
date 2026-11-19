"""Pure Python statistical and hydraulic sensor cross-check engine.

Detects flatline (near-zero variance), drift against spatial neighbours,
physically impossible bounds, abnormal rate-of-change, and hydraulic mass balance
(pressure drop + flow rise = genuine leak; pressure drop + normal flow = sensor fault).
"""
import math
from typing import Sequence


def check_flatline(values: Sequence[float], threshold: float = 0.01) -> bool:
    """
    Check if a series of recent sensor readings has flatlined (near-zero variance).
    
    Returns:
        True if the sensor is flatlined (faulty), False otherwise.
    """
    if len(values) < 3:
        return False

    val_range = max(values) - min(values)
    if val_range < threshold:
        return True

    # Also check sample variance
    n = len(values)
    mean = sum(values) / n
    variance = sum((x - mean) ** 2 for x in values) / (n - 1)
    return variance < (threshold ** 2)


def check_drift(sensor_val: float, neighbor_vals: Sequence[float], max_deviation: float = 2.0) -> bool:
    """
    Check if a sensor has drifted away from spatial neighbours or redundant sensors.
    
    Returns:
        True if sensor reading exhibits anomalous drift, False otherwise.
    """
    if not neighbor_vals:
        return False

    neighbor_avg = sum(neighbor_vals) / len(neighbor_vals)
    delta = abs(sensor_val - neighbor_avg)
    return delta > max_deviation


def check_bounds(val: float, min_val: float = 0.0, max_val: float = 150.0) -> bool:
    """
    Check if a reading falls outside physically possible limits.
    
    Returns:
        True if the value is within physical bounds, False if impossible (e.g. negative pressure).
    """
    if math.isnan(val) or math.isinf(val):
        return False
    return min_val <= val <= max_val


def check_rate_of_change(val_t1: float, val_t2: float, dt_hours: float = 1.0, max_roc: float = 35.0) -> bool:
    """
    Check if rate of change between consecutive readings exceeds physical capability.
    
    Returns:
        True if rate of change is normal, False if anomalous spike/step.
    """
    if dt_hours <= 0:
        return True
    roc = abs(val_t2 - val_t1) / dt_hours
    return roc <= max_roc


def check_mass_balance(pressure_delta: float, flow_delta: float) -> str:
    """
    Hydraulic mass-balance diagnostic correlation.
    
    In a pressurized water network:
    - Genuine Pipe Leak: Pipe wall rupture causes a sudden localized pressure drop
      coupled with a significant flow velocity increase into the ruptured sector.
      (Pressure Drop < -5 psi AND Flow Spike > +15 L/s)
    - Sensor Fault: If pressure drops while flow remains normal or decreases,
      the anomaly is an electrical/transducer fault, NOT a physical rupture.
      
    Returns:
        'LEAK_CONFIRMED' | 'SENSOR_FAULT' | 'HIGH_DEMAND' | 'NORMAL'
    """
    is_pressure_drop = pressure_delta < -8.0
    is_flow_rise = flow_delta > 20.0

    if is_pressure_drop and is_flow_rise:
        return "LEAK_CONFIRMED"
    elif is_pressure_drop and not is_flow_rise:
        return "SENSOR_FAULT"
    elif not is_pressure_drop and is_flow_rise:
        return "HIGH_DEMAND"
    else:
        return "NORMAL"

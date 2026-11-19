"""Unit tests for sensor cross-checks and hydraulic mass-balance rules."""
from guards.sensor_checks import (
    check_flatline,
    check_drift,
    check_bounds,
    check_rate_of_change,
    check_mass_balance,
)


def test_flatline_detection_flags_p17():
    # P-17 flatline values across 4 timestamps
    flatlined_series = [48.12, 48.12, 48.12, 48.12]
    assert check_flatline(flatlined_series, threshold=0.01) is True

    # Natural sensor noise should not be flagged as flatline
    normal_series = [48.12, 48.35, 47.95, 48.20]
    assert check_flatline(normal_series, threshold=0.01) is False


def test_drift_detection_flags_intake_sensor():
    # Redundant intake sensors: T-INTAKE-2 drifting high vs neighbours
    sensor_val = 4.85
    neighbor_vals = [1.20, 1.30, 1.25]
    assert check_drift(sensor_val, neighbor_vals, max_deviation=2.0) is True

    # Normal synchronized reading
    normal_sensor = 1.35
    assert check_drift(normal_sensor, neighbor_vals, max_deviation=2.0) is False


def test_bounds_detection_flags_impossible_values():
    # Negative pressure is physically impossible in positive-pressure distribution
    assert check_bounds(-4.5, min_val=0.0, max_val=150.0) is False
    assert check_bounds(55.0, min_val=0.0, max_val=150.0) is True
    assert check_bounds(210.0, min_val=0.0, max_val=150.0) is False


def test_rate_of_change_check():
    # Extreme spike of 60 psi in 1 hour
    assert check_rate_of_change(val_t1=50.0, val_t2=115.0, dt_hours=1.0, max_roc=35.0) is False
    # Normal transition
    assert check_rate_of_change(val_t1=50.0, val_t2=58.0, dt_hours=1.0, max_roc=35.0) is True


def test_mass_balance_leak_vs_sensor_fault():
    # Case 1: Pipe Leak (Pressure drops AND Flow spikes)
    res_leak = check_mass_balance(pressure_delta=-18.5, flow_delta=45.0)
    assert res_leak == "LEAK_CONFIRMED"

    # Case 2: Broken Pressure Sensor (Pressure drops but Flow is normal)
    res_fault = check_mass_balance(pressure_delta=-18.5, flow_delta=1.5)
    assert res_fault == "SENSOR_FAULT"

    # Case 3: High Demand (Pressure stable/mild drop, Flow high)
    res_demand = check_mass_balance(pressure_delta=-2.0, flow_delta=30.0)
    assert res_demand == "HIGH_DEMAND"

    # Case 4: Normal operation
    res_norm = check_mass_balance(pressure_delta=0.5, flow_delta=-1.0)
    assert res_norm == "NORMAL"

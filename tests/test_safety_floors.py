"""Unit tests for the 35% reservoir floor and water quality derating guards."""
from guards.safety_floors import (
    simulate_reservoir_trajectory,
    evaluate_quality_and_bloom_derating,
)
from config.constants import RESERVOIR_TOTAL_CAPACITY_ML, RESERVOIR_FLOOR_PERCENT


def test_reservoir_floor_blocks_aggressive_throttle():
    # Strategic reservoir starts at 48% (240 ML)
    current_vol = 240.0
    # Peak tariff throttle proposed: drop production to 20 MLD
    throttled_inflow_mld = 20.0
    # High afternoon/evening demand forecast (average 95 MLD across 24 hours)
    demands_mld = [95.0] * 24

    res = simulate_reservoir_trajectory(
        current_volume_ml=current_vol,
        plant_inflow_mld=throttled_inflow_mld,
        demand_forecast_mld=demands_mld,
        total_capacity_ml=RESERVOIR_TOTAL_CAPACITY_ML,
        min_floor_percent=RESERVOIR_FLOOR_PERCENT,
    )

    # Must fail safety check
    assert res["is_safe"] is False
    # Minimum level reached must dip below 35% floor (175 ML)
    assert res["min_level_percent"] < 35.0
    assert res["min_volume_ml"] < 175.0
    assert res["breach_hour"] is not None
    assert "SAFETY FLOOR BREACH" in res["reason"]


def test_reservoir_floor_allows_safe_production():
    # Reservoir starts at 48% (240 ML)
    current_vol = 240.0
    # Maintain baseline production of 100 MLD
    safe_inflow_mld = 100.0
    # Moderate demand forecast of 85 MLD
    demands_mld = [85.0] * 12

    res = simulate_reservoir_trajectory(
        current_volume_ml=current_vol,
        plant_inflow_mld=safe_inflow_mld,
        demand_forecast_mld=demands_mld,
        total_capacity_ml=RESERVOIR_TOTAL_CAPACITY_ML,
        min_floor_percent=RESERVOIR_FLOOR_PERCENT,
    )

    # Must pass safety check
    assert res["is_safe"] is True
    assert res["min_level_percent"] >= 35.0
    assert res["breach_hour"] is None


def test_algal_bloom_derating_factors():
    # Critical bloom at Intake 2 isolates Intake 2 and caps plant at 50% (60 MLD)
    crit = evaluate_quality_and_bloom_derating(turbidity_ntu=1.2, chlorine_ppm=2.0, bloom_severity="CRITICAL")
    assert crit["derating_factor"] == 0.50
    assert crit["max_safe_output_mld"] == 60.0

    # Moderate bloom cuts capacity to 50% (60 MLD)
    mod = evaluate_quality_and_bloom_derating(turbidity_ntu=1.5, chlorine_ppm=2.2, bloom_severity="MODERATE")
    assert mod["derating_factor"] == 0.50
    assert mod["max_safe_output_mld"] == 60.0

    # Normal conditions allow full 120 MLD
    norm = evaluate_quality_and_bloom_derating(turbidity_ntu=1.0, chlorine_ppm=2.0, bloom_severity="NONE")
    assert norm["derating_factor"] == 1.0
    assert norm["max_safe_output_mld"] == 120.0


def test_water_quality_limits_detect_potable_breaches():
    # High turbidity (e.g. 5.2 NTU > 4.0 NTU limit)
    res_turb = evaluate_quality_and_bloom_derating(turbidity_ntu=5.2, chlorine_ppm=2.0)
    assert res_turb["is_quality_safe"] is False
    assert any("Turbidity" in v for v in res_turb["violations"])

    # Low chlorine (< 0.5 ppm)
    res_cl = evaluate_quality_and_bloom_derating(turbidity_ntu=1.0, chlorine_ppm=0.2)
    assert res_cl["is_quality_safe"] is False
    assert any("Chlorine" in v for v in res_cl["violations"])

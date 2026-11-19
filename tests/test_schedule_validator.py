"""Unit tests for the pure-Python production schedule validator."""
from guards.schedule_validator import validate_production_schedule


def _baseline_demand_24h() -> dict[int, float]:
    """Representative 24-hour baseline town water demand (MLD)."""
    demands = {}
    for h in range(24):
        if 0 <= h < 6:
            demands[h] = 47.0
        elif 6 <= h < 14:
            demands[h] = 88.0
        elif 14 <= h < 19:
            demands[h] = 92.0
        else:
            demands[h] = 65.0
    return demands


def test_valid_schedule_passes_all_guards():
    schedule = (
        "00:00-06:00 at 110 MLD (off-peak $0.09/kWh), "
        "06:00-14:00 at 95 MLD, "
        "14:00-18:00 at 60 MLD (peak $0.48/kWh), "
        "19:00-24:00 at 85 MLD."
    )
    res = validate_production_schedule(
        proposed_schedule=schedule,
        current_volume_ml=240.0,  # 48%
        demand_by_hour=_baseline_demand_24h(),
        bloom_severity="NONE",
    )
    assert res["status"] == "VALID"
    assert res["is_valid"] is True
    assert len(res["blocks"]) == 4
    assert len(res["rejected_blocks"]) == 0
    assert all(b["status"] == "VALID" for b in res["blocks"])


def test_rejects_block_exceeding_desal_max_capacity():
    """Block '14:00-18:00 at 351 MLD' exceeds DESAL_MAX_CAPACITY_MLD (120 MLD)."""
    schedule = "00:00-06:00 at 90 MLD, 14:00-18:00 at 351 MLD."
    res = validate_production_schedule(
        proposed_schedule=schedule,
        current_volume_ml=240.0,
        demand_by_hour=_baseline_demand_24h(),
        bloom_severity="NONE",
    )
    assert res["status"] == "REJECTED_BY_CODE"
    assert res["is_valid"] is False
    assert len(res["rejected_blocks"]) == 1
    bad = res["rejected_blocks"][0]
    assert bad["window"] == "14:00-18:00"
    assert bad["status"] == "REJECTED_BY_CODE"
    assert any("120.0 MLD" in r for r in bad["reasons"])


def test_rejects_block_exceeding_algal_bloom_derating_limit():
    """MODERATE bloom derates max capacity to 60 MLD; 90 MLD block must be REJECTED_BY_CODE."""
    schedule = "00:00-06:00 at 50 MLD, 14:00-18:00 at 90 MLD."
    res = validate_production_schedule(
        proposed_schedule=schedule,
        current_volume_ml=240.0,
        demand_by_hour=_baseline_demand_24h(),
        bloom_severity="MODERATE",
    )
    assert res["status"] == "REJECTED_BY_CODE"
    assert res["bloom_max_safe_mld"] == 60.0
    assert len(res["rejected_blocks"]) == 1
    bad = res["rejected_blocks"][0]
    assert bad["window"] == "14:00-18:00"
    assert any("algal bloom derating" in r.lower() for r in bad["reasons"])


def test_rejects_block_breaching_35_percent_reservoir_floor():
    """Scenario 2 demand (351 MLD over 14:00-19:00) with 15 MLD throttle breaches 35% floor (31.2%)."""
    demand = _baseline_demand_24h()
    for h in range(14, 20):
        demand[h] = 351.0

    schedule = "00:00-06:00 at 110 MLD, 14:00-18:00 at 15 MLD."
    res = validate_production_schedule(
        proposed_schedule=schedule,
        current_volume_ml=240.0,  # 48%
        demand_by_hour=demand,
        bloom_severity="NONE",
    )
    assert res["status"] == "REJECTED_BY_CODE"
    assert len(res["rejected_blocks"]) == 1
    bad = res["rejected_blocks"][0]
    assert bad["window"] == "14:00-18:00"
    assert bad["min_projected_percent"] < 35.0
    assert any("SAFETY FLOOR BREACH" in r and "35.0%" in r for r in bad["reasons"])


def test_rejects_unparseable_vague_schedule():
    res = validate_production_schedule(
        proposed_schedule="Run desalination plant during off-peak hours to save money.",
        current_volume_ml=240.0,
        demand_by_hour=_baseline_demand_24h(),
    )
    assert res["status"] == "REJECTED_BY_CODE"
    assert res["is_valid"] is False
    assert len(res["rejected_blocks"]) == 1


def test_critical_bloom_caps_schedule_at_60_mld_not_zero():
    """CRITICAL bloom at Intake 2 caps output at 50% (60 MLD): 60 MLD passes while 80 MLD is REJECTED_BY_CODE."""
    schedule = "00:00-06:00 at 60 MLD, 14:00-18:00 at 80 MLD."
    res = validate_production_schedule(
        proposed_schedule=schedule,
        current_volume_ml=240.0,
        demand_by_hour=_baseline_demand_24h(),
        bloom_severity="CRITICAL",
    )
    assert res["bloom_max_safe_mld"] == 60.0
    assert res["status"] == "REJECTED_BY_CODE"
    assert res["blocks"][0]["window"] == "00:00-06:00"
    assert res["blocks"][0]["status"] == "VALID"
    assert res["blocks"][1]["window"] == "14:00-18:00"
    assert res["blocks"][1]["status"] == "REJECTED_BY_CODE"
    assert any("60.0 MLD" in r for r in res["blocks"][1]["reasons"])

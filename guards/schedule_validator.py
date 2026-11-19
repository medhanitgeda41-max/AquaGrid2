"""Pure Python deterministic validator for LLM-proposed desalination schedules.

Parses time-blocked production schedules (e.g., "00:00-06:00 at 110 MLD, 14:00-18:00 at 60 MLD")
and validates every block against three non-negotiable physical & safety constraints:
1. Physical desalination plant capacity (0 <= output_mld <= DESAL_MAX_CAPACITY_MLD = 120.0 MLD).
2. Water quality & algal-bloom capacity derating limit.
3. Mandatory 35% strategic reservoir storage floor via simulate_reservoir_trajectory().

Any violating block is deterministically flagged as 'REJECTED_BY_CODE' with explicit reasons.
"""
import re
from typing import Mapping, Sequence, Union
from config.constants import (
    DESAL_MAX_CAPACITY_MLD,
    RESERVOIR_FLOOR_PERCENT,
    RESERVOIR_TOTAL_CAPACITY_ML,
)
from guards.safety_floors import (
    evaluate_quality_and_bloom_derating,
    simulate_reservoir_trajectory,
)

# Matches blocks like:
#   "00:00-06:00 at 110 MLD"
#   "14:00-18:00 throttle proposal to 15 MLD"
#   "14:00-18:00 (peak $0.48/kWh): 60 MLD"
_SCHEDULE_BLOCK_RE = re.compile(
    r"(?P<start>\d{1,2}):\d{2}\s*(?:-|–|—|to)\s*(?P<end>\d{1,2}):\d{2}"
    r"[^,;\n]*?"
    r"(?P<mld>-?\d+(?:\.\d+)?)\s*MLD",
    re.IGNORECASE,
)


def parse_schedule_blocks(schedule: Union[str, Sequence[dict]]) -> list[dict]:
    """Extract normalized schedule blocks from an LLM schedule string or list of dicts."""
    if isinstance(schedule, (list, tuple)):
        parsed = []
        for item in schedule:
            if not isinstance(item, dict):
                continue
            start_h = int(item.get("start_hour", 0))
            end_h = int(item.get("end_hour", 24))
            mld = float(item.get("output_mld", item.get("proposed_mld", 0.0)))
            parsed.append({
                "window": f"{start_h:02d}:00-{end_h:02d}:00",
                "start_hour": start_h,
                "end_hour": end_h,
                "proposed_mld": mld,
            })
        return parsed

    if not isinstance(schedule, str) or not schedule.strip():
        return []

    blocks = []
    for match in _SCHEDULE_BLOCK_RE.finditer(schedule):
        start_h = int(match.group("start"))
        end_h = int(match.group("end"))
        mld = float(match.group("mld"))
        blocks.append({
            "window": f"{start_h:02d}:00-{end_h:02d}:00",
            "start_hour": start_h,
            "end_hour": end_h,
            "proposed_mld": mld,
        })
    return blocks


def _build_block_demand_series(
    start_hour: int,
    end_hour: int,
    demand_by_hour: Mapping[int, float] | None,
    fallback_demand_mld: Sequence[float] | None,
    min_horizon_hours: int = 6,
) -> list[float]:
    """Construct hourly demand series for a block (at least min_horizon_hours for safety lookahead)."""
    duration = (end_hour - start_hour) if end_hour > start_hour else ((24 - start_hour) + end_hour)
    duration = max(duration, 1)
    sim_hours = max(duration, min_horizon_hours)

    if demand_by_hour:
        default_val = sum(demand_by_hour.values()) / max(len(demand_by_hour), 1)
        return [
            float(demand_by_hour.get((start_hour + offset) % 24, default_val))
            for offset in range(sim_hours)
        ]

    if fallback_demand_mld:
        seq = [float(x) for x in fallback_demand_mld]
        if len(seq) >= sim_hours:
            return seq[:sim_hours]
        return seq + [seq[-1]] * (sim_hours - len(seq))

    return [85.0] * sim_hours


def validate_production_schedule(
    proposed_schedule: Union[str, Sequence[dict]],
    current_volume_ml: float,
    demand_by_hour: Mapping[int, float] | None = None,
    fallback_demand_mld: Sequence[float] | None = None,
    bloom_severity: str = "NONE",
    turbidity_ntu: float = 1.2,
    chlorine_ppm: float = 1.8,
    max_capacity_mld: float = DESAL_MAX_CAPACITY_MLD,
    total_capacity_ml: float = RESERVOIR_TOTAL_CAPACITY_ML,
    min_floor_percent: float = RESERVOIR_FLOOR_PERCENT,
) -> dict:
    """
    Validate every time block of an LLM-proposed production schedule in pure Python.

    Checks each block against:
      1. Physical capacity bounds: 0.0 <= proposed_mld <= max_capacity_mld (120.0 MLD).
      2. Algal-bloom capacity derating limit via evaluate_quality_and_bloom_derating().
      3. 35% reservoir floor via simulate_reservoir_trajectory().

    Returns:
        dict with keys:
          - 'status': 'VALID' or 'REJECTED_BY_CODE'
          - 'is_valid': bool
          - 'max_capacity_mld': float
          - 'bloom_severity': str
          - 'bloom_max_safe_mld': float
          - 'blocks': list[dict] (each has status 'VALID' or 'REJECTED_BY_CODE' and 'reasons')
          - 'rejected_blocks': list[dict]
          - 'summary': str
    """
    derating = evaluate_quality_and_bloom_derating(
        turbidity_ntu=turbidity_ntu,
        chlorine_ppm=chlorine_ppm,
        bloom_severity=bloom_severity,
    )
    bloom_max_mld = float(derating["max_safe_output_mld"])
    normalized_bloom = derating["bloom_severity"]

    parsed_blocks = parse_schedule_blocks(proposed_schedule)
    if not parsed_blocks:
        reason = "No parseable hour-range and MLD blocks found in proposed_schedule."
        return {
            "status": "REJECTED_BY_CODE",
            "is_valid": False,
            "max_capacity_mld": max_capacity_mld,
            "bloom_severity": normalized_bloom,
            "bloom_max_safe_mld": bloom_max_mld,
            "blocks": [],
            "rejected_blocks": [
                {
                    "window": "UNPARSEABLE",
                    "proposed_mld": None,
                    "status": "REJECTED_BY_CODE",
                    "reasons": [reason],
                    "min_projected_percent": None,
                }
            ],
            "summary": f"REJECTED_BY_CODE: {reason}",
        }

    validated_blocks = []
    rejected_blocks = []

    for block in parsed_blocks:
        start_h = block["start_hour"]
        end_h = block["end_hour"]
        mld = block["proposed_mld"]
        reasons: list[str] = []

        # 1. Physical plant capacity check
        if mld < 0.0:
            reasons.append(f"Proposed output {mld:.1f} MLD cannot be negative.")
        elif mld > max_capacity_mld:
            reasons.append(
                f"Proposed output {mld:.1f} MLD exceeds DESAL-01 max capacity of {max_capacity_mld:.1f} MLD."
            )

        # 2. Algal bloom derating check
        if normalized_bloom != "NONE" and mld > bloom_max_mld:
            reasons.append(
                f"Proposed output {mld:.1f} MLD exceeds {normalized_bloom} algal bloom derating limit "
                f"of {bloom_max_mld:.1f} MLD (derating factor {derating['derating_factor']:.0%})."
            )

        # 3. 35% reservoir floor trajectory simulation (clamped to physical max if over-capacity so floor check is honest)
        effective_inflow = min(max(mld, 0.0), max_capacity_mld, bloom_max_mld if normalized_bloom != "NONE" else max_capacity_mld)
        block_demands = _build_block_demand_series(
            start_hour=start_h,
            end_hour=end_h,
            demand_by_hour=demand_by_hour,
            fallback_demand_mld=fallback_demand_mld,
        )
        # Simulate with the actual proposed value (capped at physical max so an impossible 351 MLD doesn't hide a deficit)
        sim_inflow = min(max(mld, 0.0), max_capacity_mld)
        sim = simulate_reservoir_trajectory(
            current_volume_ml=current_volume_ml,
            plant_inflow_mld=sim_inflow,
            demand_forecast_mld=block_demands,
            total_capacity_ml=total_capacity_ml,
            min_floor_percent=min_floor_percent,
        )
        if not sim["is_safe"]:
            reasons.append(sim["reason"])

        block_status = "REJECTED_BY_CODE" if reasons else "VALID"
        entry = {
            "window": block["window"],
            "start_hour": start_h,
            "end_hour": end_h,
            "proposed_mld": mld,
            "status": block_status,
            "reasons": reasons,
            "min_projected_percent": sim["min_level_percent"],
            "effective_capped_mld": effective_inflow,
        }
        validated_blocks.append(entry)
        if block_status == "REJECTED_BY_CODE":
            rejected_blocks.append(entry)

    is_valid = len(rejected_blocks) == 0
    overall_status = "VALID" if is_valid else "REJECTED_BY_CODE"
    if is_valid:
        summary = f"VALID: All {len(validated_blocks)} schedule block(s) passed capacity, bloom derating, and 35% reservoir floor checks."
    else:
        summary = (
            f"REJECTED_BY_CODE: {len(rejected_blocks)} of {len(validated_blocks)} schedule block(s) "
            f"violated physical or safety constraints."
        )

    return {
        "status": overall_status,
        "is_valid": is_valid,
        "max_capacity_mld": max_capacity_mld,
        "bloom_severity": normalized_bloom,
        "bloom_max_safe_mld": bloom_max_mld,
        "blocks": validated_blocks,
        "rejected_blocks": rejected_blocks,
        "summary": summary,
    }

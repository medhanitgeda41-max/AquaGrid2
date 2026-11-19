"""Tool 2 (Read-Only): Electricity Tariff & Water Quality Feed Service.

Queries time-of-use electricity tariffs, urban water demand forecasts,
reservoir levels, and incoming text advisories. Passes all incoming text through
the pure Python regex injection filter before presenting data to the agent.
"""
from typing import Optional
from config.constants import DEFAULT_SCADA_HOUR
from database.connection import get_db_connection, transaction_scope
from guards.injection_filter import sanitize_text, QUARANTINED_ALERT_PLACEHOLDER
from guards.safety_floors import evaluate_quality_and_bloom_derating


def read_tariff_and_quality_feeds(
    horizon_hours: int = 6,
    current_hour: int = DEFAULT_SCADA_HOUR,
    db_path: Optional[str] = None,
    log_audit: bool = False,
) -> dict:
    """
    Read time-of-use tariffs, demand forecasts, and water quality alerts.

    All incoming operator text, field messages, and sensor feeds are sanitized
    against prompt-injection patterns before returning to the LLM agent.

    Args:
        horizon_hours: Number of forward-looking hours to inspect (default: 6).
        db_path: Optional database path override.

    Returns:
        Structured dict containing sanitized feeds, tariff windows, and capacity deratings.
    """
    conn = get_db_connection(db_path)
    try:
        # Use the requested operational hour (defaults to DEFAULT_SCADA_HOUR = 14)
        # 1. Fetch upcoming Tariffs for the requested horizon
        end_hour = min(23, current_hour + horizon_hours)
        tariff_rows = conn.execute(
            """
            SELECT hour, rate_per_kwh, is_peak
            FROM tariffs
            WHERE hour >= ? AND hour <= ?
            ORDER BY hour ASC;
            """,
            (current_hour, end_hour),
        ).fetchall()

        tariff_schedule = [
            {
                "hour": r["hour"],
                "rate_per_kwh": r["rate_per_kwh"],
                "is_peak": bool(r["is_peak"]),
            }
            for r in tariff_rows
        ]
        is_current_peak = any(t["is_peak"] for t in tariff_schedule if t["hour"] == current_hour)

        # 2. Fetch Demand Forecast for the requested horizon
        demand_rows = conn.execute(
            """
            SELECT hour, demand_mld
            FROM demand_forecast
            WHERE hour >= ? AND hour <= ?
            ORDER BY hour ASC;
            """,
            (current_hour, end_hour),
        ).fetchall()

        demand_forecast = [
            {"hour": r["hour"], "demand_mld": r["demand_mld"]}
            for r in demand_rows
        ]

        # 2b. Compute full 24h tariff & demand window summary so the agent can schedule across the whole day
        window_defs = [
            ("00:00-06:00", "off_peak", 0, 5),
            ("06:00-14:00", "mid_peak", 6, 13),
            ("14:00-18:00", "peak", 14, 18),
            ("19:00-24:00", "evening_mid_peak", 19, 23),
        ]
        daily_windows = []
        for label, tier, start_h, end_h in window_defs:
            row = conn.execute(
                """
                SELECT
                    ROUND(AVG(t.rate_per_kwh), 3) AS avg_rate,
                    ROUND(AVG(d.demand_mld), 1) AS avg_demand_mld
                FROM tariffs t
                JOIN demand_forecast d ON t.hour = d.hour
                WHERE t.hour >= ? AND t.hour <= ?;
                """,
                (start_h, end_h),
            ).fetchone()
            if row and row["avg_rate"] is not None:
                daily_windows.append({
                    "window": label,
                    "tier": tier,
                    "avg_rate_per_kwh": row["avg_rate"],
                    "avg_demand_mld": row["avg_demand_mld"],
                })

        # 2c. Full 24h hourly demand map for deterministic schedule validation
        all_demand_rows = conn.execute(
            "SELECT hour, demand_mld FROM demand_forecast ORDER BY hour ASC;"
        ).fetchall()
        hourly_demand_24h = {int(r["hour"]): float(r["demand_mld"]) for r in all_demand_rows}

        # 3. Fetch Current Reservoir Status
        res_row = conn.execute("SELECT * FROM reservoirs WHERE id = 'RES-01';").fetchone()
        reservoir_status = {
            "reservoir_id": res_row["id"],
            "name": res_row["name"],
            "capacity_ml": res_row["capacity_ml"],
            "current_volume_ml": res_row["volume_ml"],
            "current_level_percent": res_row["level_percent"],
            "safety_floor_percent": 35.0,
            "safety_floor_volume_ml": res_row["capacity_ml"] * 0.35,
        }

        # 4. Fetch Quality Alerts & Apply Prompt Injection Filter
        alert_rows = conn.execute(
            """
            SELECT id, timestamp, severity, location, raw_text, is_injection
            FROM quality_alerts
            ORDER BY id DESC
            LIMIT 10;
            """
        ).fetchall()

        sanitized_alerts = []
        bloom_detected = False
        highest_bloom_severity = "NONE"

        for a in alert_rows:
            raw = a["raw_text"]
            # Layer 0: Deterministic pure Python regex sanitization
            is_inj, cleaned = sanitize_text(raw)
            flagged = is_inj or bool(a["is_injection"])

            if flagged:
                # Quarantine the ENTIRE alert text: pass only placeholder + metadata (id, source, severity)
                sanitized_alerts.append({
                    "alert_id": a["id"],
                    "source": a["location"],
                    "severity": a["severity"],
                    "text": QUARANTINED_ALERT_PLACEHOLDER,
                    "injection_detected": True,
                })
                continue

            if "algal bloom" in raw.lower() or "bloom" in raw.lower():
                bloom_detected = True
                if a["severity"].upper() in ("CRITICAL", "MODERATE", "LOW"):
                    highest_bloom_severity = a["severity"].upper()

            sanitized_alerts.append({
                "alert_id": a["id"],
                "timestamp": a["timestamp"],
                "severity": a["severity"],
                "source": a["location"],
                "location": a["location"],
                "text": cleaned,
                "injection_detected": False,
            })

        # 5. Fetch Latest Intake Water Quality Telemetry
        turbidity_row = conn.execute(
            "SELECT value FROM telemetry WHERE sensor_id = 'T-INTAKE-1' AND hour = ?;",
            (current_hour,),
        ).fetchone()
        chlorine_row = conn.execute(
            "SELECT value FROM telemetry WHERE sensor_id = 'CL-INTAKE-1' AND hour = ?;",
            (current_hour,),
        ).fetchone()

        curr_turbidity = float(turbidity_row["value"]) if turbidity_row else 1.2
        curr_chlorine = float(chlorine_row["value"]) if chlorine_row else 1.8

        derating_eval = evaluate_quality_and_bloom_derating(
            turbidity_ntu=curr_turbidity,
            chlorine_ppm=curr_chlorine,
            bloom_severity=highest_bloom_severity,
        )

        result = {
            "current_hour": current_hour,
            "horizon_hours": horizon_hours,
            "is_current_peak_tariff": is_current_peak,
            "tariffs": tariff_schedule,
            "demand_forecast": demand_forecast,
            "daily_windows": daily_windows,
            "hourly_demand_24h": hourly_demand_24h,
            "reservoir": reservoir_status,
            "sanitized_alerts": sanitized_alerts,
            "water_quality": {
                "intake_turbidity_ntu": curr_turbidity,
                "intake_chlorine_ppm": curr_chlorine,
                "algal_bloom_detected": bloom_detected,
                "bloom_severity": highest_bloom_severity,
                "derating_factor": derating_eval["derating_factor"],
                "max_allowable_output_mld": derating_eval["max_safe_output_mld"],
                "is_quality_safe": derating_eval["is_quality_safe"],
                "violations": derating_eval["violations"],
            },
        }
    finally:
        conn.close()

    if log_audit:
        inj_alerts = [a for a in sanitized_alerts if a.get("injection_detected")]
        with transaction_scope(db_path) as audit_conn:
            audit_conn.execute(
                """
                INSERT INTO audit_log (event_type, target_id, details, actor, status)
                VALUES (?, ?, ?, ?, ?);
                """,
                (
                    "TOOL_CALL",
                    "read_tariff_and_quality_feeds",
                    (
                        f"Ingested {len(tariff_schedule)}h tariff/demand horizon from hour {current_hour}, "
                        f"bloom={highest_bloom_severity} (max {derating_eval['max_safe_output_mld']} MLD), "
                        f"alerts={len(sanitized_alerts)} ({len(inj_alerts)} quarantined)."
                    ),
                    "CODE_GUARD",
                    "ALLOWED",
                ),
            )
            for ia in inj_alerts:
                audit_conn.execute(
                    """
                    INSERT INTO audit_log (event_type, target_id, details, actor, status)
                    VALUES (?, ?, ?, ?, ?);
                    """,
                    (
                        "INJECTION_BLOCKED",
                        f"ALERT-{ia['alert_id']}",
                        f"Alert #{ia['alert_id']} from {ia.get('source')} ({ia.get('severity')}) fully quarantined before LLM ingestion.",
                        "CODE_GUARD",
                        "BLOCKED",
                    ),
                )

    return result

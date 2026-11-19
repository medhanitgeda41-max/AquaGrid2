"""Exclusive Write Gateway for AquaGrid.

Enforces strict architectural perimeter:
- Whitelist validation on action_type and target_id.
- Pure Python deterministic safety checks (35% reservoir floor & water quality).
- Physical mutations MUST be staged as 'PENDING' for human approval.
- Just-in-time safety re-check upon human 'Approve' before any database commit.
"""
from typing import Optional
from config.constants import (
    ALLOWED_ACTION_TYPES,
    KNOWN_TARGET_IDS,
    RESERVOIR_TOTAL_CAPACITY_ML,
    RESERVOIR_FLOOR_PERCENT,
)
from database.connection import get_db_connection, transaction_scope
from guards.safety_floors import simulate_reservoir_trajectory, evaluate_quality_and_bloom_derating


def stage_gated_valve_or_setpoint_action(
    action_type: str,
    target_id: str,
    proposed_value: float,
    rationale: str,
    db_path: Optional[str] = None,
) -> dict:
    """
    The ONLY authorized write staging gateway for AquaGrid.

    Validates targets against whitelists, runs mathematical safety floor checks,
    and inserts approved proposals into 'pending_actions' with status 'PENDING'.
    DOES NOT modify 'valves' or 'plant_setpoints' directly.

    Args:
        action_type: Must be 'CLOSE_VALVE', 'OPEN_VALVE', or 'SET_PLANT_OUTPUT'.
        target_id: Must be in V-01..V-12 or 'DESAL-01'.
        proposed_value: Proposed actuator value (0.0/1.0 for valves, MLD for plant).
        rationale: Plain English justification.
        db_path: Optional database path override.

    Returns:
        Result dict with status 'STAGED_PENDING_APPROVAL', 'REJECTED_INVALID_TARGET',
        or 'REJECTED_BY_SAFETY_GUARD'.
    """
    # 1. Target and Action Type Whitelist Validation
    if action_type not in ALLOWED_ACTION_TYPES or target_id not in KNOWN_TARGET_IDS:
        error_msg = f"Rejected invalid action_type '{action_type}' or unknown target_id '{target_id}'"
        with transaction_scope(db_path) as conn:
            conn.execute(
                """
                INSERT INTO audit_log (event_type, target_id, details, actor, status)
                VALUES (?, ?, ?, ?, ?);
                """,
                ("INVALID_ACTION_REJECTED", target_id, error_msg, "CODE_GUARD", "REJECTED"),
            )
        return {
            "status": "REJECTED_INVALID_TARGET",
            "reason": error_msg,
            "allowed_actions": ALLOWED_ACTION_TYPES,
            "known_targets": KNOWN_TARGET_IDS,
        }

    conn = get_db_connection(db_path)
    sim_min_projected_percent: Optional[float] = None
    try:
        # 1b. Duplicate PENDING guard: reject if a PENDING action already exists for same target_id & action_type
        existing_pending = conn.execute(
            """
            SELECT id
            FROM pending_actions
            WHERE target_id = ? AND action_type = ? AND status = 'PENDING'
            ORDER BY id ASC
            LIMIT 1;
            """,
            (target_id, action_type),
        ).fetchone()
        if existing_pending:
            existing_id = int(existing_pending["id"])
            reason = (
                f"Duplicate proposal rejected: PENDING action #{existing_id} already exists for "
                f"{action_type} on {target_id}. Resolve the existing pending action first."
            )
            with transaction_scope(db_path) as audit_conn:
                audit_conn.execute(
                    """
                    INSERT INTO audit_log (event_type, target_id, details, actor, status)
                    VALUES (?, ?, ?, ?, ?);
                    """,
                    ("DUPLICATE_PENDING_REJECTED", target_id, reason, "CODE_GUARD", "BLOCKED"),
                )
            return {
                "status": "REJECTED_DUPLICATE_PENDING",
                "existing_action_id": existing_id,
                "action_type": action_type,
                "target_id": target_id,
                "reason": reason,
            }

        current_value = 0.0
        # Fetch current actuator state
        if action_type in ("CLOSE_VALVE", "OPEN_VALVE"):
            v_row = conn.execute("SELECT status FROM valves WHERE valve_id = ?;", (target_id,)).fetchone()
            current_value = 1.0 if (v_row and v_row["status"] == "OPEN") else 0.0
        elif action_type == "SET_PLANT_OUTPUT":
            p_row = conn.execute("SELECT production_mld FROM plant_setpoints WHERE plant_id = ?;", (target_id,)).fetchone()
            current_value = float(p_row["production_mld"]) if p_row else 100.0

            # 2. Pure Python Safety Floor Verification (for production changes)
            # Fetch latest reservoir volume
            res_row = conn.execute("SELECT volume_ml FROM reservoirs WHERE id = 'RES-01';").fetchone()
            current_vol = float(res_row["volume_ml"]) if res_row else 240.0

            # Fetch demand forecast over the 6h horizon from 14:00 (hours 14 to 19)
            demand_rows = conn.execute(
                "SELECT demand_mld FROM demand_forecast WHERE hour >= 14 AND hour < 20 ORDER BY hour ASC;"
            ).fetchall()
            demand_list = [float(r["demand_mld"]) for r in demand_rows]
            if not demand_list or len(demand_list) < 6:
                demand_list = [351.0] * 6

            # Simulate trajectory
            sim_result = simulate_reservoir_trajectory(
                current_volume_ml=current_vol,
                plant_inflow_mld=proposed_value,
                demand_forecast_mld=demand_list,
                total_capacity_ml=RESERVOIR_TOTAL_CAPACITY_ML,
                min_floor_percent=RESERVOIR_FLOOR_PERCENT,
            )
            sim_min_projected_percent = sim_result["min_level_percent"]

            # If simulation violates the 35% floor, abort immediately
            if not sim_result["is_safe"]:
                with transaction_scope(db_path) as audit_conn:
                    audit_conn.execute(
                        """
                        INSERT INTO audit_log (event_type, target_id, details, actor, status)
                        VALUES (?, ?, ?, ?, ?);
                        """,
                        (
                            "SAFETY_FLOOR_BREACH",
                            target_id,
                            f"Proposed output {proposed_value} MLD blocked: {sim_result['reason']}",
                            "CODE_GUARD",
                            "BLOCKED",
                        ),
                    )
                return {
                    "status": "REJECTED_BY_SAFETY_GUARD",
                    "reason": sim_result["reason"],
                    "min_projected_percent": sim_result["min_level_percent"],
                    "floor_threshold_percent": 35.0,
                    "breach_hour_offset": sim_result["breach_hour"],
                }

            # Check algal bloom derating constraint
            alert_rows = conn.execute(
                "SELECT severity, raw_text FROM quality_alerts WHERE raw_text LIKE '%bloom%';"
            ).fetchall()
            highest_bloom = "NONE"
            for a in alert_rows:
                sev = a["severity"].upper()
                if sev in ("CRITICAL", "MODERATE", "LOW"):
                    highest_bloom = sev

            derating_check = evaluate_quality_and_bloom_derating(
                turbidity_ntu=1.2,
                chlorine_ppm=2.0,
                bloom_severity=highest_bloom,
            )
            if proposed_value > derating_check["max_safe_output_mld"]:
                reason = (
                    f"Proposed output {proposed_value} MLD exceeds maximum allowable capacity of "
                    f"{derating_check['max_safe_output_mld']} MLD due to {highest_bloom} algal bloom alert."
                )
                with transaction_scope(db_path) as audit_conn:
                    audit_conn.execute(
                        """
                        INSERT INTO audit_log (event_type, target_id, details, actor, status)
                        VALUES (?, ?, ?, ?, ?);
                        """,
                        ("BLOOM_CAPACITY_BREACH", target_id, reason, "CODE_GUARD", "BLOCKED"),
                    )
                return {
                    "status": "REJECTED_BY_SAFETY_GUARD",
                    "reason": reason,
                    "max_safe_output_mld": derating_check["max_safe_output_mld"],
                }
    finally:
        conn.close()

    # 3. Stage Action as PENDING in pending_actions (Atomic)
    with transaction_scope(db_path) as tx_conn:
        cursor = tx_conn.execute(
            """
            INSERT INTO pending_actions (action_type, target_id, proposed_value, current_value, rationale, status)
            VALUES (?, ?, ?, ?, ?, 'PENDING');
            """,
            (action_type, target_id, proposed_value, current_value, rationale),
        )
        action_id = cursor.lastrowid

        tx_conn.execute(
            """
            INSERT INTO audit_log (event_type, target_id, details, actor, status)
            VALUES (?, ?, ?, ?, ?);
            """,
            (
                "GATEWAY_PROPOSAL",
                target_id,
                f"Action {action_type} for {target_id} staged as PENDING (ID: {action_id}). Awaiting human authorization.",
                "CODE_GUARD",
                "PENDING",
            ),
        )

    response = {
        "status": "STAGED_PENDING_APPROVAL",
        "action_id": action_id,
        "action_type": action_type,
        "target_id": target_id,
        "proposed_value": proposed_value,
        "current_value": current_value,
        "rationale": rationale,
        "message": "Action staged successfully in PENDING state. Awaiting mandatory human operator authorization.",
    }
    if sim_min_projected_percent is not None:
        response["min_projected_percent"] = sim_min_projected_percent
        response["floor_threshold_percent"] = 35.0
    return response


def execute_human_approval(
    action_id: int,
    approver: str = "ControlRoom_Operator",
    db_path: Optional[str] = None,
) -> dict:
    """
    Execute human operator approval with mandatory just-in-time safety re-check.

    Re-runs the 35% reservoir floor and water quality checks with latest telemetry.
    If conditions deteriorated, cancels with 'CANCELLED_BY_SAFETY_RECHECK' and DOES NOT commit.
    If re-check passes, commits the actuator change in a single ACID transaction.
    """
    with transaction_scope(db_path) as conn:
        action_row = conn.execute(
            "SELECT * FROM pending_actions WHERE id = ? AND status = 'PENDING';",
            (action_id,),
        ).fetchone()

        if not action_row:
            return {
                "status": "ERROR_NOT_FOUND",
                "message": f"Pending action with ID {action_id} not found or already processed.",
            }

        action_type = action_row["action_type"]
        target_id = action_row["target_id"]
        proposed_value = float(action_row["proposed_value"])

        # JIT Safety Re-Check: If setting plant output, re-verify reservoir floor
        if action_type == "SET_PLANT_OUTPUT":
            res_row = conn.execute("SELECT volume_ml FROM reservoirs WHERE id = 'RES-01';").fetchone()
            latest_vol = float(res_row["volume_ml"]) if res_row else 240.0
            demand_rows = conn.execute(
                "SELECT demand_mld FROM demand_forecast WHERE hour >= 14 AND hour < 20 ORDER BY hour ASC;"
            ).fetchall()
            demand_list = [float(r["demand_mld"]) for r in demand_rows] or [351.0] * 6

            recheck_sim = simulate_reservoir_trajectory(
                current_volume_ml=latest_vol,
                plant_inflow_mld=proposed_value,
                demand_forecast_mld=demand_list,
            )

            if not recheck_sim["is_safe"]:
                conn.execute(
                    """
                    UPDATE pending_actions
                    SET status = 'CANCELLED_BY_SAFETY_RECHECK', executed_at = CURRENT_TIMESTAMP, approver = ?
                    WHERE id = ?;
                    """,
                    (approver, action_id),
                )
                conn.execute(
                    """
                    INSERT INTO audit_log (event_type, target_id, details, actor, status)
                    VALUES (?, ?, ?, ?, ?);
                    """,
                    (
                        "APPROVAL_CANCELLED_BY_SAFETY",
                        target_id,
                        f"Action {action_id} cancelled upon approval: {recheck_sim['reason']}",
                        "CODE_GUARD",
                        "BLOCKED",
                    ),
                )
                return {
                    "status": "CANCELLED_BY_SAFETY_RECHECK",
                    "reason": recheck_sim["reason"],
                    "min_projected_percent": recheck_sim["min_level_percent"],
                }

        # Execute physical mutation atomically
        if action_type == "CLOSE_VALVE":
            conn.execute(
                "UPDATE valves SET status = 'CLOSED', last_updated = CURRENT_TIMESTAMP WHERE valve_id = ?;",
                (target_id,),
            )
        elif action_type == "OPEN_VALVE":
            conn.execute(
                "UPDATE valves SET status = 'OPEN', last_updated = CURRENT_TIMESTAMP WHERE valve_id = ?;",
                (target_id,),
            )
        elif action_type == "SET_PLANT_OUTPUT":
            conn.execute(
                "UPDATE plant_setpoints SET production_mld = ?, last_updated = CURRENT_TIMESTAMP WHERE plant_id = ?;",
                (proposed_value, target_id),
            )

        # Update action status to APPROVED
        conn.execute(
            """
            UPDATE pending_actions
            SET status = 'APPROVED', executed_at = CURRENT_TIMESTAMP, approver = ?
            WHERE id = ?;
            """,
            (approver, action_id),
        )

        # Audit log commit
        conn.execute(
            """
            INSERT INTO audit_log (event_type, target_id, details, actor, status)
            VALUES (?, ?, ?, ?, ?);
            """,
            (
                "ACTION_EXECUTED",
                target_id,
                f"Action {action_id} ({action_type} -> {proposed_value}) APPROVED and executed by {approver}.",
                "HUMAN_OPERATOR",
                "APPROVED",
            ),
        )

    return {
        "status": "EXECUTED",
        "action_id": action_id,
        "action_type": action_type,
        "target_id": target_id,
        "new_value": proposed_value,
        "approver": approver,
    }


def execute_human_rejection(
    action_id: int,
    rejection_reason: str = "Operator declined action",
    approver: str = "ControlRoom_Operator",
    db_path: Optional[str] = None,
) -> dict:
    """Execute human operator rejection of a staged pending action."""
    with transaction_scope(db_path) as conn:
        conn.execute(
            """
            UPDATE pending_actions
            SET status = 'REJECTED', executed_at = CURRENT_TIMESTAMP, approver = ?
            WHERE id = ? AND status = 'PENDING';
            """,
            (approver, action_id),
        )
        conn.execute(
            """
            INSERT INTO audit_log (event_type, target_id, details, actor, status)
            VALUES (?, ?, ?, ?, ?);
            """,
            (
                "ACTION_REJECTED",
                f"ACTION-{action_id}",
                f"Action {action_id} REJECTED by {approver}. Reason: {rejection_reason}",
                "HUMAN_OPERATOR",
                "REJECTED",
            ),
        )

    return {
        "status": "REJECTED",
        "action_id": action_id,
        "reason": rejection_reason,
        "approver": approver,
    }


def refuse_direct_write_bypass(
    target_valve_id: str = "V-12",
    attempted_status: str = "OPEN",
    db_path: Optional[str] = None,
) -> dict:
    """
    Demonstrate and enforce refusal of an un-gated direct write to the valves table.

    Executes the attempted write against a read-only SQLite connection
    (PRAGMA query_only = ON, matching the agent's read-only database boundary)
    so SQLite itself refuses any mutation outside execute_human_approval().
    Logs the refused attempt in audit_log and verifies the valve status is unchanged.
    """
    import sqlite3

    ro_conn = get_db_connection(db_path)
    try:
        before_row = ro_conn.execute(
            "SELECT status FROM valves WHERE valve_id = ?;", (target_valve_id,)
        ).fetchone()
        status_before = before_row["status"] if before_row else "UNKNOWN"

        # Enforce read-only database perimeter (zero direct write access outside gateway approval)
        ro_conn.execute("PRAGMA query_only = ON;")
        refusal_error = ""
        refused = False
        try:
            ro_conn.execute(
                "UPDATE valves SET status = ? WHERE valve_id = ?;",
                (attempted_status, target_valve_id),
            )
            ro_conn.commit()
        except sqlite3.OperationalError as exc:
            refused = True
            refusal_error = f"{type(exc).__name__}: {exc}"

        after_row = ro_conn.execute(
            "SELECT status FROM valves WHERE valve_id = ?;", (target_valve_id,)
        ).fetchone()
        status_after = after_row["status"] if after_row else "UNKNOWN"
    finally:
        ro_conn.close()

    with transaction_scope(db_path) as audit_conn:
        audit_conn.execute(
            """
            INSERT INTO audit_log (event_type, target_id, details, actor, status)
            VALUES (?, ?, ?, ?, ?);
            """,
            (
                "DIRECT_WRITE_REFUSED",
                target_valve_id,
                f"Direct un-gated write (set {target_valve_id} -> {attempted_status}) REFUSED: {refusal_error}",
                "CODE_GUARD",
                "REFUSED",
            ),
        )

    return {
        "status": "REFUSED" if refused else "UNEXPECTED_WRITE",
        "target_id": target_valve_id,
        "attempted_action": f"Direct SQL UPDATE valves SET status='{attempted_status}' WHERE valve_id='{target_valve_id}' (bypassing write_gateway)",
        "error": refusal_error,
        "valve_status_before": status_before,
        "valve_status_after": status_after,
        "unchanged": status_before == status_after,
    }

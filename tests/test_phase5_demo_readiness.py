"""Phase 5 Demo Readiness Tests: Audit Log Completeness, Reset Speed, Offline Resilience, Work Order Phrasing."""
import time
from unittest.mock import patch
from database.connection import get_db_connection
from database.scenarios import (
    inject_scenario_1,
    inject_scenario_2,
    inject_scenario_3,
    inject_scenario_4,
    reset_database,
)
from agent.graph import run_agent
from agent.llm_factory import generate_offline_mock_response
from tools.write_gateway import execute_human_approval, refuse_direct_write_bypass


def _force_offline(sp: str, up: str) -> tuple[dict, str]:
    return generate_offline_mock_response(sp, up), "Deterministic Offline Engine"


def test_reset_database_under_one_second():
    """Reset and re-seed must restore clean baseline in strictly < 1.0 second."""
    inject_scenario_3()
    t0 = time.perf_counter()
    reset_database()
    elapsed = time.perf_counter() - t0
    assert elapsed < 1.0, f"reset_database() took {elapsed:.3f}s (must be < 1.0s)"

    conn = get_db_connection()
    try:
        res = conn.execute("SELECT level_percent FROM reservoirs WHERE id = 'RES-01';").fetchone()
        plant = conn.execute("SELECT production_mld FROM plant_setpoints WHERE plant_id = 'DESAL-01';").fetchone()
        closed_valves = conn.execute("SELECT COUNT(*) AS cnt FROM valves WHERE status != 'OPEN';").fetchone()["cnt"]
        pending = conn.execute("SELECT COUNT(*) AS cnt FROM pending_actions WHERE status = 'PENDING';").fetchone()["cnt"]
    finally:
        conn.close()

    assert res["level_percent"] == 48.0
    assert plant["production_mld"] == 100.0
    assert closed_valves == 0
    assert pending == 0


@patch("agent.nodes.llm_client.query", side_effect=_force_offline)
def test_audit_log_records_complete_chain_across_scenarios(mock_query):
    """
    Verify audit_log captures every required event category:
    tool calls, sensor quarantines, injection blocks, LLM provider used,
    gateway decisions, direct-write refusal, and human approver.
    """
    # Scenario 1: tool calls + sensor quarantines (P-17, T-INTAKE-2) + LLM provider + gateway proposal
    reset_database()
    inject_scenario_1()
    run_agent(scenario_id=1, current_hour=14)

    conn = get_db_connection()
    try:
        events_1 = conn.execute("SELECT event_type, target_id, details, actor FROM audit_log;").fetchall()
    finally:
        conn.close()

    event_types_1 = {r["event_type"] for r in events_1}
    assert "TOOL_CALL" in event_types_1
    assert any(r["event_type"] == "TOOL_CALL" and r["target_id"] == "read_network_telemetry" for r in events_1)
    assert any(r["event_type"] == "TOOL_CALL" and r["target_id"] == "read_tariff_and_quality_feeds" for r in events_1)
    assert any(r["event_type"] == "SENSOR_QUARANTINED" and r["target_id"] == "P-17" for r in events_1)
    assert any(r["event_type"] == "SENSOR_QUARANTINED" and r["target_id"] == "T-INTAKE-2" for r in events_1)
    assert any(
        r["event_type"] == "LLM_REASONING" and "Deterministic Offline Engine" in r["details"]
        for r in events_1
    )
    assert "GATEWAY_PROPOSAL" in event_types_1

    # Scenario 2: safety floor breach + replan staging
    reset_database()
    inject_scenario_2()
    run_agent(scenario_id=2, current_hour=14)
    conn = get_db_connection()
    try:
        events_2 = conn.execute("SELECT event_type FROM audit_log;").fetchall()
    finally:
        conn.close()
    assert any(r["event_type"] == "SAFETY_FLOOR_BREACH" for r in events_2)
    assert any(r["event_type"] == "GATEWAY_PROPOSAL" for r in events_2)

    # Scenario 3: human approval logs approver signature
    reset_database()
    inject_scenario_3()
    res3 = run_agent(scenario_id=3, current_hour=14)
    action_id = res3["gateway_response"]["action_id"]
    exec_res = execute_human_approval(action_id, approver="Lead_Operator_Amina")
    assert exec_res["status"] == "EXECUTED"

    conn = get_db_connection()
    try:
        events_3 = conn.execute("SELECT event_type, details, actor FROM audit_log;").fetchall()
    finally:
        conn.close()
    assert any(
        r["event_type"] == "ACTION_EXECUTED"
        and r["actor"] == "HUMAN_OPERATOR"
        and "Lead_Operator_Amina" in r["details"]
        for r in events_3
    )

    # Scenario 4: injection block + direct write bypass refused
    reset_database()
    inject_scenario_4()
    run_agent(scenario_id=4, current_hour=14)
    refuse_direct_write_bypass(target_valve_id="V-12", attempted_status="OPEN")

    conn = get_db_connection()
    try:
        events_4 = conn.execute("SELECT event_type FROM audit_log;").fetchall()
    finally:
        conn.close()
    assert any(r["event_type"] == "INJECTION_BLOCKED" for r in events_4)
    assert any(r["event_type"] == "DIRECT_WRITE_REFUSED" for r in events_4)


@patch("agent.nodes.llm_client.query", side_effect=_force_offline)
def test_work_orders_specify_after_operator_approval_close_v12(mock_query):
    """Work orders for V-12 leak isolation must explicitly say 'after operator approval, close V-12'."""
    for sc_id, injector in ((1, inject_scenario_1), (3, inject_scenario_3)):
        reset_database()
        injector()
        res = run_agent(scenario_id=sc_id, current_hour=14)
        advisory = (res.get("maintenance_advisory") or "").lower()
        assert "after operator approval, close v-12" in advisory, (
            f"Scenario {sc_id} work order must explicitly include 'after operator approval, close V-12'. Got: {advisory}"
        )


def test_offline_mode_succeeds_when_all_providers_unreachable():
    """Simulate total network outage (every OpenAI client raises ConnectionError); agent must fall back cleanly."""
    reset_database()
    inject_scenario_1()
    with patch("agent.llm_factory.OpenAI", side_effect=ConnectionError("Network unreachable")):
        res = run_agent(scenario_id=1, current_hour=14)
    assert res["llm_provider"] == "Deterministic Offline Engine"
    assert res["status"] == "AWAITING_HUMAN_APPROVAL"
    assert res["operator_brief"]

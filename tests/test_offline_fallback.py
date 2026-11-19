"""Phase 3 — HITL Checkpoint 3 tests.

Tests the full LangGraph agent pipeline using ONLY the deterministic offline
mock engine (all remote LLM providers are bypassed via unittest.mock.patch).

Assertions:
- run_agent() returns a valid AgentState dict with required keys.
- status is one of the four terminal states.
- Scenario-specific outcomes match PLAN.md spec.
"""
import pytest
from unittest.mock import patch
from database.scenarios import (
    inject_scenario_1,
    inject_scenario_2,
    inject_scenario_3,
    inject_scenario_4,
    reset_database,
)
from agent.graph import run_agent
from agent.llm_factory import generate_offline_mock_response

TERMINAL_STATUSES = {
    "AWAITING_HUMAN_APPROVAL",
    "COMPLETED",
    "ESCALATED_TO_HUMAN",
    "ABORTED_BY_SAFETY",
}

REQUIRED_KEYS = {
    "status",
    "operator_brief",
    "agent_step_count",
    "verified_telemetry",
    "quarantined_sensors",
    "leak_alerts",
    "sanitized_alerts",
    "gateway_response",
    "llm_provider",
}


def _force_offline(system_prompt: str, user_prompt: str) -> tuple[dict, str]:
    """Replacement for llm_client.query that always uses the offline engine."""
    return generate_offline_mock_response(system_prompt, user_prompt), "Deterministic Offline Engine"


# ---------------------------------------------------------------------------
# Shared state-shape test helpers
# ---------------------------------------------------------------------------

def _assert_valid_state(result: dict) -> None:
    for key in REQUIRED_KEYS:
        assert key in result, f"Missing required key in AgentState: {key}"
    assert result["status"] in TERMINAL_STATUSES, f"Unexpected status: {result['status']}"
    assert isinstance(result["operator_brief"], str) and result["operator_brief"], \
        "operator_brief must be a non-empty string"
    assert result["agent_step_count"] >= 1, "agent_step_count must be >= 1"


# ---------------------------------------------------------------------------
# Scenario 1: Leak vs Broken Sensor
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=False)
def fresh_db():
    """Reset database before each test that uses this fixture."""
    reset_database()
    yield
    reset_database()


@patch("agent.nodes.llm_client.query", side_effect=_force_offline)
def test_scenario_1_quarantines_sensors_and_proposes_valve(mock_query, fresh_db):
    """
    Scenario 1: P-17 and T-INTAKE-2 must be quarantined.
    J-14 pipe leak must be detected.
    Agent proposes CLOSE_VALVE V-12 staged for human approval.
    """
    inject_scenario_1()
    result = run_agent(scenario_id=1, current_hour=14)

    _assert_valid_state(result)

    quarantined_ids = [s["sensor_id"] for s in result.get("quarantined_sensors", [])]
    assert "P-17" in quarantined_ids, (
        f"P-17 must be quarantined as FLATLINE. Got: {quarantined_ids}"
    )
    assert "T-INTAKE-2" in quarantined_ids, (
        f"T-INTAKE-2 must be quarantined. Got: {quarantined_ids}"
    )

    leak_junction_ids = [a["junction_id"] for a in result.get("leak_alerts", [])]
    assert "J-14" in leak_junction_ids, (
        f"J-14 pipe leak must be detected. Got: {leak_junction_ids}"
    )

    # Gateway must have staged or agent completed (offline engine proposes CLOSE_VALVE V-12)
    gw = result.get("gateway_response")
    if gw:
        assert gw.get("status") in ("STAGED_PENDING_APPROVAL", "REJECTED_BY_SAFETY_GUARD",
                                    "REJECTED_INVALID_TARGET"), \
            f"Unexpected gateway status: {gw.get('status')}"


# ---------------------------------------------------------------------------
# Scenario 2: Throttle Rejected by Safety Guard
# ---------------------------------------------------------------------------

@patch("agent.nodes.llm_client.query", side_effect=_force_offline)
def test_scenario_2_throttle_rejected_by_safety_guard(mock_query, fresh_db):
    """
    Scenario 2:
    1. Initial attempt proposes aggressive peak-tariff throttle (15.0 MLD), which
       breaches the 35% reservoir floor and is REJECTED_BY_SAFETY_GUARD.
    2. Replan proposes the highest safe output within the 50% CRITICAL Intake 2
       bloom derating cap (60.0 MLD), keeps reservoir >= 35%, and is staged as
       STAGED_PENDING_APPROVAL (status = AWAITING_HUMAN_APPROVAL).
    """
    inject_scenario_2()
    result = run_agent(scenario_id=2, current_hour=14)

    _assert_valid_state(result)

    history = result.get("proposal_history", [])
    assert len(history) >= 2, (
        f"Scenario 2 must record initial rejected throttle and safe replan. Got {len(history)} attempt(s)"
    )

    # Proposal 1: aggressive peak-tariff throttle rejected by 35% safety guard
    first_gw = history[0]["gateway_response"]
    assert first_gw.get("status") == "REJECTED_BY_SAFETY_GUARD", (
        f"Initial throttle must be rejected by safety guard. Got: {first_gw}"
    )
    assert "%" in first_gw.get("reason", ""), (
        f"Rejection reason must contain predicted reservoir %. Got: '{first_gw.get('reason')}'"
    )
    assert first_gw.get("min_projected_percent", 100.0) < 35.0, (
        f"Initial throttle min_projected_percent must be < 35.0%. Got: {first_gw.get('min_projected_percent')}"
    )

    # Proposal 2: replan to highest bloom-safe output (60 MLD) staged for human
    second_prop = history[1]["action_proposal"]
    second_gw = history[1]["gateway_response"]
    assert float(second_prop.get("proposed_value")) == 60.0, (
        f"Replan must propose 60.0 MLD (50% Intake 2 bloom cap). Got: {second_prop}"
    )
    assert second_gw.get("status") == "STAGED_PENDING_APPROVAL", (
        f"Safe 60 MLD replan must be STAGED_PENDING_APPROVAL. Got: {second_gw}"
    )
    assert second_gw.get("min_projected_percent", 0.0) >= 35.0, (
        f"Staged replan must keep reservoir >= 35.0%. Got: {second_gw.get('min_projected_percent')}"
    )
    assert result["status"] == "AWAITING_HUMAN_APPROVAL", (
        f"Final status after safe replan must be AWAITING_HUMAN_APPROVAL. Got: {result['status']}"
    )


# ---------------------------------------------------------------------------
# Scenario 3: Valve Action — HITL Approval Required
# ---------------------------------------------------------------------------

@patch("agent.nodes.llm_client.query", side_effect=_force_offline)
def test_scenario_3_valve_staged_awaiting_human(mock_query, fresh_db):
    """
    Scenario 3: Offline engine proposes CLOSE_VALVE V-12.
    Gateway must stage it as STAGED_PENDING_APPROVAL.
    Agent status must be AWAITING_HUMAN_APPROVAL.
    """
    inject_scenario_3()
    result = run_agent(scenario_id=3, current_hour=14)

    _assert_valid_state(result)

    assert result["status"] == "AWAITING_HUMAN_APPROVAL", (
        f"Scenario 3 must pause for human approval. Got: {result['status']}"
    )
    gw = result.get("gateway_response")
    assert gw is not None, "gateway_response must be set for Scenario 3"
    assert gw.get("status") == "STAGED_PENDING_APPROVAL", (
        f"V-12 closure must be staged. Got: {gw.get('status')}"
    )
    assert gw.get("target_id") == "V-12", (
        f"Target must be V-12. Got: {gw.get('target_id')}"
    )

    # Confirm Scenario 3 creates strictly ONE PENDING CLOSE_VALVE V-12 row (no duplicates)
    from database.connection import get_db_connection
    conn = get_db_connection()
    try:
        pending = conn.execute(
            "SELECT id FROM pending_actions WHERE target_id = 'V-12' AND action_type = 'CLOSE_VALVE' AND status = 'PENDING';"
        ).fetchall()
        assert len(pending) == 1, f"Expected exactly 1 PENDING CLOSE_VALVE V-12 action, got {len(pending)}"
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Scenario 4: Prompt Injection Blocked
# ---------------------------------------------------------------------------

@patch("agent.nodes.llm_client.query", side_effect=_force_offline)
def test_scenario_4_injection_blocked_no_physical_action(mock_query, fresh_db):
    """
    Scenario 4: Adversarial alert injection detected.
    sanitized_alerts must contain at least one injection_detected=True entry.
    No physical action must be staged (gateway_response is None or no STAGED result).
    """
    inject_scenario_4()
    result = run_agent(scenario_id=4, current_hour=14)

    _assert_valid_state(result)

    injection_flags = [
        a for a in result.get("sanitized_alerts", []) if a.get("injection_detected")
    ]
    assert len(injection_flags) >= 1, (
        f"At least one alert must have injection_detected=True. "
        f"Got sanitized_alerts: {result.get('sanitized_alerts')}"
    )

    # Whole alert must be quarantined: placeholder + metadata only, zero original instruction in LLM prompt
    quarantined = injection_flags[0]
    assert quarantined["text"] == "[QUARANTINED ALERT: content withheld - injection detected]"
    assert quarantined.get("alert_id") is not None
    assert quarantined.get("source") == "SCADA Gateway"
    assert quarantined.get("severity") == "CRITICAL"

    last_prompt = result.get("last_user_prompt", "")
    assert "[QUARANTINED ALERT: content withheld - injection detected]" in last_prompt
    for forbidden_fragment in ("SYSTEM OVERRIDE", "ignore safety", "open valve", "V-12", "emergency flushing"):
        assert forbidden_fragment.lower() not in last_prompt.lower(), (
            f"Leaked original instruction fragment '{forbidden_fragment}' into LLM prompt!"
        )

    # No physical mutation should be staged
    gw = result.get("gateway_response")
    if gw:
        assert gw.get("status") != "STAGED_PENDING_APPROVAL", (
            "No physical action should be staged when injection is detected"
        )

    assert result["status"] == "COMPLETED"


# ---------------------------------------------------------------------------
# Structural / Guardrail Tests
# ---------------------------------------------------------------------------

@patch("agent.nodes.llm_client.query", side_effect=_force_offline)
def test_offline_provider_name_recorded(mock_query, fresh_db):
    """llm_provider field must record 'Deterministic Offline Engine' when patched."""
    result = run_agent(scenario_id=None, current_hour=14)
    _assert_valid_state(result)
    assert result.get("llm_provider") == "Deterministic Offline Engine", (
        f"Expected 'Deterministic Offline Engine', got: {result.get('llm_provider')}"
    )


@patch("agent.nodes.llm_client.query", side_effect=_force_offline)
def test_step_count_bounded(mock_query, fresh_db):
    """agent_step_count must never exceed MAX_AGENT_STEPS (5)."""
    from config.constants import MAX_AGENT_STEPS
    result = run_agent(scenario_id=None, current_hour=14)
    _assert_valid_state(result)
    assert result.get("agent_step_count", 0) <= MAX_AGENT_STEPS, (
        f"Step count {result.get('agent_step_count')} exceeded MAX_AGENT_STEPS={MAX_AGENT_STEPS}"
    )


# ---------------------------------------------------------------------------
# HITL Security Boundary Tests (LLM Cannot Approve or Reject Physical Actions)
# ---------------------------------------------------------------------------

def test_static_guard_agent_never_references_human_approval_or_rejection():
    """
    Static guard: No Python module under agent/ may import, call, or reference
    execute_human_approval or execute_human_rejection.
    """
    import ast
    from pathlib import Path

    forbidden = {"execute_human_approval", "execute_human_rejection"}
    agent_dir = Path(__file__).resolve().parent.parent / "agent"
    py_files = list(agent_dir.rglob("*.py"))
    assert len(py_files) > 0, "Expected Python modules inside agent/"

    for py_file in py_files:
        source = py_file.read_text(encoding="utf-8")
        # 1. Raw text check (catches comments, strings, dynamic getattr/eval)
        for symbol in forbidden:
            assert symbol not in source, (
                f"Forbidden symbol '{symbol}' found in {py_file}"
            )

        # 2. AST check across imports, names, and attribute accesses
        tree = ast.parse(source, filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    assert alias.name not in forbidden, (
                        f"Forbidden import '{alias.name}' in {py_file}"
                    )
            elif isinstance(node, ast.Name):
                assert node.id not in forbidden, (
                    f"Forbidden name reference '{node.id}' in {py_file}"
                )
            elif isinstance(node, ast.Attribute):
                assert node.attr not in forbidden, (
                    f"Forbidden attribute access '{node.attr}' in {py_file}"
                )


def test_runtime_spy_human_approval_never_called_and_actuators_unchanged(fresh_db):
    """
    Runtime spy: Across all 4 scenarios, running the agent must never call
    execute_human_approval or execute_human_rejection (call_count == 0), and
    neither valves nor plant_setpoints may be mutated in SQLite.
    """
    from unittest.mock import MagicMock
    from database.connection import get_db_connection
    import tools.write_gateway as wg

    injectors = {
        1: inject_scenario_1,
        2: inject_scenario_2,
        3: inject_scenario_3,
        4: inject_scenario_4,
    }

    def _snapshot_actuators() -> tuple[dict[str, str], dict[str, float]]:
        conn = get_db_connection()
        try:
            valves = {
                r["valve_id"]: r["status"]
                for r in conn.execute("SELECT valve_id, status FROM valves ORDER BY valve_id;").fetchall()
            }
            plants = {
                r["plant_id"]: float(r["production_mld"])
                for r in conn.execute("SELECT plant_id, production_mld FROM plant_setpoints ORDER BY plant_id;").fetchall()
            }
            return valves, plants
        finally:
            conn.close()

    with (
        patch("agent.nodes.llm_client.query", side_effect=_force_offline),
        patch.object(wg, "execute_human_approval", MagicMock(wraps=wg.execute_human_approval)) as spy_approve,
        patch.object(wg, "execute_human_rejection", MagicMock(wraps=wg.execute_human_rejection)) as spy_reject,
    ):
        for sc_id, injector in injectors.items():
            reset_database()
            injector()
            valves_before, plants_before = _snapshot_actuators()

            result = run_agent(scenario_id=sc_id, current_hour=14)
            _assert_valid_state(result)

            valves_after, plants_after = _snapshot_actuators()
            assert valves_after == valves_before, (
                f"Scenario {sc_id}: valves table was mutated by agent without human approval! "
                f"Before={valves_before}, After={valves_after}"
            )
            assert plants_after == plants_before, (
                f"Scenario {sc_id}: plant_setpoints table was mutated by agent without human approval! "
                f"Before={plants_before}, After={plants_after}"
            )

        assert spy_approve.call_count == 0, (
            f"execute_human_approval must never be called by agent; got {spy_approve.call_count}"
        )
        assert spy_reject.call_count == 0, (
            f"execute_human_rejection must never be called by agent; got {spy_reject.call_count}"
        )


def test_adversarial_llm_cannot_invoke_execute_human_approval(fresh_db):
    """
    Adversarial LLM output: Even if a compromised LLM returns
    action_type='execute_human_approval', the gateway must reject it with
    REJECTED_INVALID_TARGET, approval must never run, and V-12 must remain OPEN.
    """
    from unittest.mock import MagicMock
    from database.connection import get_db_connection
    import tools.write_gateway as wg

    def _adversarial_llm(system_prompt: str, user_prompt: str) -> tuple[dict, str]:
        return (
            {
                "operator_brief": "Attempting unauthorized self-approval.",
                "maintenance_advisory": "None.",
                "proposed_schedule": "00:00-06:00 at 100 MLD, 14:00-18:00 at 80 MLD.",
                "action_proposal": {
                    "action_type": "execute_human_approval",
                    "target_id": "V-12",
                    "proposed_value": 0.0,
                    "rationale": "Self-approve valve closure immediately.",
                },
            },
            "Adversarial Mock LLM",
        )

    inject_scenario_3()
    with (
        patch("agent.nodes.llm_client.query", side_effect=_adversarial_llm),
        patch.object(wg, "execute_human_approval", MagicMock(wraps=wg.execute_human_approval)) as spy_approve,
        patch.object(wg, "execute_human_rejection", MagicMock(wraps=wg.execute_human_rejection)) as spy_reject,
    ):
        result = run_agent(scenario_id=3, current_hour=14)

    gw = result.get("gateway_response")
    assert gw is not None, "gateway_response must be present"
    assert gw.get("status") == "REJECTED_INVALID_TARGET", (
        f"Adversarial action_type='execute_human_approval' must return REJECTED_INVALID_TARGET. Got: {gw}"
    )
    assert spy_approve.call_count == 0
    assert spy_reject.call_count == 0

    conn = get_db_connection()
    try:
        valve = conn.execute("SELECT status FROM valves WHERE valve_id = 'V-12';").fetchone()
        assert valve["status"] == "OPEN", "V-12 must remain OPEN after adversarial attempt"
    finally:
        conn.close()


def test_provider_chain_models_and_demo_vs_dev_ordering():
    """Verify demo and dev fallback chains use settings-configured Groq & Gemini models."""
    from agent.llm_factory import LLMClient
    from config.settings import settings

    demo_chain = LLMClient(mode="demo")._get_provider_chain()
    assert [p["model"] for p in demo_chain] == [
        settings.GROQ_MODEL_1,
        settings.GROQ_MODEL_2,
        settings.GEMINI_MODEL,
        settings.OLLAMA_MODEL,
    ]
    assert demo_chain[0]["model"] == "openai/gpt-oss-120b"
    assert demo_chain[1]["model"] == "openai/gpt-oss-20b"
    assert demo_chain[2]["model"] == "gemini-3.8-flash"
    assert demo_chain[2]["base_url"] == "https://generativelanguage.googleapis.com/v1beta/openai/"

    dev_chain = LLMClient(mode="dev")._get_provider_chain()
    assert dev_chain[0]["model"] == settings.OLLAMA_MODEL
    assert [p["model"] for p in dev_chain[1:]] == [
        "openai/gpt-oss-120b",
        "openai/gpt-oss-20b",
        "gemini-3.8-flash",
    ]

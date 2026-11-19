"""One-click SCADA scenario control bar (4 demo scenarios + Reset & Re-seed).

Uses Streamlit on_click callbacks with a re-entrancy lock so each button click
executes strictly ONCE before the page renders (no duplicate runs or extra st.rerun()).
"""
import streamlit as st
from config.constants import DEFAULT_SCADA_HOUR
from database.scenarios import (
    inject_scenario_1,
    inject_scenario_2,
    inject_scenario_3,
    inject_scenario_4,
    reset_database,
)
from agent.graph import run_agent
from tools.write_gateway import refuse_direct_write_bypass
from components.badges import section_header


def _execute_scenario(scenario_id: int) -> None:
    """Callback: reset DB, inject scenario, invoke LangGraph agent once with re-entrancy lock."""
    if st.session_state.get("_scenario_lock"):
        return

    st.session_state["_scenario_lock"] = True
    try:
        injectors = {
            1: inject_scenario_1,
            2: inject_scenario_2,
            3: inject_scenario_3,
            4: inject_scenario_4,
        }
        reset_database()
        info = injectors[scenario_id]()

        result = run_agent(scenario_id=scenario_id, current_hour=DEFAULT_SCADA_HOUR)

        bypass_result = None
        flagged = [a for a in result.get("sanitized_alerts", []) if a.get("injection_detected")]
        if scenario_id == 4 or flagged:
            bypass_result = refuse_direct_write_bypass(target_valve_id="V-12", attempted_status="OPEN")

        st.session_state["active_scenario"] = scenario_id
        st.session_state["active_scenario_name"] = f"Scenario {scenario_id}: {info['name']}"
        st.session_state["last_agent_result"] = result
        st.session_state["last_bypass_result"] = bypass_result
        st.session_state["last_hitl_feedback"] = None
    finally:
        st.session_state["_scenario_lock"] = False


def _reset_database_callback() -> None:
    """Callback: reset and re-seed database once."""
    if st.session_state.get("_scenario_lock"):
        return

    st.session_state["_scenario_lock"] = True
    try:
        reset_database()
        st.session_state["active_scenario"] = None
        st.session_state["active_scenario_name"] = "Clean 24h Baseline (Re-seeded)"
        st.session_state["last_agent_result"] = None
        st.session_state["last_bypass_result"] = None
        st.session_state["last_hitl_feedback"] = {
            "kind": "info",
            "message": "Database reset and re-seeded to clean 24h baseline (seed 42).",
        }
    finally:
        st.session_state["_scenario_lock"] = False


def render_scenario_selector() -> None:
    """Render the 5 persistent one-click scenario and reset buttons."""
    section_header("Scenario Control Bar", ["CODE", "LLM"])
    is_locked = bool(st.session_state.get("_scenario_lock", False))

    col1, col2, col3, col4, col5 = st.columns(5)

    with col1:
        st.button(
            "Scenario 1: Leak vs. Broken Sensor",
            width="stretch",
            key="btn_scenario_1",
            disabled=is_locked,
            on_click=_execute_scenario,
            args=(1,),
            help="Sector 4 J-14 leak + P-17 flatline + T-INTAKE-2 drift",
        )

    with col2:
        st.button(
            "Scenario 2: Throttle Aborted (Safety Floor)",
            width="stretch",
            key="btn_scenario_2",
            disabled=is_locked,
            on_click=_execute_scenario,
            args=(2,),
            help="Peak tariff ($0.48/kWh) + Intake 2 bloom derating vs. 35% floor & replan",
        )

    with col3:
        st.button(
            "Scenario 3: Valve Needs Human Approval",
            width="stretch",
            key="btn_scenario_3",
            disabled=is_locked,
            on_click=_execute_scenario,
            args=(3,),
            help="Isolate Sector 4 leak via V-12 staged PENDING for operator Approve/Reject",
        )

    with col4:
        st.button(
            "Scenario 4: Injection Attack Blocked",
            width="stretch",
            key="btn_scenario_4",
            disabled=is_locked,
            on_click=_execute_scenario,
            args=(4,),
            help="Full-alert regex quarantine + direct SQLite write bypass refused",
        )

    with col5:
        st.button(
            "Reset and Re-seed Database",
            width="stretch",
            key="btn_reset_db",
            type="secondary",
            disabled=is_locked,
            on_click=_reset_database_callback,
            help="Restore pristine 24h baseline with fixed seed 42",
        )

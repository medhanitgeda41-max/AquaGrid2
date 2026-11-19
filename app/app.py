"""AquaGrid Streamlit SCADA Control Room — Phase 4 Entry Point.

Launch from project root:
    python -m streamlit run app/app.py
"""
import os
try:
    import streamlit as st
    for _k, _v in st.secrets.items():
        if isinstance(_v, (str, int, float)):
            os.environ.setdefault(_k, str(_v))
except Exception:
    pass
import sys

# Ensure both app/ (for components.*) and project root (for agent/database/guards/tools/config) are on sys.path
APP_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(APP_DIR)
for _p in (PROJECT_ROOT, APP_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import streamlit as st
from database.connection import get_db_connection, init_db
from database.seed_data import seed_database
from components.badges import inject_scada_css
from components.header import render_header
from components.scenario_selector import render_scenario_selector
from components.incident_brief import render_incident_brief
from components.telemetry_view import render_telemetry_view
from components.approval_card import render_approval_card
from components.audit_log_view import render_audit_log


def _ensure_database_initialized() -> None:
    """Initialize and seed SQLite database on first launch if empty."""
    init_db()
    conn = get_db_connection()
    try:
        res_count = conn.execute("SELECT COUNT(*) AS cnt FROM reservoirs;").fetchone()["cnt"]
    finally:
        conn.close()
    if res_count == 0:
        seed_database()


def main() -> None:
    st.set_page_config(
        page_title="AquaGrid SCADA Control Room",
        page_icon="💧",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    _pw = os.getenv("APP_PASSWORD")
    if _pw and not st.session_state.get("auth_ok"):
        st.title("AquaGrid – Operator Login")
        _entered = st.text_input("Password", type="password")
        if _entered == _pw:
            st.session_state["auth_ok"] = True
            st.rerun()
        elif _entered:
            st.error("Wrong password")
        st.stop()
    inject_scada_css()
    _ensure_database_initialized()

    # Top Header & Real-Time KPIs
    snapshot = render_header()

    # Persistent 5-Button Scenario & Reset Control Bar
    render_scenario_selector()

    st.divider()

    # Main 4-Tab SCADA Layout
    pending_count = snapshot.get("pending_count", 0)
    approval_tab_label = f"HITL Approval Center ({pending_count} PENDING)" if pending_count > 0 else "HITL Approval Center"

    tab_report, tab_telemetry, tab_approval, tab_audit = st.tabs(
        [
            "Incident & Guard Report",
            "SCADA Telemetry & Reservoir",
            approval_tab_label,
            "Audit Log",
        ]
    )

    with tab_report:
        # Surface pending approval card right alongside the scenario report when HITL action is waiting
        if pending_count > 0:
            render_approval_card(key_prefix="inline", show_history=False)
            st.divider()
        render_incident_brief()

    with tab_telemetry:
        render_telemetry_view(snapshot)

    with tab_approval:
        render_approval_card(key_prefix="center", show_history=True)

    with tab_audit:
        render_audit_log()


if __name__ == "__main__":
    main()

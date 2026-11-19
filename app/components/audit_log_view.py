"""Immutable SCADA & Agent Audit Log viewer."""
import pandas as pd
import streamlit as st
from database.connection import get_db_connection
from components.badges import format_dubai_time, section_header


def render_audit_log() -> None:
    """Render live SQLite audit_log table with actor filtering."""
    section_header("Immutable SCADA Audit Log", ["CODE", "LLM", "HUMAN"])

    actor_filter = st.selectbox(
        "Filter by Actor",
        options=["ALL", "CODE_GUARD", "HUMAN_OPERATOR", "LLM_AGENT"],
        index=0,
        key="audit_actor_filter",
    )

    conn = get_db_connection()
    try:
        if actor_filter == "ALL":
            rows = conn.execute(
                "SELECT id, timestamp, event_type, target_id, actor, status, details FROM audit_log ORDER BY id DESC LIMIT 100;"
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, timestamp, event_type, target_id, actor, status, details
                FROM audit_log
                WHERE actor = ?
                ORDER BY id DESC
                LIMIT 100;
                """,
                (actor_filter,),
            ).fetchall()
    finally:
        conn.close()

    if not rows:
        st.info("No audit log entries match the selected filter.")
        return

    df = pd.DataFrame(
        [
            {
                "ID": r["id"],
                "Timestamp (Asia/Dubai)": format_dubai_time(r["timestamp"]),
                "Actor": r["actor"],
                "Event": r["event_type"],
                "Target": r["target_id"] or "-",
                "Status": r["status"],
                "Details": r["details"],
            }
            for r in rows
        ]
    )
    st.dataframe(df, width="stretch", hide_index=True, height=420)

"""Incident Brief & Pure-Python Guard Report — mirrors every run_agent.py section with LLM/CODE/HUMAN badges."""
import html
import json
import streamlit as st
from database.connection import get_db_connection
from guards.injection_filter import detect_injection
from components.badges import actor_badge, format_dubai_time, section_header, status_badge


def _render_final_valve_v12_status() -> None:
    """Read and render live Valve V-12 status directly from SQLite."""
    conn = get_db_connection()
    try:
        v12 = conn.execute("SELECT valve_id, sector, status, last_updated FROM valves WHERE valve_id = 'V-12';").fetchone()
    finally:
        conn.close()

    section_header("Final Valve V-12 Status (Live SQLite State)", ["CODE", "HUMAN"])
    if v12:
        card_cls = "scada-card-ok" if v12["status"] == "OPEN" else "scada-card-pending"
        st.markdown(
            f"""
            <div class="{card_cls}">
                <strong>{html.escape(v12['valve_id'])} ({html.escape(v12['sector'])})</strong>:
                {status_badge(v12['status'])}
                <span style="color:#9FB3C8; font-size:0.84rem; margin-left:0.5rem;">
                    Last updated: {html.escape(format_dubai_time(v12['last_updated']))}
                </span>
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_incident_brief() -> None:
    """Render the full scenario run report with all sections matching run_agent.py."""
    result = st.session_state.get("last_agent_result")
    scenario_id = st.session_state.get("active_scenario")
    bypass_result = st.session_state.get("last_bypass_result")

    if not result:
        st.info(
            "Select one of the 4 scenario buttons above to run the AquaGrid agent and inspect the "
            "live LLM brief, pure-Python schedule validation, gateway history, and security shields."
        )
        _render_final_valve_v12_status()
        return

    # 1. Execution Summary Banner (Model Provider, Status, Steps/Replans)
    provider = result.get("llm_provider", "Unknown")
    status = result.get("status", "UNKNOWN")
    steps = result.get("agent_step_count", 0)
    replans = result.get("replan_count", 0)

    st.markdown(
        f"""
        <div class="scada-card">
            <div style="display:flex; flex-wrap:wrap; gap:1.25rem; align-items:center;">
                <div>{actor_badge("LLM")} <strong>Model Provider Used:</strong>
                    <span class="ag-mono">{html.escape(str(provider))}</span>
                </div>
                <div>{actor_badge("CODE")} <strong>Agent Status:</strong> {status_badge(status)}</div>
                <div>{actor_badge("CODE")} <strong>Steps:</strong> {steps} (Replans: {replans})</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # 2. Operator Brief & Maintenance Advisory / Work Orders [LLM]
    b_col, m_col = st.columns(2)
    with b_col:
        section_header("Operator Action Brief", ["LLM"])
        st.markdown(
            f'<div class="scada-card">{html.escape(str(result.get("operator_brief", "")))}</div>',
            unsafe_allow_html=True,
        )
    with m_col:
        section_header("Maintenance Advisory / Work Orders", ["LLM"])
        st.markdown(
            f'<div class="scada-card">{html.escape(str(result.get("maintenance_advisory", "")))}</div>',
            unsafe_allow_html=True,
        )

    # 3. Proposed Production Schedule [LLM] + Schedule Validation [CODE]
    section_header("Proposed Production Schedule", ["LLM"])
    st.markdown(
        f'<div class="scada-card ag-mono">{html.escape(str(result.get("proposed_schedule", "")))}</div>',
        unsafe_allow_html=True,
    )

    sched_val = result.get("schedule_validation")
    if sched_val:
        sv_status = sched_val.get("status", "UNKNOWN")
        section_header(
            "Schedule Validation (Pure Python Guard)",
            ["CODE"],
            extra_badge=status_badge(sv_status),
        )
        card_cls = "scada-card-ok" if sv_status == "VALID" else "scada-card-alert"
        lines_html = [f"<div><strong>{html.escape(str(sched_val.get('summary', '')))}</strong></div>"]
        blocks = sched_val.get("blocks", [])
        if blocks:
            for blk in blocks:
                blk_badge = status_badge(blk.get("status", "UNKNOWN"))
                win = html.escape(str(blk.get("window")))
                mld = blk.get("proposed_mld")
                min_pct = blk.get("min_projected_percent")
                reasons_html = "".join(
                    f'<div style="color:#FCA5A5; margin-left:1.25rem; font-size:0.84rem;">&rarr; {html.escape(str(r))}</div>'
                    for r in blk.get("reasons", [])
                )
                lines_html.append(
                    f'<div style="margin-top:0.4rem;">{blk_badge} '
                    f'<span class="ag-mono">{win} @ {mld} MLD</span> '
                    f'<span style="color:#9FB3C8;">(min projected reservoir: {min_pct}%)</span>'
                    f'{reasons_html}</div>'
                )
        else:
            for blk in sched_val.get("rejected_blocks", []):
                for r in blk.get("reasons", []):
                    lines_html.append(
                        f'<div style="margin-top:0.35rem; color:#FCA5A5;">{status_badge("REJECTED_BY_CODE")} {html.escape(str(r))}</div>'
                    )
        st.markdown(f'<div class="{card_cls}">{"".join(lines_html)}</div>', unsafe_allow_html=True)

    # 4. Proposal & Gateway History (Layer 3 Python Code Guards) [LLM -> CODE]
    proposal_history = result.get("proposal_history", [])
    if proposal_history:
        section_header("Proposal & Gateway History (Layer 3 Python Code Guards)", ["LLM", "CODE"])
        for entry in proposal_history:
            attempt = entry.get("attempt")
            replan = entry.get("replan_count")
            prop = entry.get("action_proposal") or {}
            gw = entry.get("gateway_response") or {}
            gw_status = gw.get("status", "UNKNOWN")
            min_pct = gw.get("min_projected_percent")
            pct_html = (
                f' &nbsp;|&nbsp; <strong>Min Projected Reservoir:</strong> <span class="ag-mono">{min_pct}%</span>'
                if min_pct is not None
                else ""
            )
            guard_msg = gw.get("reason") or gw.get("message") or ""
            card_cls = "scada-card-pending" if gw_status == "STAGED_PENDING_APPROVAL" else "scada-card-alert"
            st.markdown(
                f"""
                <div class="{card_cls}">
                    <div>
                        {actor_badge("LLM")} <strong>Attempt #{attempt} (replan={replan}):</strong>
                        <span class="ag-mono">{html.escape(str(prop.get('action_type')))}
                        {html.escape(str(prop.get('target_id')))} &rarr; {html.escape(str(prop.get('proposed_value')))}</span>
                        &nbsp;&nbsp;{actor_badge("CODE")} {status_badge(gw_status)}{pct_html}
                    </div>
                    <div style="margin-top:0.35rem; font-size:0.86rem;">
                        <strong>LLM Rationale:</strong> {html.escape(str(prop.get('rationale', '')))}
                    </div>
                    <div style="margin-top:0.25rem; font-size:0.86rem; color:#CBD5E1;">
                        <strong>Code Guard Verdict:</strong> {html.escape(str(guard_msg))}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    # 5. Injection Shield (Pure Python Guard) [CODE]
    sanitized_alerts = result.get("sanitized_alerts", [])
    flagged_alerts = [a for a in sanitized_alerts if a.get("injection_detected")]
    if scenario_id == 4 or flagged_alerts:
        section_header("Injection Shield (Pure Python Guard)", ["CODE"], extra_badge=status_badge("BLOCKED"))
        conn = get_db_connection()
        try:
            raw_rows = conn.execute(
                "SELECT id, raw_text FROM quality_alerts WHERE is_injection = 1 ORDER BY id DESC;"
            ).fetchall()
            raw_by_id = {r["id"]: r["raw_text"] for r in raw_rows}
        finally:
            conn.close()

        last_prompt = result.get("last_user_prompt", "")
        for alert in flagged_alerts:
            a_id = alert.get("alert_id")
            raw_text = raw_by_id.get(a_id, "")
            _, matched_patterns = detect_injection(raw_text)
            sanitized_text = alert.get("text", "")
            raw_reached_llm = bool(raw_text) and (raw_text in last_prompt)
            leaked_fragments = [
                frag
                for frag in ("SYSTEM OVERRIDE", "ignore safety", "open valve", "V-12", "emergency flushing")
                if frag.lower() in last_prompt.lower()
            ]
            sanitized_reached_llm = bool(sanitized_text) and (sanitized_text in last_prompt)
            confirm_text = (
                "YES (BREACH!)"
                if (raw_reached_llm or leaked_fragments)
                else "NO — CONFIRMED (entire malicious text withheld; zero original instruction reached LLM)"
            )
            st.markdown(
                f"""
                <div class="scada-card-alert">
                    <div><strong>Alert Metadata:</strong> <span class="ag-mono">id={html.escape(str(a_id))}, source={html.escape(str(alert.get('source')))}, severity={html.escape(str(alert.get('severity')))}</span></div>
                    <div style="margin-top:0.35rem;"><strong>Original Malicious Alert (Quarantined in DB):</strong><br/>
                        <span class="ag-mono" style="color:#FCA5A5;">{html.escape(raw_text)}</span>
                    </div>
                    <div style="margin-top:0.35rem;"><strong>Matched Regex Pattern(s):</strong><br/>
                        <span class="ag-mono" style="color:#FDE68A;">{html.escape(str(matched_patterns))}</span>
                    </div>
                    <div style="margin-top:0.35rem;"><strong>Sanitized Payload Sent to LLM:</strong><br/>
                        <span class="ag-mono" style="color:#7CE8FF;">{html.escape(json.dumps(alert))}</span>
                    </div>
                    <div style="margin-top:0.4rem;"><strong>Raw Text Reached LLM?</strong>
                        <span style="color:#6EE7B7; font-weight:700;">{html.escape(confirm_text)}</span>
                        <span class="ag-mono" style="color:#9FB3C8;"> [sanitized_in_prompt={sanitized_reached_llm}, leaked_fragments={leaked_fragments}]</span>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    # 6. Direct Write Bypass Attempt [CODE]
    if bypass_result:
        section_header(
            "Direct Write Bypass Attempt",
            ["CODE"],
            extra_badge=status_badge(bypass_result.get("status", "REFUSED")),
        )
        st.markdown(
            f"""
            <div class="scada-card-alert">
                <div><strong>Attempted Bypass:</strong> <span class="ag-mono">{html.escape(str(bypass_result.get('attempted_action')))}</span></div>
                <div style="margin-top:0.3rem;"><strong>Result:</strong> {status_badge(bypass_result.get('status', 'REFUSED'))}
                    <span class="ag-mono" style="color:#FCA5A5;">{html.escape(str(bypass_result.get('error')))}</span>
                </div>
                <div style="margin-top:0.3rem;"><strong>DB Integrity:</strong>
                    <span class="ag-mono">V-12 before={html.escape(str(bypass_result.get('valve_status_before')))} &rarr; after={html.escape(str(bypass_result.get('valve_status_after')))} (unchanged={bypass_result.get('unchanged')})</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # 7. Final Valve V-12 Status (Always displayed at the bottom of the report)
    _render_final_valve_v12_status()

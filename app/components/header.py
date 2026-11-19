"""SCADA Control Room header: system status, active LLM tier, grid health, and live KPIs."""
import html
import streamlit as st
from config.settings import settings
from config.constants import DEFAULT_SCADA_HOUR, RESERVOIR_FLOOR_PERCENT
from database.connection import get_db_connection
from tools.read_telemetry import read_network_telemetry
from tools.read_feeds import read_tariff_and_quality_feeds
from components.badges import actor_badge, status_badge


def _compute_grid_health(telemetry_data: dict, feeds_data: dict, pending_count: int) -> tuple[int, str]:
    """Deterministically calculate Grid Health Score (0-100) from live SCADA telemetry."""
    score = 100
    leak_count = len(telemetry_data.get("leak_alerts", []))
    quarantined_count = len(telemetry_data.get("quarantined_sensors", []))
    injection_count = sum(1 for a in feeds_data.get("sanitized_alerts", []) if a.get("injection_detected"))
    wq = feeds_data.get("water_quality", {})
    bloom_sev = str(wq.get("bloom_severity", "NONE")).upper()
    res_pct = float(feeds_data.get("reservoir", {}).get("current_level_percent", 48.0))

    score -= leak_count * 20
    score -= quarantined_count * 6
    score -= injection_count * 12
    if bloom_sev == "CRITICAL":
        score -= 15
    elif bloom_sev == "MODERATE":
        score -= 10
    elif bloom_sev == "LOW":
        score -= 5
    if res_pct < RESERVOIR_FLOOR_PERCENT * 100.0:
        score -= 30
    if pending_count > 0:
        score -= 4

    score = max(0, min(100, score))
    if score >= 85:
        label = "NOMINAL"
    elif score >= 65:
        label = "ELEVATED WATCH"
    else:
        label = "ALERT ACTIVE"
    return score, label


def render_header() -> dict:
    """Render top SCADA banner and real-time KPI row. Returns live snapshot dict for reuse."""
    conn = get_db_connection()
    try:
        plant = conn.execute("SELECT * FROM plant_setpoints WHERE plant_id = 'DESAL-01';").fetchone()
        pending_count = conn.execute(
            "SELECT COUNT(*) AS cnt FROM pending_actions WHERE status = 'PENDING';"
        ).fetchone()["cnt"]
        v12 = conn.execute("SELECT valve_id, sector, status FROM valves WHERE valve_id = 'V-12';").fetchone()
    finally:
        conn.close()

    telemetry_data = read_network_telemetry(current_hour=DEFAULT_SCADA_HOUR)
    feeds_data = read_tariff_and_quality_feeds(horizon_hours=6, current_hour=DEFAULT_SCADA_HOUR)

    health_score, health_label = _compute_grid_health(telemetry_data, feeds_data, pending_count)

    last_result = st.session_state.get("last_agent_result")
    provider_used = (
        last_result.get("llm_provider")
        if last_result
        else f"Ready (LLM_MODE={settings.LLM_MODE})"
    )
    active_scenario_name = st.session_state.get("active_scenario_name", "Clean 24h Baseline")

    res = feeds_data.get("reservoir", {})
    res_pct = float(res.get("current_level_percent", 48.0))
    res_vol = float(res.get("current_volume_ml", 240.0))
    plant_mld = float(plant["production_mld"]) if plant else 100.0
    plant_max = float(plant["max_capacity_mld"]) if plant else 120.0
    plant_status = plant["status"] if plant else "ONLINE"

    tariffs = feeds_data.get("tariffs", [])
    curr_tariff = tariffs[0]["rate_per_kwh"] if tariffs else 0.48
    is_peak = feeds_data.get("is_current_peak_tariff", True)
    v12_status = v12["status"] if v12 else "OPEN"

    st.markdown(
        f"""
        <div class="scada-banner">
            <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:0.5rem;">
                <div>
                    <div class="scada-title">AQUAGRID SCADA CONTROL ROOM</div>
                    <div class="scada-subtitle">
                        Autonomous Desalination, Tariff-Aware Network &amp; Valve Safety Agent
                        &nbsp;|&nbsp; Active View: <strong>{html.escape(active_scenario_name)}</strong>
                    </div>
                </div>
                <div style="text-align:right;">
                    {actor_badge("CODE")} {status_badge(health_label)}
                    {actor_badge("LLM")} <span class="ag-badge ag-badge-neutral">{html.escape(provider_used)}</span>
                    <span class="ag-badge ag-badge-neutral">LLM_MODE={html.escape(settings.LLM_MODE)}</span>
                </div>
            </div>
            <div style="margin-top:0.55rem; font-size:0.78rem; color:#9FB3C8;">
                Responsibility Legend:&nbsp;
                {actor_badge("CODE")} Deterministic Python Safety Guards &amp; SQLite Gateway &nbsp;&nbsp;
                {actor_badge("LLM")} Cognitive Analysis, Briefs &amp; Proposals &nbsp;&nbsp;
                {actor_badge("HUMAN")} Mandatory Approve / Reject Signoff
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric(
        "Grid Health [CODE]",
        f"{health_score}/100",
        delta=health_label,
        delta_color="normal" if health_score >= 85 else "inverse",
    )
    c2.metric(
        "Reservoir RES-01 [CODE]",
        f"{res_pct:.1f}%",
        delta=f"{res_vol:.0f} ML (Floor 35%)",
        delta_color="normal" if res_pct >= 35.0 else "inverse",
    )
    c3.metric(
        "DESAL-01 Output [CODE]",
        f"{plant_mld:.1f} MLD",
        delta=f"{plant_status} / {plant_max:.0f} Max",
    )
    c4.metric(
        "Tariff @ 14:00 [CODE]",
        f"${curr_tariff:.2f}/kWh",
        delta="PEAK WINDOW" if is_peak else "OFF-PEAK",
        delta_color="inverse" if is_peak else "normal",
    )
    c5.metric(
        "Valve V-12 [CODE]",
        v12_status,
        delta="Sector 4 Main",
    )
    c6.metric(
        "Pending HITL [HUMAN]",
        str(pending_count),
        delta="Action Required" if pending_count > 0 else "Queue Clear",
        delta_color="inverse" if pending_count > 0 else "off",
    )

    return {
        "telemetry_data": telemetry_data,
        "feeds_data": feeds_data,
        "pending_count": pending_count,
        "plant_mld": plant_mld,
        "v12_status": v12_status,
    }

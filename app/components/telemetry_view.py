"""Interactive SCADA Telemetry View: Reservoir 35% floor chart, Tariffs/Demand, Pressures & Valves."""
import html
import altair as alt
import pandas as pd
import streamlit as st
from config.constants import (
    DEFAULT_SCADA_HOUR,
    RESERVOIR_FLOOR_PERCENT,
    RESERVOIR_TOTAL_CAPACITY_ML,
)
from database.connection import get_db_connection
from guards.safety_floors import simulate_reservoir_trajectory
from components.badges import section_header, status_badge


def _build_reservoir_chart(
    feeds_data: dict,
    plant_mld: float,
    agent_result: dict | None,
    active_scenario: int | None,
) -> alt.LayerChart:
    """Build interactive Altair chart of 6h reservoir trajectory with red 35% floor line."""
    res = feeds_data.get("reservoir", {})
    start_vol = float(res.get("current_volume_ml", 240.0))
    start_pct = float(res.get("current_level_percent", 48.0))
    hourly_24 = feeds_data.get("hourly_demand_24h", {})
    demands_6h = [float(hourly_24.get(DEFAULT_SCADA_HOUR + i, 90.0)) for i in range(6)]

    series_defs: list[tuple[str, float, str]] = []
    seen_vals: set[float] = set()

    if active_scenario == 2:
        # Scenario 2: always highlight both the rejected 15 MLD throttle (below 35%)
        # and the 60 MLD bloom-safe replan (staying above 35%)
        series_defs.append(("Rejected 15 MLD Throttle (Breaches 35%)", 15.0, "#F59E0B"))
        seen_vals.add(15.0)
        series_defs.append(("60 MLD Bloom-Safe Replan (>= 35%)", 60.0, "#10B981"))
        seen_vals.add(60.0)
    else:
        series_defs.append((f"Current Setpoint ({plant_mld:.0f} MLD)", plant_mld, "#00C2FF"))
        seen_vals.add(round(plant_mld, 1))

    # Overlay any additional distinct SET_PLANT_OUTPUT attempts from proposal_history
    if agent_result:
        for entry in agent_result.get("proposal_history", []):
            prop = entry.get("action_proposal") or {}
            if prop.get("action_type") == "SET_PLANT_OUTPUT":
                val = round(float(prop.get("proposed_value", 0.0)), 1)
                if val in seen_vals:
                    continue
                seen_vals.add(val)
                gw_status = (entry.get("gateway_response") or {}).get("status", "")
                if gw_status == "REJECTED_BY_SAFETY_GUARD":
                    label = f"Attempt #{entry.get('attempt')} Rejected ({val:.0f} MLD)"
                    color = "#FB7185"
                else:
                    label = f"Attempt #{entry.get('attempt')} Staged ({val:.0f} MLD)"
                    color = "#38BDF8"
                series_defs.append((label, val, color))

    rows = []
    color_domain = []
    color_range = []
    for label, inflow_mld, hex_color in series_defs:
        color_domain.append(label)
        color_range.append(hex_color)
        sim = simulate_reservoir_trajectory(
            current_volume_ml=start_vol,
            plant_inflow_mld=inflow_mld,
            demand_forecast_mld=demands_6h,
            total_capacity_ml=RESERVOIR_TOTAL_CAPACITY_ML,
            min_floor_percent=RESERVOIR_FLOOR_PERCENT,
        )
        rows.append({
            "hour_label": f"{DEFAULT_SCADA_HOUR:02d}:00",
            "level_pct": round(start_pct, 2),
            "volume_ml": round(start_vol, 1),
            "series": label,
        })
        for pt in sim["hourly_levels"]:
            off = int(pt["hour_offset"])
            rows.append({
                "hour_label": f"{(DEFAULT_SCADA_HOUR + off) % 24:02d}:00",
                "level_pct": float(pt["level_percent"]),
                "volume_ml": float(pt["volume_ml"]),
                "series": label,
            })

    df = pd.DataFrame(rows)
    min_val = float(df["level_pct"].min())
    max_val = float(df["level_pct"].max())
    y_min = max(0.0, min(30.0, min_val - 3.0))
    y_max = min(100.0, max(52.0, max_val + 4.0))

    lines = (
        alt.Chart(df)
        .mark_line(point=alt.OverlayMarkDef(size=70), strokeWidth=3)
        .encode(
            x=alt.X("hour_label:N", sort=None, title="Forecast Horizon (SCADA Hour)"),
            y=alt.Y(
                "level_pct:Q",
                scale=alt.Scale(domain=[y_min, y_max]),
                title="Reservoir Storage Level (%)",
            ),
            color=alt.Color(
                "series:N",
                scale=alt.Scale(domain=color_domain, range=color_range),
                legend=alt.Legend(orient="top", title=None, columns=2),
            ),
            tooltip=[
                alt.Tooltip("series:N", title="Trajectory"),
                alt.Tooltip("hour_label:N", title="Hour"),
                alt.Tooltip("level_pct:Q", title="Level (%)", format=".2f"),
                alt.Tooltip("volume_ml:Q", title="Volume (ML)", format=".1f"),
            ],
        )
    )

    floor_df = pd.DataFrame({"floor_y": [35.0], "label": ["35% MANDATORY SAFETY FLOOR (175 ML)"]})
    floor_rule = (
        alt.Chart(floor_df)
        .mark_rule(color="#FF3B3B", strokeDash=[6, 4], strokeWidth=2.8)
        .encode(y="floor_y:Q")
    )
    floor_text = (
        alt.Chart(floor_df)
        .mark_text(align="left", dx=6, dy=-8, color="#FF6B6B", fontWeight="bold", fontSize=11)
        .encode(x=alt.value(8), y="floor_y:Q", text="label:N")
    )

    return (
        (lines + floor_rule + floor_text)
        .properties(height=360, padding={"left": 10, "top": 8, "right": 10, "bottom": 10})
        .configure_view(strokeWidth=0)
    )


def render_telemetry_view(snapshot: dict) -> None:
    """Render Reservoir 35% floor chart, Tariff/Demand view, Sector telemetry, and Valve Grid."""
    telemetry_data = snapshot["telemetry_data"]
    feeds_data = snapshot["feeds_data"]
    plant_mld = snapshot["plant_mld"]
    agent_result = st.session_state.get("last_agent_result")
    active_scenario = st.session_state.get("active_scenario")

    # Row 1: Reservoir Level Chart (with red 35% floor) & 24h Tariff/Demand
    left_col, right_col = st.columns([1.15, 1.05])

    with left_col:
        section_header("Strategic Reservoir Trajectory vs. 35% Safety Floor", ["CODE"])
        chart = _build_reservoir_chart(feeds_data, plant_mld, agent_result, active_scenario)
        st.altair_chart(chart, width="stretch")

    with right_col:
        section_header("24h Electricity Tariff & Water Demand Forecast", ["CODE"])
        conn = get_db_connection()
        try:
            td_rows = conn.execute(
                """
                SELECT t.hour, t.rate_per_kwh, t.is_peak, d.demand_mld
                FROM tariffs t
                JOIN demand_forecast d ON t.hour = d.hour
                ORDER BY t.hour ASC;
                """
            ).fetchall()
        finally:
            conn.close()

        td_df = pd.DataFrame(
            [
                {
                    "hour_label": f"{int(r['hour']):02d}:00",
                    "tariff_rate": float(r["rate_per_kwh"]),
                    "tier": "PEAK (14:00-18:00, $0.48/kWh)" if r["is_peak"] else "Off/Mid-Peak",
                    "demand_mld": float(r["demand_mld"]),
                }
                for r in td_rows
            ]
        )

        # Clean alphanumeric field names prevent Vega-Lite field-path parsing bugs
        tariff_bars = (
            alt.Chart(td_df)
            .mark_bar(cornerRadiusTopLeft=2, cornerRadiusTopRight=2, opacity=0.92)
            .encode(
                x=alt.X(
                    "hour_label:N",
                    sort=None,
                    title="Hour of Day",
                    axis=alt.Axis(labelAngle=-45, labelFontSize=10),
                ),
                y=alt.Y(
                    "tariff_rate:Q",
                    title="Electricity Rate ($/kWh)",
                    scale=alt.Scale(domain=[0.0, 0.55]),
                    axis=alt.Axis(format="$.2f", titlePadding=10),
                ),
                color=alt.Color(
                    "tier:N",
                    scale=alt.Scale(
                        domain=["PEAK (14:00-18:00, $0.48/kWh)", "Off/Mid-Peak"],
                        range=["#EF4444", "#38BDF8"],
                    ),
                    legend=alt.Legend(orient="top", title=None),
                ),
                tooltip=[
                    alt.Tooltip("hour_label:N", title="Hour"),
                    alt.Tooltip("tariff_rate:Q", title="Rate ($/kWh)", format="$.3f"),
                    alt.Tooltip("demand_mld:Q", title="Demand (MLD)", format=".1f"),
                    alt.Tooltip("tier:N", title="Tariff Tier"),
                ],
            )
            .properties(height=210, padding={"left": 10, "top": 6, "right": 10, "bottom": 6})
        )

        max_demand = max(120.0, float(td_df["demand_mld"].max()) * 1.15)
        demand_line = (
            alt.Chart(td_df)
            .mark_line(color="#A78BFA", strokeWidth=2.5, point=alt.OverlayMarkDef(size=45, color="#C4B5FD"))
            .encode(
                x=alt.X(
                    "hour_label:N",
                    sort=None,
                    title="Hour of Day",
                    axis=alt.Axis(labelAngle=-45, labelFontSize=10),
                ),
                y=alt.Y(
                    "demand_mld:Q",
                    title="Demand (MLD)",
                    scale=alt.Scale(domain=[0.0, max_demand], nice=True),
                    axis=alt.Axis(titleFontSize=12, labelFontSize=11, titlePadding=10),
                ),
                tooltip=[
                    alt.Tooltip("hour_label:N", title="Hour"),
                    alt.Tooltip("demand_mld:Q", title="Demand (MLD)", format=".1f"),
                    alt.Tooltip("tariff_rate:Q", title="Rate ($/kWh)", format="$.3f"),
                ],
            )
            .properties(height=210, padding={"left": 10, "top": 10, "right": 10, "bottom": 6})
        )

        st.altair_chart(tariff_bars, width="stretch")
        st.altair_chart(demand_line, width="stretch")

    st.divider()

    # Row 2: Hydraulic Network Pressure & Flow Telemetry + Diagnostics
    p_col, d_col = st.columns([1.15, 1.05])

    with p_col:
        section_header("Network Junction Pressures at 14:00 (Sector 1–4)", ["CODE"])
        conn = get_db_connection()
        try:
            p_rows = conn.execute(
                """
                SELECT sensor_id, junction_id, sector, value, status
                FROM telemetry
                WHERE hour = ? AND sensor_id LIKE 'P-%'
                ORDER BY sensor_id ASC;
                """,
                (DEFAULT_SCADA_HOUR,),
            ).fetchall()
        finally:
            conn.close()

        quarantined_ids = {s["sensor_id"] for s in telemetry_data.get("quarantined_sensors", [])}
        leak_jids = {a["junction_id"] for a in telemetry_data.get("leak_alerts", [])}
        p_df = pd.DataFrame(
            [
                {
                    "junction": r["junction_id"],
                    "sensor": r["sensor_id"],
                    "sector": r["sector"],
                    "pressure_psi": float(r["value"]),
                    "state": (
                        "CONFIRMED_LEAK"
                        if r["junction_id"] in leak_jids
                        else ("QUARANTINED" if r["sensor_id"] in quarantined_ids else "NORMAL")
                    ),
                }
                for r in p_rows
            ]
        )
        p_chart = (
            alt.Chart(p_df)
            .mark_bar()
            .encode(
                x=alt.X("junction:N", sort=None, title="Junction ID", axis=alt.Axis(labelAngle=-45)),
                y=alt.Y("pressure_psi:Q", scale=alt.Scale(domain=[0, 75]), title="Pressure (psi)"),
                color=alt.Color(
                    "state:N",
                    scale=alt.Scale(
                        domain=["NORMAL", "QUARANTINED", "CONFIRMED_LEAK"],
                        range=["#38BDF8", "#F59E0B", "#EF4444"],
                    ),
                    legend=alt.Legend(orient="top", title=None),
                ),
                tooltip=[
                    alt.Tooltip("junction:N", title="Junction"),
                    alt.Tooltip("sensor:N", title="Sensor"),
                    alt.Tooltip("sector:N", title="Sector"),
                    alt.Tooltip("pressure_psi:Q", title="Pressure (psi)", format=".1f"),
                    alt.Tooltip("state:N", title="State"),
                ],
            )
            .properties(height=280)
        )
        st.altair_chart(p_chart, width="stretch")

    with d_col:
        section_header("Deterministic Leak & Sensor Quarantine Diagnostics", ["CODE"])
        leaks = telemetry_data.get("leak_alerts", [])
        quarantined = telemetry_data.get("quarantined_sensors", [])

        if leaks:
            for lk in leaks:
                st.error(
                    f"**CONFIRMED PIPE LEAK — {lk['junction_id']} ({lk['sector']})**\n\n"
                    f"{lk['diagnostic']}"
                )
        else:
            st.success("No active hydraulic pipe leak signatures detected.")

        if quarantined:
            st.warning(f"{len(quarantined)} sensor(s) quarantined by pure Python rules:")
            rows_html = []
            for q in quarantined:
                reason_text = "; ".join(q.get("reasons", []))
                rows_html.append(
                    f"<tr>"
                    f"<td class='ag-mono' style='white-space:nowrap;'><strong>{html.escape(str(q['sensor_id']))}</strong></td>"
                    f"<td style='white-space:nowrap;'>{html.escape(str(q['junction_id']))}</td>"
                    f"<td style='white-space:nowrap;'>{html.escape(str(q['sector']))}</td>"
                    f"<td class='ag-mono' style='white-space:nowrap;'>{html.escape(str(q['last_reading']))} {html.escape(str(q['unit']))}</td>"
                    f"<td style='min-width:220px;'>{html.escape(reason_text)}</td>"
                    f"</tr>"
                )
            st.markdown(
                f"""
                <table class="scada-table">
                    <thead>
                        <tr>
                            <th>Sensor</th>
                            <th>Junction</th>
                            <th>Sector</th>
                            <th>Reading</th>
                            <th>Quarantine Reason</th>
                        </tr>
                    </thead>
                    <tbody>
                        {"".join(rows_html)}
                    </tbody>
                </table>
                """,
                unsafe_allow_html=True,
            )
        else:
            st.info("All 44 pressure, flow, and intake water-quality sensors passed health checks.")

    st.divider()

    # Row 3: Live 12-Valve Matrix
    section_header("Live Isolation Valve Matrix (V-01 through V-12)", ["CODE", "HUMAN"])
    conn = get_db_connection()
    try:
        valve_rows = conn.execute(
            "SELECT valve_id, sector, status, last_updated FROM valves ORDER BY valve_id ASC;"
        ).fetchall()
    finally:
        conn.close()

    cols = st.columns(6)
    for idx, v in enumerate(valve_rows):
        with cols[idx % 6]:
            highlight = "border: 2px solid #00C2FF;" if v["valve_id"] == "V-12" else ""
            st.markdown(
                f"""
                <div class="scada-card" style="text-align:center; padding:0.6rem; {highlight}">
                    <div style="font-weight:700; font-size:0.95rem;">{v['valve_id']}</div>
                    <div style="font-size:0.75rem; color:#9FB3C8; margin-bottom:0.35rem;">{v['sector']}</div>
                    {status_badge(v['status'])}
                </div>
                """,
                unsafe_allow_html=True,
            )

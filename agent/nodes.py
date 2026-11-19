"""LangGraph Agent Nodes implementing the cognitive loop.

Nodes:
1. node_ingest: Reads verified telemetry and sanitized feeds (Layer 1).
2. node_reason: Synthesizes situation, drafts operator brief and action proposal (Layer 2).
3. node_stage_action: Submits proposal to single stage-gated write gateway (Layer 3).
4. node_replan: Handles gateway rejections, increments replan count (Max 2 replans).
"""
import json
from agent.state import AgentState
from agent.prompts import SYSTEM_PROMPT
from agent.llm_factory import llm_client
from tools.read_telemetry import read_network_telemetry
from tools.read_feeds import read_tariff_and_quality_feeds
from tools.write_gateway import stage_gated_valve_or_setpoint_action
from database.connection import transaction_scope
from guards.schedule_validator import validate_production_schedule
from config.constants import MAX_REPLANS, MAX_AGENT_STEPS


def node_ingest(state: AgentState) -> dict:
    """Ingest live network state using the two read-only tools."""
    current_hour = state.get("current_hour", 14)

    # Tool 1: Read Telemetry (cross-checked in pure Python + logged to audit_log)
    telemetry_data = read_network_telemetry(current_hour=current_hour, log_audit=True)

    # Tool 2: Read Feeds (sanitized by regex filter in pure Python + logged to audit_log)
    feeds_data = read_tariff_and_quality_feeds(horizon_hours=6, current_hour=current_hour, log_audit=True)

    return {
        "verified_telemetry": telemetry_data.get("verified_telemetry", []),
        "quarantined_sensors": telemetry_data.get("quarantined_sensors", []),
        "leak_alerts": telemetry_data.get("leak_alerts", []),
        "tariff_data": {
            "current_hour": feeds_data.get("current_hour"),
            "is_current_peak_tariff": feeds_data.get("is_current_peak_tariff"),
            "tariffs": feeds_data.get("tariffs", []),
            "demand_forecast": feeds_data.get("demand_forecast", []),
            "daily_windows": feeds_data.get("daily_windows", []),
            "water_quality": feeds_data.get("water_quality", {}),
        },
        "hourly_demand_24h": feeds_data.get("hourly_demand_24h", {}),
        "reservoir_status": feeds_data.get("reservoir", {}),
        "sanitized_alerts": feeds_data.get("sanitized_alerts", []),
        "agent_step_count": state.get("agent_step_count", 0) + 1,
    }


def node_reason(state: AgentState) -> dict:
    """Cognitive analysis: explain leak vs. fault and propose tariff schedule / physical actions."""
    user_context = {
        "scenario_id": state.get("scenario_id"),
        "current_hour": state.get("current_hour", 14),
        "reservoir_status": state.get("reservoir_status", {}),
        "leak_alerts": state.get("leak_alerts", []),
        "quarantined_sensors": state.get("quarantined_sensors", []),
        "sanitized_alerts": state.get("sanitized_alerts", []),
        "tariff_data": state.get("tariff_data", {}),
        "safety_violations_from_previous_attempts": state.get("safety_violations", []),
        "replan_count": state.get("replan_count", 0),
    }

    user_prompt = f"Analyze the following SCADA telemetry and feeds:\n{json.dumps(user_context, separators=(',', ':'))}"

    analysis, provider_used = llm_client.query(SYSTEM_PROMPT, user_prompt)

    action_prop = analysis.get("action_proposal")
    # If action proposal is NONE or missing, set to None
    if not isinstance(action_prop, dict) or str(action_prop.get("action_type") or "").strip().upper() in ("NONE", ""):
        action_prop = None

    proposed_schedule = analysis.get("proposed_schedule", "Baseline schedule.")

    # Pure Python deterministic validation of every proposed schedule block
    res_status = state.get("reservoir_status", {})
    wq = state.get("tariff_data", {}).get("water_quality", {})
    demand_list = [
        float(d["demand_mld"])
        for d in state.get("tariff_data", {}).get("demand_forecast", [])
        if "demand_mld" in d
    ]
    schedule_validation = validate_production_schedule(
        proposed_schedule=proposed_schedule,
        current_volume_ml=float(res_status.get("current_volume_ml", 240.0)),
        demand_by_hour=state.get("hourly_demand_24h", {}),
        fallback_demand_mld=demand_list or None,
        bloom_severity=str(wq.get("bloom_severity", "NONE")),
        turbidity_ntu=float(wq.get("intake_turbidity_ntu", 1.2)),
        chlorine_ppm=float(wq.get("intake_chlorine_ppm", 1.8)),
    )

    # Record LLM provider & reasoning pass in immutable audit_log
    scenario_label = f"SCENARIO_{state.get('scenario_id')}" if state.get("scenario_id") else "NETWORK"
    prop_summary = (
        f"{action_prop.get('action_type')} {action_prop.get('target_id')}={action_prop.get('proposed_value')}"
        if action_prop
        else "NONE"
    )
    with transaction_scope() as audit_conn:
        audit_conn.execute(
            """
            INSERT INTO audit_log (event_type, target_id, details, actor, status)
            VALUES (?, ?, ?, ?, ?);
            """,
            (
                "LLM_REASONING",
                scenario_label,
                (
                    f"Provider: {provider_used} | replan={state.get('replan_count', 0)} | "
                    f"proposal={prop_summary} | schedule_check={schedule_validation.get('status')}"
                ),
                "LLM_AGENT",
                "ALLOWED",
            ),
        )

    return {
        "last_user_prompt": user_prompt,
        "operator_brief": analysis.get("operator_brief", "Monitoring active."),
        "maintenance_advisory": analysis.get("maintenance_advisory", "No immediate maintenance."),
        "proposed_schedule": proposed_schedule,
        "schedule_validation": schedule_validation,
        "proposed_action": action_prop,
        "llm_provider": provider_used,
        "agent_step_count": state.get("agent_step_count", 0) + 1,
    }


def node_stage_action(state: AgentState) -> dict:
    """Submit proposal exclusively to the stage-gated write gateway."""
    action = state.get("proposed_action")

    if not action:
        return {
            "status": "COMPLETED",
            "agent_step_count": state.get("agent_step_count", 0) + 1,
        }

    # Gateway call — only 5 params; safety re-checks run inside the gateway
    raw_val = action.get("proposed_value")
    try:
        proposed_value = float(raw_val) if raw_val is not None else 0.0
    except (TypeError, ValueError):
        proposed_value = 0.0

    result = stage_gated_valve_or_setpoint_action(
        action_type=str(action.get("action_type") or ""),
        target_id=str(action.get("target_id") or ""),
        proposed_value=proposed_value,
        rationale=str(action.get("rationale") or "Proposed by AquaGrid Agent"),
    )

    history = list(state.get("proposal_history", []))
    history.append({
        "attempt": len(history) + 1,
        "replan_count": state.get("replan_count", 0),
        "action_proposal": action,
        "gateway_response": result,
    })

    if result.get("status") in ("STAGED_PENDING_APPROVAL", "REJECTED_DUPLICATE_PENDING"):
        return {
            "gateway_response": result,
            "proposal_history": history,
            "status": "AWAITING_HUMAN_APPROVAL",
            "agent_step_count": state.get("agent_step_count", 0) + 1,
        }
    else:  # REJECTED_BY_SAFETY_GUARD or REJECTED_INVALID_TARGET
        violations = list(state.get("safety_violations", []))
        violations.append(result.get("reason", "Safety breach"))
        return {
            "gateway_response": result,
            "proposal_history": history,
            "safety_violations": violations,
            "status": "ABORTED_BY_SAFETY",
            "agent_step_count": state.get("agent_step_count", 0) + 1,
        }


def node_replan(state: AgentState) -> dict:
    """Increment replan count after gateway rejection and prepare next loop."""
    new_replan_count = state.get("replan_count", 0) + 1
    new_step_count = state.get("agent_step_count", 0) + 1

    if new_replan_count >= MAX_REPLANS or new_step_count >= MAX_AGENT_STEPS:
        return {
            "replan_count": new_replan_count,
            "agent_step_count": new_step_count,
            "status": "ESCALATED_TO_HUMAN",
        }

    return {
        "replan_count": new_replan_count,
        "agent_step_count": new_step_count,
        "status": "RUNNING",
    }

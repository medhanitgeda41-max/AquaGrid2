"""LangGraph StateGraph builder for AquaGrid Orchestration Agent.

Enforces loop bounds (MAX_REPLANS = 2, MAX_STEPS = 5) and strict node transitions.
"""
from langgraph.graph import StateGraph, END
from agent.state import AgentState
from agent.nodes import node_ingest, node_reason, node_stage_action, node_replan
from config.constants import MAX_REPLANS, MAX_AGENT_STEPS


def should_replan_or_end(state: AgentState) -> str:
    """Conditional router determining whether to replan, wait for human, or end."""
    status = state.get("status")

    if status == "AWAITING_HUMAN_APPROVAL":
        return END
    elif status == "COMPLETED":
        return END
    elif status == "ABORTED_BY_SAFETY":
        replan_count = state.get("replan_count", 0)
        step_count = state.get("agent_step_count", 0)
        if replan_count >= MAX_REPLANS or step_count >= MAX_AGENT_STEPS:
            return END
        return "replan"
    elif status == "ESCALATED_TO_HUMAN":
        return END

    return END


def build_aquagrid_graph():
    """Build and compile the LangGraph agent graph."""
    workflow = StateGraph(AgentState)

    # Register Nodes
    workflow.add_node("ingest", node_ingest)
    workflow.add_node("reason", node_reason)
    workflow.add_node("stage_action", node_stage_action)
    workflow.add_node("replan", node_replan)

    # Set Entry Point
    workflow.set_entry_point("ingest")

    # Connect Edges
    workflow.add_edge("ingest", "reason")
    workflow.add_edge("reason", "stage_action")

    # Conditional Routing from stage_action
    workflow.add_conditional_edges(
        "stage_action",
        should_replan_or_end,
        {
            "replan": "replan",
            END: END,
        },
    )

    # From replan, re-enter reason node to reformulate proposal
    workflow.add_edge("replan", "reason")

    return workflow.compile()


# Global compiled graph instance
aquagrid_graph = build_aquagrid_graph()


def run_agent(scenario_id: int | None = None, current_hour: int = 14) -> AgentState:
    """Execute the AquaGrid agent on the current network state."""
    initial_state: AgentState = {
        "scenario_id": scenario_id,
        "current_hour": current_hour,
        "llm_provider": "Initializing",
        "verified_telemetry": [],
        "quarantined_sensors": [],
        "leak_alerts": [],
        "tariff_data": {},
        "hourly_demand_24h": {},
        "reservoir_status": {},
        "sanitized_alerts": [],
        "last_user_prompt": "",
        "operator_brief": "",
        "maintenance_advisory": "",
        "proposed_schedule": "",
        "schedule_validation": None,
        "proposed_action": None,
        "gateway_response": None,
        "proposal_history": [],
        "safety_violations": [],
        "replan_count": 0,
        "agent_step_count": 0,
        "status": "RUNNING",
    }

    final_state = aquagrid_graph.invoke(initial_state)
    return final_state

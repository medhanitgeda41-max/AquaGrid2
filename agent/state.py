"""LangGraph Agent State schema using Pydantic / TypedDict."""
from typing import TypedDict, Any, Optional


class AgentState(TypedDict):
    """Execution state passed between LangGraph agent nodes."""
    # Run context & mode
    scenario_id: Optional[int]
    current_hour: int
    llm_provider: str

    # Ingested Data (Layer 1 output)
    verified_telemetry: list[dict]
    quarantined_sensors: list[dict]
    leak_alerts: list[dict]
    tariff_data: dict
    hourly_demand_24h: dict[int, float]
    reservoir_status: dict
    sanitized_alerts: list[dict]

    # Cognitive Reasoning (Layer 2 output)
    last_user_prompt: str
    operator_brief: str
    maintenance_advisory: str
    proposed_schedule: str
    schedule_validation: Optional[dict]
    proposed_action: Optional[dict]

    # Staging & Gateway Execution (Layer 3 output)
    gateway_response: Optional[dict]
    proposal_history: list[dict]
    safety_violations: list[str]

    # Loop guardrails
    replan_count: int
    agent_step_count: int
    status: str  # 'RUNNING', 'AWAITING_HUMAN_APPROVAL', 'ABORTED_BY_SAFETY', 'COMPLETED', 'ESCALATED_TO_HUMAN'

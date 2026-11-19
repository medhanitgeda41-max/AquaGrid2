"""AquaGrid Architectural Tools & Gateway Package.

Exposes exactly two read-only telemetry tools and one stage-gated write gateway.
Direct writes to actuators or database tables outside this gateway are strictly forbidden.
"""
from tools.read_telemetry import read_network_telemetry
from tools.read_feeds import read_tariff_and_quality_feeds
from tools.write_gateway import stage_gated_valve_or_setpoint_action

__all__ = [
    "read_network_telemetry",
    "read_tariff_and_quality_feeds",
    "stage_gated_valve_or_setpoint_action",
]

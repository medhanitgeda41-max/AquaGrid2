-- AquaGrid SQLite SCADA & Safety Schema
PRAGMA foreign_keys = ON;

-- Strategic Storage Reservoirs
CREATE TABLE IF NOT EXISTS reservoirs (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    capacity_ml REAL NOT NULL,
    volume_ml REAL NOT NULL,
    level_percent REAL NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Hourly Electricity Tariffs ($/kWh)
CREATE TABLE IF NOT EXISTS tariffs (
    hour INTEGER PRIMARY KEY,
    rate_per_kwh REAL NOT NULL,
    is_peak INTEGER NOT NULL DEFAULT 0
);

-- Hourly Urban Water Demand Forecast (MLD)
CREATE TABLE IF NOT EXISTS demand_forecast (
    hour INTEGER PRIMARY KEY,
    demand_mld REAL NOT NULL
);

-- Sensor Registry & Metadata
CREATE TABLE IF NOT EXISTS sensors (
    sensor_id TEXT PRIMARY KEY,
    sensor_type TEXT NOT NULL, -- 'pressure', 'flow', 'turbidity', 'chlorine'
    junction_id TEXT NOT NULL,
    sector TEXT NOT NULL,
    unit TEXT NOT NULL,
    nominal_min REAL NOT NULL,
    nominal_max REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'ACTIVE' -- 'ACTIVE', 'QUARANTINED', 'FAULT'
);

-- Real-time & Historical Telemetry Frames
CREATE TABLE IF NOT EXISTS telemetry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    hour INTEGER NOT NULL,
    sensor_id TEXT NOT NULL,
    junction_id TEXT NOT NULL,
    sector TEXT NOT NULL,
    value REAL NOT NULL,
    unit TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'NORMAL', -- 'NORMAL', 'FLATLINE', 'DRIFT', 'OUT_OF_BOUNDS', 'QUARANTINED'
    FOREIGN KEY (sensor_id) REFERENCES sensors(sensor_id)
);

-- Water Quality Alerts & Operator Logs
CREATE TABLE IF NOT EXISTS quality_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    severity TEXT NOT NULL, -- 'LOW', 'MODERATE', 'CRITICAL'
    location TEXT NOT NULL,
    raw_text TEXT NOT NULL,
    sanitized_text TEXT NOT NULL,
    is_injection INTEGER NOT NULL DEFAULT 0
);

-- Controllable Network Isolation Valves
CREATE TABLE IF NOT EXISTS valves (
    valve_id TEXT PRIMARY KEY,
    sector TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'OPEN', -- 'OPEN', 'CLOSED'
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Desalination Plant Production Setpoints
CREATE TABLE IF NOT EXISTS plant_setpoints (
    plant_id TEXT PRIMARY KEY,
    production_mld REAL NOT NULL,
    max_capacity_mld REAL NOT NULL,
    derating_factor REAL NOT NULL DEFAULT 1.0,
    status TEXT NOT NULL DEFAULT 'ONLINE', -- 'ONLINE', 'THROTTLED', 'OFFLINE'
    last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Gated Pending Actions (HITL Queue)
CREATE TABLE IF NOT EXISTS pending_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action_type TEXT NOT NULL, -- 'CLOSE_VALVE', 'OPEN_VALVE', 'SET_PLANT_OUTPUT'
    target_id TEXT NOT NULL,   -- 'V-01'..'V-12', 'DESAL-01'
    proposed_value REAL NOT NULL,
    current_value REAL NOT NULL,
    rationale TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING', -- 'PENDING', 'APPROVED', 'REJECTED', 'CANCELLED_BY_SAFETY_RECHECK'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    executed_at TIMESTAMP,
    approver TEXT
);

-- Immutable SCADA & Agent Audit Trail
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    event_type TEXT NOT NULL, -- 'GATEWAY_PROPOSAL', 'SAFETY_CHECK', 'INJECTION_BLOCKED', 'OPERATOR_ACTION', etc.
    target_id TEXT,
    details TEXT NOT NULL,
    actor TEXT NOT NULL, -- 'LLM_AGENT', 'CODE_GUARD', 'HUMAN_OPERATOR'
    status TEXT NOT NULL -- 'ALLOWED', 'BLOCKED', 'PENDING', 'APPROVED', 'REJECTED'
);

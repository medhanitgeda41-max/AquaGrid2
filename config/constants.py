"""Physical limits, network constants, and architectural invariants for AquaGrid."""

# Safety Reserves & Reservoir Constraints
RESERVOIR_FLOOR_PERCENT: float = 0.35  # Non-negotiable 35% strategic reserve floor
RESERVOIR_TOTAL_CAPACITY_ML: float = 500.0  # Megalitres
RESERVOIR_FLOOR_ML: float = RESERVOIR_TOTAL_CAPACITY_ML * RESERVOIR_FLOOR_PERCENT  # 175.0 ML

# Desalination Plant Capacity (MLD = Megalitres per day)
DESAL_MAX_CAPACITY_MLD: float = 120.0
DESAL_BASELINE_OUTPUT_MLD: float = 100.0
DESAL_THROTTLED_OUTPUT_MLD: float = 40.0

# Potable Water Quality Thresholds (Australian / WHO Standards)
TURBIDITY_MAX_NTU: float = 4.0  # Nephelometric Turbidity Units
CHLORINE_MIN_PPM: float = 0.5   # Parts per million (free chlorine)
CHLORINE_MAX_PPM: float = 4.0

# Hydraulic Network Pressure Limits (psi)
PRESSURE_MIN_PSI: float = 20.0
PRESSURE_MAX_PSI: float = 100.0
PRESSURE_NOMINAL_MIN_PSI: float = 45.0
PRESSURE_NOMINAL_MAX_PSI: float = 65.0

# Tariff Windows & Default Operational Time
PEAK_TARIFF_START_HOUR: int = 14  # 2:00 PM
PEAK_TARIFF_END_HOUR: int = 18    # 6:00 PM
DEFAULT_SCADA_HOUR: int = 14      # Live operational scenario baseline hour (2:00 PM)

# Architectural Loop Guardrails
MAX_AGENT_STEPS: int = 5
MAX_REPLANS: int = 2

# Gateway Allowed Whitelists
ALLOWED_ACTION_TYPES: tuple[str, ...] = (
    "CLOSE_VALVE",
    "OPEN_VALVE",
    "SET_PLANT_OUTPUT",
)

KNOWN_VALVES: tuple[str, ...] = tuple(f"V-{i:02d}" for i in range(1, 13))
KNOWN_PLANTS: tuple[str, ...] = ("DESAL-01",)
KNOWN_TARGET_IDS: tuple[str, ...] = KNOWN_VALVES + KNOWN_PLANTS

KNOWN_SECTORS: tuple[str, ...] = ("Sector 1", "Sector 2", "Sector 3", "Sector 4")

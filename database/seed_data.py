"""Deterministic synthetic dataset generator for AquaGrid with fixed seed (42)."""
import random
import sqlite3
from config.constants import (
    RESERVOIR_TOTAL_CAPACITY_ML,
    DESAL_BASELINE_OUTPUT_MLD,
    DESAL_MAX_CAPACITY_MLD,
    PEAK_TARIFF_START_HOUR,
    PEAK_TARIFF_END_HOUR,
    KNOWN_VALVES,
)
from database.connection import init_db, transaction_scope


def seed_database(db_path: str | None = None) -> None:
    """Populate database with a realistic 24-hour baseline using seed(42)."""
    init_db(db_path)
    random.seed(42)

    with transaction_scope(db_path) as conn:
        # Clear existing data
        for table in (
            "audit_log",
            "pending_actions",
            "quality_alerts",
            "telemetry",
            "sensors",
            "valves",
            "plant_setpoints",
            "demand_forecast",
            "tariffs",
            "reservoirs",
        ):
            conn.execute(f"DELETE FROM {table};")

        # 1. Strategic Reservoir (Starts at 48% at 14:00 = 240.0 ML)
        start_level_percent = 48.0
        start_volume_ml = RESERVOIR_TOTAL_CAPACITY_ML * (start_level_percent / 100.0)
        conn.execute(
            """
            INSERT INTO reservoirs (id, name, capacity_ml, volume_ml, level_percent)
            VALUES (?, ?, ?, ?, ?);
            """,
            ("RES-01", "Coastal Strategic Storage Reservoir", RESERVOIR_TOTAL_CAPACITY_ML, start_volume_ml, start_level_percent),
        )

        # 2. Hourly Tariffs (Peak between 14:00 and 18:00)
        for h in range(24):
            is_peak = 1 if (PEAK_TARIFF_START_HOUR <= h <= PEAK_TARIFF_END_HOUR) else 0
            if is_peak:
                rate = 0.48
            elif 0 <= h < 6:
                rate = 0.09 + round(random.uniform(-0.01, 0.02), 3)
            else:
                rate = 0.20 + round(random.uniform(-0.02, 0.02), 3)

            conn.execute(
                "INSERT INTO tariffs (hour, rate_per_kwh, is_peak) VALUES (?, ?, ?);",
                (h, rate, is_peak),
            )

        # 3. Demand Forecast (MLD across 24h)
        for h in range(24):
            if 0 <= h < 6:
                demand = 45.0 + random.uniform(0.0, 5.0)
            elif 6 <= h < 10:
                demand = 92.0 + random.uniform(0.0, 6.0)
            elif 10 <= h < 16:
                demand = 84.0 + random.uniform(0.0, 4.0)
            elif 16 <= h < 21:
                demand = 96.0 + random.uniform(0.0, 7.0)
            else:
                demand = 60.0 + random.uniform(0.0, 5.0)

            conn.execute(
                "INSERT INTO demand_forecast (hour, demand_mld) VALUES (?, ?);",
                (h, round(demand, 2)),
            )

        # 4. Sensor Registry (20 Junctions across 4 Sectors + Raw Water Intakes)
        # J-01..J-05 -> Sector 1, J-06..J-10 -> Sector 2, J-11..J-13 -> Sector 3, J-14..J-20 -> Sector 4
        sensors_to_insert = []
        for i in range(1, 21):
            j_id = f"J-{i:02d}"
            sector = "Sector 4" if i >= 14 else f"Sector {(i - 1) // 5 + 1}"
            # Pressure sensor
            sensors_to_insert.append((f"P-{i:02d}", "pressure", j_id, sector, "psi", 45.0, 65.0, "ACTIVE"))
            # Flow sensor
            sensors_to_insert.append((f"F-{i:02d}", "flow", j_id, sector, "L/s", 80.0, 140.0, "ACTIVE"))

        # Intake water quality sensors
        sensors_to_insert.append(("T-INTAKE-1", "turbidity", "INTAKE-01", "Coastal Intake", "NTU", 0.5, 4.0, "ACTIVE"))
        sensors_to_insert.append(("T-INTAKE-2", "turbidity", "INTAKE-02", "Coastal Intake", "NTU", 0.5, 4.0, "ACTIVE"))
        sensors_to_insert.append(("CL-INTAKE-1", "chlorine", "INTAKE-01", "Coastal Intake", "ppm", 0.5, 3.5, "ACTIVE"))
        sensors_to_insert.append(("CL-INTAKE-2", "chlorine", "INTAKE-02", "Coastal Intake", "ppm", 0.5, 3.5, "ACTIVE"))

        conn.executemany(
            """
            INSERT INTO sensors (sensor_id, sensor_type, junction_id, sector, unit, nominal_min, nominal_max, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?);
            """,
            sensors_to_insert,
        )

        # 5. Natural 24h Baseline Telemetry
        telemetry_records = []
        for h in range(24):
            for s in sensors_to_insert:
                s_id, s_type, j_id, sector, unit, n_min, n_max, _ = s
                if s_type == "pressure":
                    val = 55.0 + random.uniform(-2.5, 2.5)
                elif s_type == "flow":
                    val = 110.0 + random.uniform(-6.0, 6.0)
                elif s_type == "turbidity":
                    val = 1.2 + random.uniform(-0.2, 0.2)
                elif s_type == "chlorine":
                    val = 1.8 + random.uniform(-0.15, 0.15)
                else:
                    val = 50.0

                telemetry_records.append((h, s_id, j_id, sector, round(val, 2), unit, "NORMAL"))

        conn.executemany(
            """
            INSERT INTO telemetry (hour, sensor_id, junction_id, sector, value, unit, status)
            VALUES (?, ?, ?, ?, ?, ?, ?);
            """,
            telemetry_records,
        )

        # 6. Network Isolation Valves (V-01 through V-12, all OPEN)
        valves_to_insert = []
        for i, v_name in enumerate(KNOWN_VALVES, 1):
            sector = f"Sector {(i - 1) // 3 + 1}"
            valves_to_insert.append((v_name, sector, "OPEN"))

        conn.executemany(
            "INSERT INTO valves (valve_id, sector, status) VALUES (?, ?, ?);",
            valves_to_insert,
        )

        # 7. Desalination Plant Setpoint (DESAL-01 at 100.0 MLD)
        conn.execute(
            """
            INSERT INTO plant_setpoints (plant_id, production_mld, max_capacity_mld, derating_factor, status)
            VALUES (?, ?, ?, ?, ?);
            """,
            ("DESAL-01", DESAL_BASELINE_OUTPUT_MLD, DESAL_MAX_CAPACITY_MLD, 1.0, "ONLINE"),
        )

        # 8. Baseline Audit Record
        conn.execute(
            """
            INSERT INTO audit_log (event_type, target_id, details, actor, status)
            VALUES (?, ?, ?, ?, ?);
            """,
            ("DATABASE_SEEDED", "ALL", "Synthetic water network initialized with fixed seed 42", "CODE_GUARD", "ALLOWED"),
        )


if __name__ == "__main__":
    seed_database()
    print("Database successfully seeded with fixed seed 42.")

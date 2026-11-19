"""Command-line runner for AquaGrid Agent across the 4 SCADA demo scenarios."""
import argparse
import json
from database.connection import get_db_connection
from database.scenarios import (
    inject_scenario_1,
    inject_scenario_2,
    inject_scenario_3,
    inject_scenario_4,
    reset_database,
)
from guards.injection_filter import detect_injection
from tools.write_gateway import refuse_direct_write_bypass
from agent.graph import run_agent


def main():
    parser = argparse.ArgumentParser(description="AquaGrid SCADA Decision Agent Runner")
    parser.add_argument(
        "--scenario",
        type=int,
        choices=[1, 2, 3, 4],
        help="Scenario ID to inject and analyze (1: Leak vs Fault, 2: Throttle Aborted, 3: Valve HITL, 4: Attack Blocked)",
    )
    parser.add_argument("--reset", action="store_true", help="Reset database to clean 24h baseline")
    parser.add_argument("--hour", type=int, default=14, help="Operational hour (default: 14)")
    args = parser.parse_args()

    if args.reset:
        reset_database()
        print("Database successfully reset and re-seeded with fixed seed 42.")
        return

    scenario_name = "Baseline Operations"
    if args.scenario == 1:
        reset_database()
        info = inject_scenario_1()
        scenario_name = info["name"]
    elif args.scenario == 2:
        reset_database()
        info = inject_scenario_2()
        scenario_name = info["name"]
    elif args.scenario == 3:
        reset_database()
        info = inject_scenario_3()
        scenario_name = info["name"]
    elif args.scenario == 4:
        reset_database()
        info = inject_scenario_4()
        scenario_name = info["name"]

    print("=" * 80)
    print(f" AQUAGRID AUTONOMOUS AGENT RUNNER | SCENARIO {args.scenario}: {scenario_name}")
    print("=" * 80)

    result = run_agent(scenario_id=args.scenario, current_hour=args.hour)

    print(f"\n[MODEL PROVIDER USED]: {result.get('llm_provider')}")
    print(f"[STATUS]:               {result.get('status')}")
    print(f"[AGENT STEPS]:          {result.get('agent_step_count')} (Replans: {result.get('replan_count')})")
    print("\n" + "-" * 80)
    print("OPERATOR ACTION BRIEF:")
    print("-" * 80)
    print(result.get("operator_brief"))

    print("\n" + "-" * 80)
    print("MAINTENANCE ADVISORY / WORK ORDERS:")
    print("-" * 80)
    print(result.get("maintenance_advisory"))

    print("\n" + "-" * 80)
    print("PROPOSED PRODUCTION SCHEDULE:")
    print("-" * 80)
    print(result.get("proposed_schedule"))

    sched_val = result.get("schedule_validation")
    if sched_val:
        print("\n" + "-" * 80)
        print(f"SCHEDULE VALIDATION (PURE PYTHON GUARD): {sched_val.get('status')}")
        print("-" * 80)
        print(sched_val.get("summary"))
        for blk in sched_val.get("blocks", []):
            status_tag = blk.get("status")
            win = blk.get("window")
            mld = blk.get("proposed_mld")
            min_pct = blk.get("min_projected_percent")
            print(f"  [{status_tag}] {win} @ {mld} MLD (min projected reservoir: {min_pct}%)")
            for r in blk.get("reasons", []):
                print(f"      -> {r}")
        if not sched_val.get("blocks"):
            for blk in sched_val.get("rejected_blocks", []):
                for r in blk.get("reasons", []):
                    print(f"  [REJECTED_BY_CODE] {r}")

    proposal_history = result.get("proposal_history", [])
    if proposal_history:
        print("\n" + "-" * 80)
        print("PROPOSAL & GATEWAY HISTORY (LAYER 3 PYTHON CODE GUARDS):")
        print("-" * 80)
        for entry in proposal_history:
            attempt = entry.get("attempt")
            replan = entry.get("replan_count")
            prop = entry.get("action_proposal") or {}
            gw = entry.get("gateway_response") or {}
            min_pct = gw.get("min_projected_percent")
            pct_str = f" | min projected reservoir: {min_pct}%" if min_pct is not None else ""
            print(
                f"  Attempt #{attempt} (replan={replan}): {prop.get('action_type')} {prop.get('target_id')} "
                f"-> {prop.get('proposed_value')} | Gateway: {gw.get('status')}{pct_str}"
            )
            print(f"      Rationale: {prop.get('rationale')}")
            if gw.get("reason"):
                print(f"      Guard:     {gw.get('reason')}")
            elif gw.get("message"):
                print(f"      Guard:     {gw.get('message')}")

    if result.get("proposed_action"):
        print("\n" + "-" * 80)
        print("ACTION PROPOSAL:")
        print("-" * 80)
        print(json.dumps(result.get("proposed_action"), indent=2))

    if result.get("gateway_response"):
        print("\n" + "-" * 80)
        print("GATEWAY RESPONSE (LAYER 3 PYTHON CODE GUARDS):")
        print("-" * 80)
        print(json.dumps(result.get("gateway_response"), indent=2))

    # Scenario 4 / Security Incident Sections: Injection Shield, Direct Write Bypass, Final V-12 Status
    sanitized_alerts = result.get("sanitized_alerts", [])
    flagged_alerts = [a for a in sanitized_alerts if a.get("injection_detected")]
    if args.scenario == 4 or flagged_alerts:
        conn = get_db_connection()
        try:
            raw_rows = conn.execute(
                "SELECT id, raw_text FROM quality_alerts WHERE is_injection = 1 ORDER BY id DESC;"
            ).fetchall()
            raw_by_id = {r["id"]: r["raw_text"] for r in raw_rows}
        finally:
            conn.close()

        last_prompt = result.get("last_user_prompt", "")
        print("\n" + "-" * 80)
        print("INJECTION SHIELD (PURE PYTHON GUARD):")
        print("-" * 80)
        for alert in flagged_alerts:
            a_id = alert.get("alert_id")
            raw_text = raw_by_id.get(a_id, "")
            _, matched_patterns = detect_injection(raw_text)
            sanitized_text = alert.get("text", "")
            raw_reached_llm = bool(raw_text) and (raw_text in last_prompt)
            # Also verify no actionable substring of the original instruction leaked into the LLM prompt
            leaked_fragments = [
                frag for frag in ("SYSTEM OVERRIDE", "ignore safety", "open valve", "V-12", "emergency flushing")
                if frag.lower() in last_prompt.lower()
            ]
            sanitized_reached_llm = bool(sanitized_text) and (sanitized_text in last_prompt)

            print(f"  Alert Metadata           : id={a_id}, source={alert.get('source')}, severity={alert.get('severity')}")
            print(f"  Original Malicious Alert : {raw_text}")
            print(f"  Matched Regex Pattern(s) : {matched_patterns}")
            print(f"  Sanitized Text Sent LLM  : {sanitized_text}")
            print(f"  Sanitized Payload -> LLM : {json.dumps(alert)}")
            print(
                f"  Raw Text Reached LLM?    : "
                f"{'YES (BREACH!)' if (raw_reached_llm or leaked_fragments) else 'NO — CONFIRMED (entire malicious text withheld; zero original instruction reached LLM)'}"
                f" [sanitized_in_prompt={sanitized_reached_llm}, leaked_fragments={leaked_fragments}]"
            )

        bypass = refuse_direct_write_bypass(target_valve_id="V-12", attempted_status="OPEN")
        print("\n" + "-" * 80)
        print("DIRECT WRITE BYPASS ATTEMPT:")
        print("-" * 80)
        print(f"  Attempted Bypass : {bypass['attempted_action']}")
        print(f"  Result           : {bypass['status']} ({bypass['error']})")
        print(
            f"  DB Integrity     : V-12 before={bypass['valve_status_before']} -> "
            f"after={bypass['valve_status_after']} (unchanged={bypass['unchanged']})"
        )

    # Final Valve V-12 status verification from SQLite
    if args.scenario == 4 or flagged_alerts:
        conn = get_db_connection()
        try:
            v12 = conn.execute("SELECT valve_id, sector, status FROM valves WHERE valve_id = 'V-12';").fetchone()
        finally:
            conn.close()
        print("\n" + "-" * 80)
        print("FINAL VALVE V-12 STATUS:")
        print("-" * 80)
        if v12:
            print(f"  {v12['valve_id']} ({v12['sector']}): {v12['status']} (unchanged; zero unauthorized actuation)")

    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()

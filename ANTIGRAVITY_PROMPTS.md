# AquaGrid: prompts to paste into Google Antigravity

Paste one prompt at a time. Wait for the agent to finish and stop, do the checkpoint, then move on.
Model setting: **Planning** = Gemini 3.8 Flash, thinking **High**. **Coding** = Gemini 3.8 Flash, thinking **Low or Medium**.
Commit to Git after every checkpoint that passes.

---

## Prompt 1: write the plan (Planning model)
Attach `PROBLEM_STATEMENT.md` and `All_project_starting_prompt.md`, then paste:

```
Read PROBLEM_STATEMENT.md (our project, including the "Our team's decisions" section)
and All_project_starting_prompt.md. Follow the starting prompt to create PLAN.md for
AquaGrid and save it in this folder. Do not write any application code yet.

Hard requirements the plan must keep:
- Exactly two read-only tools (read_network_telemetry, read_tariff_and_quality_feeds)
  and one write gateway (stage_gated_valve_or_setpoint_action). No other code may
  write to valves, setpoints or the database tables they control.
- Sensor checks, the 35% reservoir floor, water-quality limits and the regex
  injection filter are pure Python, never the LLM.
- Every valve or plant setpoint change waits for human Approve/Reject in Streamlit.
- The 4 demo scenarios listed in PROBLEM_STATEMENT.md each get a one-click button.
- Clearly label in the plan which step is done by the LLM, by code, or by a human.
End with your assumptions and ask me to confirm them.
```

**Checkpoint:** read PLAN.md. Check the 3 tools, the 35% floor, the human approval and the 4 scenarios are all there. Reply with corrections or "Confirmed".

---

## Prompt 2: Phase 1, setup and fake data (Coding model)
```
Follow PLAN.md. Build Phase 1 only: .gitignore, .env.example, requirements.txt,
src/config.py (all limits, e.g. RESERVOIR_FLOOR_PCT = 35), src/schemas.py,
src/db.py and src/seed_data.py that creates coastal_water_network.sqlite with a
fixed random seed and every injected fault from PROBLEM_STATEMENT.md
(Sector 4 leak, flatlined P-17, drifting intake sensor, negative-pressure reading,
algal-bloom alert, field-crew text, injection alert). Then stop and tell me how
to run the seed script and what to check.
```
**Checkpoint:** copy `.env.example` to `.env` and add your keys. Run the seed script. Open the .sqlite file in *DB Browser for SQLite* and check the tricky cases are really there.

---

## Prompt 3: Phase 2, tools, guards and tests (Coding model)
```
Follow PLAN.md. Build Phase 2 only: src/tools.py (the 2 read-only tools and the
single write gateway, which stores actions as PENDING and only executes after
approval, inside a SQLite transaction with rollback), src/guards.py (injection
regex, flatline, drift, rate-of-change, impossible values, mass balance
leak-vs-sensor, reservoir-floor forecast, water-quality and algal-bloom rules),
and tests/test_guards.py with pytest. Keep all earlier files working. Then stop
and tell me how to run the tests.
```
**Checkpoint:** run `python -m pytest`. Check by hand: does the throttle really push the reservoir to about 31% and get blocked? Is P-17 flagged as flatlined? Is the leak found in Sector 4?

---

## Prompt 4: Phase 3, AI brain, workflow and terminal demo (Coding model)
```
Follow PLAN.md. Build Phase 3 only: src/llm_client.py (fallback chain Groq ->
Groq 8B -> Gemini -> Ollama qwen3:8b, 30-60 s timeout, max_retries=1, catches
broken JSON, plus an offline fallback so the demo runs with no internet),
src/workflow.py (LangGraph flow: trigger -> validate -> plan/act loop capped at
5 steps -> guard check -> auto-safe or human-approval interrupt -> write gateway
-> audit log; replans capped at 2), cli.py with a --demo flag running the 4
scenarios, and tests/test_workflow.py. The LLM only does the 4 jobs listed in
PROBLEM_STATEMENT.md. Then stop.
```
**Checkpoint:** make sure Ollama is running, then run `python cli.py --demo`. Check that the injection alert is blocked, the throttle is aborted, and the valve stays PENDING.

---

## Prompt 5: Phase 4, Streamlit control room (Coding model)
```
Follow PLAN.md. Build Phase 4 only: app.py, a Streamlit "SCADA control room" with
(1) live tiles for reservoir %, tariff now, active alerts and quarantined sensors,
(2) one-click buttons for the 4 demo scenarios, (3) a live step-by-step trace with
badges showing LLM vs CODE vs HUMAN for each step and the exact numbers checked
(e.g. "forecast 31% < 35% floor -> ABORTED"), (4) an Approve/Reject card for
pending valve/setpoint actions showing the before -> after change, (5) the LLM's
operator brief and maintenance advisory, (6) the audit log, (7) a "Reset and
re-seed database" button. Keep all tests passing. Then stop.
```
**Checkpoint:** run `python -m streamlit run app.py` and open http://localhost:8501. Click every scenario. Decide which stretch goal to try, or cut scope if time is short.

---

## Prompt 6+: stretch goals, one at a time
**Step A (Planning model):**
```
Write a markdown spec file an AI coding agent can follow for this feature, saved as
CREW_DISPATCH.md: automatic field crew dispatch and work-order generator that
prioritises high-loss pipe segments. Keep the LLM/code/human split from PLAN.md.
```
**Step B (Coding model):**
```
Read CREW_DISPATCH.md and implement it. Follow PLAN.md, keep all existing tests
passing, add tests for the new feature, and stop and tell me if anything in the
spec is unclear.
```
Repeat A and B for the other stretch goals, e.g. `WNTR_SIMULATION.md` (test a valve closure in a hydraulic simulation before staging it) or `ROI_DASHBOARD.md` (peak-tariff kWh saved without breaking the 35% reserve).

---

## Before the demo
Go through the checklist in section 11 of the TechX manual and tick every item.

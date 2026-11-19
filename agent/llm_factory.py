"""Multi-provider LLM Factory with dynamic fallback chains toggled by LLM_MODE.

Supports:
- Local Ollama (OLLAMA_MODEL, default qwen3:8b)
- Groq (GROQ_MODEL_1=openai/gpt-oss-120b, GROQ_MODEL_2=openai/gpt-oss-20b)
- Gemini (GEMINI_MODEL=gemini-3.8-flash via OpenAI-compatible endpoint)
- Deterministic Offline Rule-Based Mock Agent (guaranteed fail-safe execution)
"""
import json
import logging
import re
from typing import Any, Optional
from openai import OpenAI
from config.settings import settings

logger = logging.getLogger("aquagrid.llm_factory")


def _parse_json_response(raw_content: str) -> dict:
    """Parse JSON from model output, defensively stripping <think> tags and code fences."""
    cleaned = re.sub(r"<think>.*?</think>", "", raw_content or "", flags=re.DOTALL | re.IGNORECASE).strip()
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise


def _detect_scenario(user_prompt: str) -> int | None:
    """Extract scenario_id from the user prompt JSON or plain text."""
    import re
    # Match JSON key: "scenario_id": 1
    m = re.search(r'"scenario_id"\s*:\s*(\d+)', user_prompt)
    if m:
        return int(m.group(1))
    # Plain text match (e.g. "scenario 2")
    m = re.search(r'scenario\s+(\d)', user_prompt, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return None


def generate_offline_mock_response(system_prompt: str, user_prompt: str) -> dict:
    """Deterministic rule-based mock engine providing realistic reasoning outputs without external APIs."""
    user_lower = user_prompt.lower()
    scenario_id = _detect_scenario(user_prompt)

    if scenario_id == 1 or ("leak" in user_lower and "p-17" in user_lower):
        return {
            "operator_brief": (
                "DIAGNOSTIC ADVISORY: Sector 4 Junction J-14 exhibits a verified pipe leak signature "
                "(pressure dropped -26.5 psi while flow spiked +78.0 L/s). Sensor P-17 has flatlined "
                "with zero variance (48.12 psi) across consecutive timestamps and is quarantined. "
                "Intake sensor T-INTAKE-2 is drifting (4.85 NTU vs reference 1.25 NTU) and has been isolated."
            ),
            "maintenance_advisory": (
                "PRIORITY 1: Dispatch emergency repair crew to Sector 4 near Junction J-14 to investigate surface pooling; "
                "after operator approval, close V-12 to isolate the ruptured main. "
                "PRIORITY 2: Dispatch instrumentation technician to recalibrate or replace pressure transmitter P-17 "
                "and clean optical lens on Intake 02 turbidity analyzer."
            ),
            "proposed_schedule": (
                "00:00-06:00 at 115 MLD (off-peak ~$0.09/kWh), 06:00-14:00 at 95 MLD (mid-peak ~$0.20/kWh), "
                "14:00-18:00 at 85 MLD (peak $0.48/kWh; maintain pressure for Sector 4), 19:00-24:00 at 90 MLD."
            ),
            "action_proposal": {
                "action_type": "CLOSE_VALVE",
                "target_id": "V-12",
                "proposed_value": 0.0,
                "rationale": "Isolate ruptured distribution segment at J-14 in Sector 4 to stop uncontrolled water loss.",
            },
        }

    elif scenario_id == 2 or "algal bloom" in user_lower or "throttle" in user_lower:
        replan_match = re.search(r'"replan_count"\s*:\s*(\d+)', user_prompt)
        replan_count = int(replan_match.group(1)) if replan_match else 0
        if replan_count >= 1:
            return {
                "operator_brief": (
                    "REPLAN ADVISORY: Initial peak-tariff throttle breached the 35% strategic reservoir floor. "
                    "Replanning to highest safe desalination output within the Intake 2 algal-bloom derating limit (60.0 MLD, 50% capacity)."
                ),
                "maintenance_advisory": (
                    "Keep Intake 02 isolated during CRITICAL algal bloom while running Intake 01 at 60.0 MLD. "
                    "Maintain continuous turbidity monitoring."
                ),
                "proposed_schedule": (
                    "00:00-06:00 at 60 MLD (off-peak $0.09/kWh, bloom-capped), 06:00-14:00 at 60 MLD (mid-peak $0.20/kWh), "
                    "14:00-18:00 at 60 MLD (peak $0.48/kWh; highest bloom-safe output to protect 35% reservoir floor), "
                    "19:00-24:00 at 60 MLD (bloom-capped)."
                ),
                "action_proposal": {
                    "action_type": "SET_PLANT_OUTPUT",
                    "target_id": "DESAL-01",
                    "proposed_value": 60.0,
                    "rationale": (
                        "Replan after safety-floor rejection: set DESAL-01 to 60.0 MLD (maximum safe output under 50% Intake 2 bloom derating) "
                        "to keep reservoir storage >= 35% while still reducing peak-tariff draw from baseline 100 MLD."
                    ),
                },
            }
        return {
            "operator_brief": (
                "TARIFF & QUALITY ALERT: Peak electricity tariffs ($0.48/kWh) in effect from 14:00 to 18:00. "
                "Concurrently, satellite telemetry detected a coastal harmful algal bloom drifting near Intake 02. "
                "Agent proposed throttling desalination output from 100.0 MLD to 15.0 MLD for cost optimization."
            ),
            "maintenance_advisory": (
                "Monitor Intake 02 raw water quality continuously. Standby filtration backwash systems. "
                "Do not bypass automated reservoir safety floors."
            ),
            "proposed_schedule": (
                "00:00-06:00 at 115 MLD (off-peak ~$0.09/kWh), 06:00-14:00 at 95 MLD (mid-peak ~$0.20/kWh), "
                "14:00-18:00 throttle proposal to 15 MLD (peak $0.48/kWh; subject to 35% safety floor & 60 MLD bloom cap), "
                "19:00-24:00 at 60 MLD (bloom-derated)."
            ),
            "action_proposal": {
                "action_type": "SET_PLANT_OUTPUT",
                "target_id": "DESAL-01",
                "proposed_value": 15.0,
                "rationale": "Throttle production during peak electricity tariff window ($0.48/kWh) to minimize pumping expense.",
            },
        }

    elif scenario_id == 3 or "close_valve" in user_lower or "isolation" in user_lower:
        return {
            "operator_brief": (
                "EMERGENCY ISOLATION REQUEST: Major pipe breach confirmed in Sector 4. Hydraulic model recommends "
                "immediate closure of isolation valve V-12. Physical action staged in gateway awaiting operator signoff."
            ),
            "maintenance_advisory": (
                "After operator approval, close V-12 to isolate the Sector 4 rupture near J-14, and notify local utility "
                "dispatch that Sector 4 will experience reduced service pressure during repair."
            ),
            "proposed_schedule": "Keep Desalination Plant ONLINE at 100.0 MLD.",
            "action_proposal": {
                "action_type": "CLOSE_VALVE",
                "target_id": "V-12",
                "proposed_value": 0.0,
                "rationale": "Emergency isolation of Sector 4 distribution main near J-14 to halt active leak.",
            },
        }

    elif scenario_id == 4 or "injection" in user_lower or "adversarial" in user_lower:
        return {
            "operator_brief": (
                "SECURITY INCIDENT REPORT: Upstream text alert contained adversarial prompt injection syntax. "
                "The payload was neutralized by the Python regex filter before reaching model context. "
                "No unauthorized actuator changes were staged."
            ),
            "maintenance_advisory": "Report unauthorized external alert injection attempt to SCADA Cyber Operations.",
            "proposed_schedule": "00:00-24:00 at 100 MLD (security lockdown — baseline held, no actuator changes).",
            "action_proposal": {
                "action_type": "NONE",
                "target_id": "NONE",
                "proposed_value": 0.0,
                "rationale": "No physical action proposed due to malicious alert quarantine.",
            },
        }

    return {
        "operator_brief": "SCADA network operating normally. Pressure and flow across all sectors within standard tolerances.",
        "maintenance_advisory": "Routine monitoring active.",
        "proposed_schedule": "Maintain baseline production schedule.",
        "action_proposal": {"action_type": "NONE", "target_id": "NONE", "proposed_value": 0.0, "rationale": "No action required."},
    }


class LLMClient:
    """Multi-provider LLM client implementing the fallback chain."""

    def __init__(self, mode: Optional[str] = None):
        self._explicit_mode = mode

    @property
    def mode(self) -> str:
        return self._explicit_mode or settings.LLM_MODE

    def _get_provider_chain(self) -> list[dict]:
        """Define prioritized provider list based on LLM_MODE."""
        ollama_provider = {
            "name": f"Ollama ({settings.OLLAMA_MODEL})",
            "base_url": settings.OPENAI_BASE_URL,
            "api_key": "ollama",
            "model": settings.OLLAMA_MODEL,
            "timeout": max(settings.REQUEST_TIMEOUT, 240),
            "max_retries": 0,
            "extra_kwargs": {"reasoning_effort": "none"},
        }
        groq_primary = {
            "name": f"Groq ({settings.GROQ_MODEL_1})",
            "base_url": "https://api.groq.com/openai/v1",
            "api_key": settings.GROQ_API_KEY,
            "model": settings.GROQ_MODEL_1,
        }
        groq_secondary = {
            "name": f"Groq ({settings.GROQ_MODEL_2})",
            "base_url": "https://api.groq.com/openai/v1",
            "api_key": settings.GROQ_API_KEY,
            "model": settings.GROQ_MODEL_2,
        }
        gemini_provider = {
            "name": f"Gemini ({settings.GEMINI_MODEL})",
            "base_url": settings.GEMINI_BASE_URL,
            "api_key": settings.GEMINI_API_KEY,
            "model": settings.GEMINI_MODEL,
        }

        if self.mode == "demo":
            return [groq_primary, groq_secondary, gemini_provider, ollama_provider]
        else:  # dev mode (default)
            return [ollama_provider, groq_primary, groq_secondary, gemini_provider]

    @staticmethod
    def _has_real_api_key(api_key: str) -> bool:
        """Return True if api_key is set and not a .env.example placeholder."""
        key = (api_key or "").strip()
        return bool(key) and not key.lower().startswith("your_")

    def query(self, system_prompt: str, user_prompt: str) -> tuple[dict, str]:
        """
        Query LLM with automatic failover across providers.
        Falls back to deterministic offline engine if all remote endpoints fail or lack keys.
        """
        providers = self._get_provider_chain()

        for p in providers:
            # Skip cloud providers if API key is missing or still a placeholder
            if "groq" in p["name"].lower() and not self._has_real_api_key(p["api_key"]):
                continue
            if "gemini" in p["name"].lower() and not self._has_real_api_key(p["api_key"]):
                continue

            try:
                client = OpenAI(
                    base_url=p["base_url"],
                    api_key=p["api_key"],
                    timeout=p.get("timeout", settings.REQUEST_TIMEOUT),
                    max_retries=p.get("max_retries", settings.MAX_RETRIES),
                )
                request_kwargs: dict[str, Any] = {
                    "model": p["model"],
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "response_format": {"type": "json_object"},
                    "temperature": 0.1,
                }
                request_kwargs.update(p.get("extra_kwargs", {}))

                response = client.chat.completions.create(**request_kwargs)
                raw_content = response.choices[0].message.content or "{}"
                parsed = _parse_json_response(raw_content)
                return parsed, p["name"]
            except Exception as e:
                logger.warning(f"Provider {p['name']} failed: {e}. Trying next provider in fallback chain...")
                continue

        # Universal fallback: Deterministic rule-based engine
        logger.info("Using deterministic offline mock agent fallback.")
        mock_res = generate_offline_mock_response(system_prompt, user_prompt)
        return mock_res, "Deterministic Offline Engine"


llm_client = LLMClient()

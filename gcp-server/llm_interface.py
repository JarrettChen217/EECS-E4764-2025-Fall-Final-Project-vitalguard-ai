import json
import time
from typing import Dict, Any, List, Optional
from abc import ABC, abstractmethod
from openai import OpenAI, OpenAIError




# ======================= LLM INTERFACE & PROMPT BUILDER =======================
class LLMInterface(ABC):
    """LLM client abstract base class."""

    @abstractmethod
    def predict(self, prompt: str) -> str:
        """
        Low-level interface: send a raw prompt string to the LLM and return the raw response.
        """
        pass

    def analyze_vitals(
        self,
        current_status: Dict[str, str],
        history: Optional[List[Dict[str, Any]]] = None,
        user_profile: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        High-level helper for this project:
        - Build a structured LLM prompt from current vitals + history
        - Call predict()
        - Return the LLM raw response (expected JSON)
        """
        history = history or []
        user_profile = user_profile or {}

        prompt = build_health_prompt(
            current_status=current_status,
            history=history,
            user_profile=user_profile,
        )
        return self.predict(prompt)


def build_health_prompt(
    current_status: Dict[str, str],
    history: List[Dict[str, Any]],
    user_profile: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Build the LLM prompt in English:
    - Includes current discrete vital levels
    - Includes recent history (trend reference)
    - Instructs the assistant to provide:
        (1) Immediate actionable advice
        (2) Historical trend analysis
    - Requires strict JSON output for easy parsing
    """

    # ----------- Safe getters -----------
    def get_value(d: Dict[str, Any], key: str, default: str = "unknown") -> str:
        return str(d.get(key, default))

    # Current vitals
    cur_ts = get_value(current_status, "timestamp", "unknown")
    cur_hr = get_value(current_status, "heart_rate_level")
    cur_act = get_value(current_status, "activity_state")
    cur_sleep = get_value(current_status, "sleep_state")
    cur_temp = get_value(current_status, "temperature_status")
    cur_spo2 = get_value(current_status, "spo2_status")

    # Format history
    history_lines = []
    for idx, item in enumerate(history):
        line = (
            f"{idx + 1}. "
            f"time={get_value(item, 'timestamp')}, "
            f"HR={get_value(item, 'heart_rate_level')}, "
            f"Activity={get_value(item, 'activity_state')}, "
            f"Sleep={get_value(item, 'sleep_state')}, "
            f"Temp={get_value(item, 'temperature_status')}, "
            f"SpO2={get_value(item, 'spo2_status')}"
        )
        history_lines.append(line)

    history_block = "\n".join(history_lines) if history_lines else "No historical records available."

    # Optional user profile
    profile_block = "No additional user profile provided."
    if user_profile:
        profile_block = json.dumps(user_profile, ensure_ascii=False)

    # ----------- FINAL LLM PROMPT (ALL ENGLISH VERSION) -----------
    prompt = f"""
You are VitalGuard, a conservative, safety-oriented health monitoring assistant running on a wearable device.
You do NOT provide medical diagnoses and you do NOT reference diseases.  
You receive *discretized vital-sign levels* (not raw medical values).  
Your job is to give lifestyle advice and safety-oriented suggestions only.

Discrete levels you may receive:
- heart_rate_level: ["low", "normal", "high", "very_high"]
- activity_state: ["resting", "light_activity", "moderate_activity", "vigorous_activity"]
- sleep_state: ["awake", "light_sleep_candidate", "deep_sleep_candidate"]
- temperature_status: ["normal", "slightly_elevated", "elevated"]
- spo2_status: ["normal", "slightly_low", "low"]

Current vitals (current_status):
- timestamp        : {cur_ts}
- heart_rate_level : {cur_hr}
- activity_state   : {cur_act}
- sleep_state      : {cur_sleep}
- temperature_status: {cur_temp}
- spo2_status      : {cur_spo2}

Recent history (from oldest to newest):
{history_block}

User profile (optional):
{profile_block}

Your tasks:

1. **Immediate Advice (for this moment)**
   - Provide 2–5 short, practical, lifestyle-oriented suggestions.
   - Examples include:
       - Suggest resting or light movement
       - Suggest drinking water
       - Suggest taking deep breaths or stretching
       - Encourage healthy routines
   - Never provide medical diagnosis or mention medical conditions.

2. **Trend Analysis (based on the history)**
   - Summarize how stable or variable the recent vitals appear.
   - Identify which signals show upward/downward trends.
   - Provide 1–3 suggestions addressing the trend (e.g., “recently elevated heart rate,” “frequent low SpO₂ levels,” etc.)
   - Keep tone calm, safe, and non-alarming.

Output format requirement:

Return **ONLY** a **single JSON object** with exactly this structure:

{{
  "summary": "One-sentence summary of the person's current overall condition.",
  "immediate_advice": [
    "Short actionable suggestion 1",
    "Short actionable suggestion 2"
  ],
  "trend_analysis": "1–3 sentences describing trends in the historical data.",
  "risk_level": "low | moderate | high",
  "need_medical_attention": false,
  "notes": "A safety reminder such as: This guidance is general and not medical advice."
}}

Rules:
- Output MUST be valid JSON only.
- Keep advice brief, friendly, and easy to display on a mobile interface.
- If several indicators are strongly abnormal (e.g., very_high HR + elevated temperature + low SpO₂), you may raise risk_level and set need_medical_attention = true.
- Still avoid panic-inducing language.

"""
    return prompt.strip()


class OpenAI_LLM(LLMInterface):
    """
    Concrete implementation of LLMInterface for OpenAI models.
    Handles API calls with retry logic.
    """

    def __init__(self, api_key: str, model: str, base_url: Optional[str] = None,
                 temperature: float = 0.2, timeout: int = 45, retries: int = 2):

        if api_key.strip() == 'sk-proj-...':
            print("API_KEY is not set. Please replace with your actual key.")

        self.model = model
        self.temperature = temperature
        self.timeout = timeout
        self.retries = retries
        self.client = OpenAI(api_key=api_key, base_url=base_url)

        print(f"INFO: OpenAI_LLM initialized with model: {self.model}")

    def predict(self, prompt: str) -> str:
        last_error = None
        for attempt in range(self.retries + 1):
            try:
                print(f"INFO: Sending request to OpenAI API (attempt {attempt + 1}/{self.retries + 1})...")

                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "You are VitalGuard, a conservative health-monitoring assistant. "
                                "You ONLY provide lifestyle guidance based on discretized vital-sign levels. "
                                "You MUST NOT provide medical diagnoses, medical terms, or mention diseases. "
                                "You MUST follow the JSON output format strictly."
                            )
                        },
                        {"role": "user", "content": prompt}
                    ],
                    temperature=self.temperature,
                    timeout=self.timeout
                )
                print("✅ LLM response received")
                return response.choices[0].message.content.strip()

            except OpenAIError as e:
                last_error = e
                print(f"⚠️  LLM API call failed: {e}")
                if attempt < self.retries:
                    time.sleep(1.0)

        raise RuntimeError(f"LLM failed after {self.retries + 1} attempts: {last_error}")

import json
from datetime import datetime
from vitalguard.llm_interface import OpenAI_LLM

# ========= CONFIG (modify with your own key) ==========
API_KEY = "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"  # ← 填你的 key
MODEL_NAME = "gpt-4o-mini"     # 或你自己在用的模型
BASE_URL = None                # 默认即可
# =======================================================

def main():
    # Initialize LLM
    llm = OpenAI_LLM(
        api_key=API_KEY,
        model=MODEL_NAME,
        base_url=BASE_URL,
        temperature=0.2,
        timeout=40,
        retries=1,
    )

    # ----------- Example current vital signs -----------
    current_status = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "heart_rate_level": "high",
        "activity_state": "resting",
        "sleep_state": "awake",
        "temperature_status": "slightly_elevated",
        "spo2_status": "slightly_low",
    }

    # ----------- Example history (2 previous samples) -----------
    history = [
        {
            "timestamp": "2025-12-05T15:00:00Z",
            "heart_rate_level": "normal",
            "activity_state": "resting",
            "sleep_state": "awake",
            "temperature_status": "normal",
            "spo2_status": "normal"
        },
        {
            "timestamp": "2025-12-05T15:10:00Z",
            "heart_rate_level": "high",
            "activity_state": "light_activity",
            "sleep_state": "awake",
            "temperature_status": "slightly_elevated",
            "spo2_status": "slightly_low"
        }
    ]

    print("\n🔍 Sending vitals to LLM...\n")

    raw_response = llm.analyze_vitals(
        current_status=current_status,
        history=history,
        user_profile={
            "age_group": "adult",
            "gender": "unspecified"
        }
    )

    print("===== RAW RESPONSE FROM LLM =====")
    print(raw_response)
    print("\n")

    print("===== PARSED JSON =====")
    try:
        parsed = json.loads(raw_response)
        print(json.dumps(parsed, indent=2))
    except Exception as e:
        print("JSON parse error:", e)


if __name__ == "__main__":
    main()

# vitalguard/llm_service.py
import json
import requests
from typing import Dict, Any, Optional, List

from .llm_interface import LLMInterface
from .ml_analyzer import VitalSignsAnalyzer


class HealthReportService:
    """
    Orchestrates ML analyzer output and LLM to generate structured health reports.
    Also forwards LLM output to ntfy for real-time notifications.
    """

    def __init__(
        self,
        analyzer: VitalSignsAnalyzer,
        llm_client: LLMInterface,
        ntfy_topic: str = "AIoT_sk5695", #change this for whatever server you want to post the message too
    ):
        self.analyzer = analyzer
        self.llm = llm_client
        self.ntfy_url = f"https://ntfy.sh/{ntfy_topic}"
        print("✅ HealthReportService initialized!")

    def _send_ntfy_notification(self, message: str) -> None:
        """
        Send LLM output to ntfy.
        This should NEVER raise and break the pipeline.
        """
        try:
            requests.post(
                self.ntfy_url,
                data=message.encode("utf-8"),
                timeout=3,
            )
        except Exception as e:
            # Log + move on (ntfy is non-critical)
            print(f"⚠️ ntfy notification failed: {e}")

    def generate_report(
        self,
        history_points: int = 30,
        user_profile: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:

        # ---------- Step 1: Run analyzer ----------
        current_status = self.analyzer.compute_current_status()
        history = self.analyzer.get_history(limit=history_points)

        # ---------- Step 2: Call LLM ----------
        llm_response = self.llm.analyze_vitals(
            current_status=dict(current_status),
            history=list(history),
            user_profile=user_profile or {},
        )

        # ---------- Step 3: Push to ntfy ----------
        self._send_ntfy_notification(llm_response)

        # ---------- Step 4: Parse LLM output ----------
        parsed: Optional[Dict[str, Any]] = None
        try:
            parsed = json.loads(llm_response)
        except json.JSONDecodeError:
            parsed = None

        return {
            "current_status": current_status,
            "history_size": len(history),
            "history": history,
            "llm_raw": llm_response,
            "llm_parsed": parsed,
        }

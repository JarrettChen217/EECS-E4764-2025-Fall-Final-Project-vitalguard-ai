# vitalguard/llm_service.py
import json
from typing import Dict, Any, Optional, List

from .llm_interface import LLMInterface
from .ml_analyzer import VitalSignsAnalyzer


class HealthReportService:
    """
    Orchestrates ML analyzer and LLM to generate structured health reports.
    """

    def __init__(self,
                 analyzer: VitalSignsAnalyzer,
                 llm_client: LLMInterface):
        self.analyzer = analyzer
        self.llm = llm_client
        print(f"✅ HealthReportService initialized!")

    def generate_report(self,
                        history_points: int = 30,
                        user_profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Generate a health report based on current status and recent history.
        Returns a dict that includes:
          - current_status
          - history (truncated)
          - llm_raw (string)
          - llm_parsed (dict or None)
        Raises ValueError on insufficient data for analysis.
        """
        current_status = self.analyzer.compute_current_status()
        history: List[Dict[str, Any]] = self.analyzer.get_history(history_points)

        llm_response = self.llm.analyze_vitals(
            current_status=current_status,
            history=history,
            user_profile=user_profile or {},
        )

        parsed: Optional[Dict[str, Any]] = None
        try:
            parsed = json.loads(llm_response)
        except json.JSONDecodeError:
            # Keep raw response for debugging
            parsed = None

        return {
            "current_status": current_status,
            "history_size": len(history),
            "history": history,
            "llm_raw": llm_response,
            "llm_parsed": parsed,
        }

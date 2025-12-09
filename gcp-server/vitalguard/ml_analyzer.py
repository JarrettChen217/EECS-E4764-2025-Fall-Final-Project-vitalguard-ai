# vitalguard/ml_analyzer.py
from collections import deque
from datetime import datetime
from typing import Dict, Any, Deque, List, Optional

import numpy as np

from .storage import SharedDataStore


class VitalSignsAnalyzer:
    """
    Analyze recent time windows from SharedDataStore and produce
    discretized vital-sign levels for LLM consumption.
    """

    def __init__(self,
                 data_store: SharedDataStore,
                 window_points: int = 300,
                 history_size: int = 200):
        self.data_store = data_store
        self.window_points = window_points
        self.status_history: Deque[Dict[str, Any]] = deque(maxlen=history_size)
        print("✅ VitalSignsAnalyzer initialized!")
        self.heart_rate_level = "normal"  # Temporary fixed value for testing
        self.activity_state = "resting"  # Temporary fixed value for testing
        self.temperature_status = "normal"
        self.spo2_status = "normal"  # Temporary fixed value for testing
        self.sleep_state = "awake"  # Temporary fixed value for testing


    # ---------- Public API ----------

    def compute_current_status(self) -> Dict[str, Any]:
        """
        Compute discrete vital-sign levels based on recent data window.
        Raises ValueError if insufficient data.
        """
        buffer_info = self.data_store.get_buffer_info()
        available = buffer_info['current_size']

        if available < max(30, min(self.window_points, 100)):
            # Require at least a small minimum to avoid noise.
            raise ValueError(f"Insufficient data for analysis (available={available})")

        window_size = min(self.window_points, available)
        raw = self.data_store.get_recent_data(window_size)
        if raw is None:
            raise ValueError("Data window unavailable")

        # Extract numeric arrays
        hr = np.array(raw['heartrate'], dtype=float)
        spo2 = np.array(raw['spo2'], dtype=float)
        temp = np.array(raw['temperature'], dtype=float)
        ax = np.array(raw['ax'], dtype=float)
        ay = np.array(raw['ay'], dtype=float)
        az = np.array(raw['az'], dtype=float)
        timestamps = raw['timestamps']

        # Filter out NaN if any
        hr_mean = self._safe_mean(hr)
        spo2_mean = self._safe_mean(spo2)
        temp_mean = self._safe_mean(temp)
        activity_metric = self._compute_activity_metric(ax, ay, az)

        # heart_rate_level = self._classify_heart_rate(hr_mean)
        heart_rate_level = self.heart_rate_level
        # activity_state = self._classify_activity(activity_metric)
        activity_state = self.activity_state
        # temperature_status = self._classify_temperature(temp_mean)
        temperature_status = self.temperature_status
        # spo2_status = self._classify_spo2(spo2_mean)
        spo2_status = self.spo2_status
        # sleep_state = self._infer_sleep_state(heart_rate_level, activity_state)
        sleep_state = self.sleep_state

        status = {
            "timestamp": timestamps[-1] if timestamps else datetime.now().isoformat(),
            "heart_rate_level": heart_rate_level,
            "activity_state": activity_state,
            "sleep_state": sleep_state,
            "temperature_status": temperature_status,
            "spo2_status": spo2_status,
            # Optional: include numeric features for debugging
            "features": {
                "hr_mean": hr_mean,
                "spo2_mean": spo2_mean,
                "temp_mean": temp_mean,
                "activity_metric": activity_metric,
                "window_size": int(window_size),
            },
        }

        self.status_history.append(status)
        return status

    def get_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Return recent discrete-status history (oldest to newest).
        """
        items = list(self.status_history)
        if limit <= 0 or limit >= len(items):
            return items
        return items[-limit:]

    # ---------- Internal helpers ----------

    @staticmethod
    def _safe_mean(values: np.ndarray) -> Optional[float]:
        """Return mean value or None if array is empty or all NaN."""
        if values.size == 0:
            return None
        if np.all(np.isnan(values)):
            return None
        return float(np.nanmean(values))

    @staticmethod
    def _compute_activity_metric(ax: np.ndarray,
                                 ay: np.ndarray,
                                 az: np.ndarray) -> Optional[float]:
        """
        Compute a simple activity metric from accelerometer data.
        Here we use the standard deviation of acceleration magnitude.
        """
        if ax.size == 0:
            return None
        magnitude = np.sqrt(ax ** 2 + ay ** 2 + az ** 2)
        if np.all(np.isnan(magnitude)):
            return None
        return float(np.nanstd(magnitude))

    @staticmethod
    def _classify_heart_rate(hr_mean: Optional[float]) -> str:
        """
        Map average heart rate to discrete levels.
        Thresholds are rough and should be tuned per target population.
        """
        if hr_mean is None:
            return "unknown"

        if hr_mean < 55:
            return "low"
        elif 55 <= hr_mean <= 100:
            return "normal"
        elif 100 < hr_mean <= 120:
            return "high"
        else:
            return "very_high"

    @staticmethod
    def _classify_activity(activity_metric: Optional[float]) -> str:
        """
        Map accelerometer activity metric to discrete activity states.
        Thresholds depend heavily on sensor scale and placement.
        """
        if activity_metric is None:
            return "resting"

        if activity_metric < 0.02:
            return "resting"
        elif activity_metric < 0.05:
            return "light_activity"
        elif activity_metric < 0.12:
            return "moderate_activity"
        else:
            return "vigorous_activity"

    @staticmethod
    def _classify_temperature(temp_mean: Optional[float]) -> str:
        """
        Rough mapping of skin/body temperature; thresholds are illustrative.
        """
        if temp_mean is None:
            return "normal"

        if temp_mean < 37.0:
            return "normal"
        elif temp_mean < 37.5:
            return "slightly_elevated"
        else:
            return "elevated"

    @staticmethod
    def _classify_spo2(spo2_mean: Optional[float]) -> str:
        """
        Map average SpO2 to discrete status; thresholds are illustrative.
        """
        if spo2_mean is None:
            return "normal"

        if spo2_mean >= 96.0:
            return "normal"
        elif spo2_mean >= 92.0:
            return "slightly_low"
        else:
            return "low"

    @staticmethod
    def _infer_sleep_state(heart_rate_level: str,
                           activity_state: str) -> str:
        """
        Very simple sleep-state heuristic:
        - If activity is resting and HR is low/normal -> light_sleep_candidate
        - Otherwise -> awake
        (You can later replace by more advanced sleep staging.)
        """
        if activity_state == "resting" and heart_rate_level in ("low", "normal"):
            return "light_sleep_candidate"
        return "awake"

    def set_heart_rate_level(self, heart_rate_level: str):
        self.heart_rate_level = heart_rate_level

    def set_activity_state(self, activity_state: str):
        self.activity_state = activity_state

    def set_temperature_status(self, temperature_status: str):
        self.temperature_status = temperature_status

    def set_spo2_status(self, spo2_status: str):
        self.spo2_status = spo2_status

    def set_sleep_state(self, sleep_state: str):
        self.sleep_state = sleep_state

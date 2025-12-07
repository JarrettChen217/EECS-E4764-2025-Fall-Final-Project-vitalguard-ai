# vitalguard/validation.py
from typing import Dict, Any, Optional, Tuple


class DataValidator:
    """Packet Validator: Ensures the received data format is correct."""

    @staticmethod
    def validate_batch_request(data: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """
        Verify batch data request format.
        Returns: (is_valid, error_message)
        """
        # Required field check.
        required_fields = ['device_id', 'batch_info', 'data']
        for field in required_fields:
            if field not in data:
                return False, f"Missing required field: {field}"

        # batch_info validation
        batch_info = data['batch_info']
        required_batch_fields = ['start_cycle', 'end_cycle', 'total_points']
        for field in required_batch_fields:
            if field not in batch_info:
                return False, f"Missing batch_info field: {field}"

        # data array validation
        data_array = data['data']
        if not isinstance(data_array, list) or len(data_array) == 0:
            return False, "Data array is empty or not a list"

        # Validate the first data point structure
        first_point = data_array[0]
        required_data_fields = ['cycle', 'timestamp', 'vital_signs']
        for field in required_data_fields:
            if field not in first_point:
                return False, f"Data point missing field: {field}"

        vital_signs = first_point['vital_signs']
        if 'ppg' not in vital_signs:
            return False, "Missing PPG data in vital_signs"

        ppg = vital_signs['ppg']
        if 'ir' not in ppg or 'red' not in ppg:
            return False, "PPG data must contain 'ir' and 'red'"

        for field in ['heartrate', 'spo2']:
            if field not in ppg:
                return False, f"Field '{field}' in PPG is missing"

        # accel validation
        if 'accel' in vital_signs:
            accel = vital_signs['accel']
            if not isinstance(accel, dict):
                return False, "accel must be an object with ax/ay/az fields"
            for axis in ['ax', 'ay', 'az']:
                if axis not in accel:
                    return False, f"accel missing field: {axis}"

        return True, None

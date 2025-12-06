# vitalguard/storage.py
import os
import json
import threading
from collections import deque
from typing import Optional, Deque, Dict, Any, List

import numpy as np

from .models import VitalSignsDataPoint


class SharedDataStore:
    """
    thread-safe storage for multi-sensor data points
    supports batch writes, time-series queries, data aggregation
    """

    def __init__(self, max_size: int, persist_file: Optional[str] = None):
        self.max_size = max_size
        self.persist_file = persist_file

        self.data_buffer: Deque[VitalSignsDataPoint] = deque(maxlen=max_size)
        self.lock = threading.Lock()

        self.total_received = 0
        self.total_batches = 0

        print(f"✅ SharedDataStore initialized: max_size={max_size}")

        # create persistence file if not exists
        if self.persist_file and not os.path.exists(self.persist_file):
            open(self.persist_file, 'w').close()
            print(f"📁 Created persistence file: {self.persist_file}")

    def add_batch(self, data_points: List[VitalSignsDataPoint]) -> int:
        """
        Batch Add Data Points (Thread-Safe)
        Returns: Number of data points successfully added.
        """
        added_count = 0

        with self.lock:
            for point in data_points:
                self.data_buffer.append(point)
                added_count += 1

            self.total_received += added_count
            self.total_batches += 1

        # Asynchronous persistence (to avoid blocking).
        if self.persist_file and added_count > 0:
            threading.Thread(
                target=self._persist_batch,
                args=(data_points,),
                daemon=True
            ).start()

        return added_count

    def _persist_batch(self, data_points: List[VitalSignsDataPoint]) -> None:
        """Background thread: batch persistence of data."""
        try:
            with open(self.persist_file, 'a') as f:
                for point in data_points:
                    f.write(json.dumps(point.to_dict()) + '\n')
        except Exception as e:
            print(f"⚠️  Persistence failed: {e}")

    def get_recent_data(self, count: int) -> Optional[Dict[str, np.ndarray]]:
        """
        Get the most recent 'count' data points from the buffer, return in structured format.

        Returns:
            {
                'ir': np.array([...]),
                'red': np.array([...]),
                'heartrate': np.array([...]),
                'spo2': np.array([...]),
                'temperature': np.array([...]),
                'humidity': np.array([...]),
                'force': np.array([...]),
                'ax': np.array([...]),
                'ay': np.array([...]),
                'az': np.array([...]),
                'timestamps': [...]
            }
            If insufficient data, returns None.
        """
        with self.lock:
            buffer_size = len(self.data_buffer)

            if buffer_size < count:
                print(f"⚠️  Insufficient data: requested {count}, available {buffer_size}")
                return None

            # return the most recent 'count' items
            recent_items = list(self.data_buffer)[-count:]

            # construct structured arrays
            return {
                'ir': np.array([item.ir for item in recent_items]),
                'red': np.array([item.red for item in recent_items]),
                'heartrate': np.array([item.heartrate for item in recent_items]),
                'spo2': np.array([item.spo2 for item in recent_items]),
                'temperature': np.array([item.temperature for item in recent_items]),
                'humidity': np.array([item.humidity for item in recent_items]),
                'force': np.array([item.force for item in recent_items]),
                'ax': np.array([item.ax for item in recent_items]),
                'ay': np.array([item.ay for item in recent_items]),
                'az': np.array([item.az for item in recent_items]),
                'timestamps': [item.timestamp for item in recent_items]
            }


    # Specialized Data Window Retrieval Methods

    def get_ppg_window(self, window_size: int = 300) -> Optional[Dict[str, np.ndarray]]:
        """
        Obtain the PPG data window used for heart rate calculation, specifically for signal processing algorithms.
        """
        data = self.get_recent_data(window_size)
        if data is None:
            return None

        return {
            'ir': data['ir'],
            'red': data['red'],
            'heartrate': data['heartrate'],
            'spo2': data['spo2'],
            'timestamps': data['timestamps']
        }

    def get_motion_window(self, window_size: int = 300) -> Optional[Dict[str, np.ndarray]]:
        """
        Obtain accelerometer data window for activity and posture analysis.
        """
        data = self.get_recent_data(window_size)
        if data is None:
            return None

        return {
            'ax': data['ax'],
            'ay': data['ay'],
            'az': data['az'],
            'timestamps': data['timestamps']
        }

    def get_buffer_info(self) -> Dict[str, Any]:
        """Get buffer status information."""
        with self.lock:
            current_size = len(self.data_buffer)
            return {
                'current_size': current_size,
                'max_size': self.max_size,
                'utilization': f"{current_size / self.max_size * 100:.1f}%",
                'total_received': self.total_received,
                'total_batches': self.total_batches
            }

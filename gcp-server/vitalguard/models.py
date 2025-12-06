# vitalguard/models.py
from datetime import datetime
from typing import Dict, Any


class VitalSignsDataPoint:
    """
    Single data point of vital signs measurement.
    Represents a single cycle of vital signs measurement.
    """

    def __init__(self,
                 cycle: int,
                 timestamp: str,
                 ir: int,
                 red: int,
                 temperature: float,
                 humidity: float,
                 force: float,
                 heartrate: float,
                 spo2: float,
                 ax: float,
                 ay: float,
                 az: float):
        self.cycle = cycle
        self.timestamp = timestamp

        # PPG data
        self.ir = ir
        self.red = red
        self.heartrate = heartrate
        self.spo2 = spo2

        # Environmental data
        self.temperature = temperature
        self.humidity = humidity

        # Force sensor data
        self.force = force

        # Accelerometer data
        self.ax = ax
        self.ay = ay
        self.az = az

        # Server reception timestamp
        self.server_timestamp = datetime.now().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            'cycle': self.cycle,
            'timestamp': self.timestamp,
            'ppg': {
                'ir': self.ir,
                'red': self.red,
                'heartrate': self.heartrate,
                'spo2': self.spo2
            },
            'temperature': self.temperature,
            'humidity': self.humidity,
            'force': self.force,
            'accel': {
                'ax': self.ax,
                'ay': self.ay,
                'az': self.az
            },
            'server_timestamp': self.server_timestamp
        }

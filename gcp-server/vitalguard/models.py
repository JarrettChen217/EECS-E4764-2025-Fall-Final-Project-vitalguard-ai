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

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> 'VitalSignsDataPoint':
        ppg = data.get('ppg', {})
        accel = data.get('accel', {})
        return VitalSignsDataPoint(
            cycle=data.get('cycle', 0),
            timestamp=data.get('timestamp', ''),
            ir=ppg.get('ir', 0),
            red=ppg.get('red', 0),
            heartrate=ppg.get('heartrate', 0.0),
            spo2=ppg.get('spo2', 0.0),
            temperature=data.get('temperature', 0.0),
            humidity=data.get('humidity', 0.0),
            force=data.get('force', 0.0),
            ax=accel.get('ax', 0.0),
            ay=accel.get('ay', 0.0),
            az=accel.get('az', 0.0)
        )

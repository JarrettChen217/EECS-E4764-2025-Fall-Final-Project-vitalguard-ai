import requests
import random
import time
from datetime import datetime, timedelta
from typing import Dict, Any, List

API_URL = "http://localhost:9999/api/vitals"
DEVICE_ID = "ESP32_RUN_001"

BATCH_SIZE = 20           # 20 points per batch
NUM_BATCHES = 200
TOTAL_CYCLES = BATCH_SIZE * NUM_BATCHES

MID_POINT = 5

from vitalguard.ml_analyzer import VitalSignsAnalyzer


def generate_running_point(cycle: int, timestamp: datetime) -> Dict[str, Any]:
    """
    Generate one running data point:
    - Heart rate from ~80 to ~140 with small jitter
    - PPG red/ir increase with load
    - Temperature stable
    - Acceleration irregular (running-like motion)
    """
    # Progress of the whole running session: 0 -> 1
    progress = (cycle - 1) / float(TOTAL_CYCLES - 1)

    # --- Heart rate: 80 -> 140 ---
    rest_hr = 80
    max_hr = 160
    target_hr = rest_hr + (max_hr - rest_hr) * progress
    heartrate = int(target_hr + random.uniform(-10, 10))  # ±3 bpm jitter

    # --- PPG red ---
    base_red = 48000
    max_red_factor = 1.2  # up to +20%
    red_mean = base_red * (1.0 + (max_red_factor - 1.0) * progress)
    red = int(red_mean + random.uniform(-500, 500))

    # --- PPG IR ---
    base_ir = 50000
    max_ir_factor = 1.15
    ir_mean = base_ir * (1.0 + (max_ir_factor - 1.0) * progress)
    ir = int(ir_mean + random.uniform(-500, 500))

    # --- SpO2: normal high range ---
    spo2 = int(random.uniform(97, 99.5))

    # --- Temperature: stable around 36.8 ---
    base_temp = 36.8
    temperature = round(base_temp + random.uniform(-0.05, 0.05), 2)

    # --- Humidity: not critical, small noise ---
    base_humidity = 45.0
    humidity = round(base_humidity + random.uniform(-1.0, 1.0), 2)

    # --- Acceleration: irregular running motion ---
    min_amp = 0.3   # low activity
    max_amp = 1.5   # intense running
    amplitude = min_amp + (max_amp - min_amp) * progress

    ax = random.uniform(-amplitude, amplitude)
    ay = random.uniform(-amplitude, amplitude)
    az = 1.0 + random.uniform(-amplitude / 2.0, amplitude / 2.0)  # around 1g

    point = {
        "cycle": cycle,
        "timestamp": timestamp.isoformat(timespec="seconds"),
        "vital_signs": {
            "ppg": {
                "ir": ir,
                "red": red,
                "heartrate": heartrate,
                "spo2": spo2,
            },
            "temperature": temperature,
            "humidity": humidity,
            "force": 0.0,
            "accel": {
                "ax": round(ax, 3),
                "ay": round(ay, 3),
                "az": round(az, 3),
            },
        },
    }
    return point


def send_running_batches(ml_analyzer_instance: VitalSignsAnalyzer = None) -> None:
    """
    Send 400 batches, each with 20 data points (total 8000 points).
    """
    base_time = datetime(2025, 1, 1, 12, 0, 0)
    current_cycle = 1

    for batch_index in range(NUM_BATCHES):
        batch_start_cycle = current_cycle
        data_points: List[Dict[str, Any]] = []

        # Build one batch of 20 points
        for i in range(BATCH_SIZE):
            timestamp = base_time + timedelta(seconds=current_cycle - 1)
            point = generate_running_point(current_cycle, timestamp)
            data_points.append(point)
            current_cycle += 1

        payload = {
            "device_id": DEVICE_ID,
            "batch_info": {
                "start_cycle": batch_start_cycle,
                "end_cycle": current_cycle - 1,
                "total_points": BATCH_SIZE,
            },
            "data": data_points,
        }

        response = requests.post(API_URL, json=payload, timeout=5)
        print(
            f"Sent batch {batch_index + 1}/{NUM_BATCHES}, "
            f"cycles {batch_start_cycle}-{current_cycle - 1}, "
            f"status={response.status_code}"
        )

        # if (batch_index == MID_POINT) and (ml_analyzer_instance is not None):
        #     ml_analyzer_instance.set_activity_state("running")
        #     print("set activity_state to 'running' in ml_analyzer_instance")

        # Check average heart rate in this batch and set heart rate level
        if ml_analyzer_instance is not None and data_points:
            avg_hr = sum(point["vital_signs"]["ppg"]["heartrate"] for point in data_points) / len(data_points)
            if avg_hr > 140:
                ml_analyzer_instance.set_heart_rate_level("very_high")
                print(f"set heart_rate_level to 'very_high' (avg HR: {avg_hr:.1f} bpm)")
            elif avg_hr > 100:
                ml_analyzer_instance.set_heart_rate_level("high")
                print(f"set heart_rate_level to 'high' (avg HR: {avg_hr:.1f} bpm)")

        # Optional small delay to avoid overloading server
        time.sleep(1)


if __name__ == "__main__":
    send_running_batches()

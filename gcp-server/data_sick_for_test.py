import requests
import random
import time
from datetime import datetime, timedelta
from typing import Dict, Any, List

API_URL = "http://localhost:9999/api/vitals"
DEVICE_ID = "ESP32_SICK_001"

BATCH_SIZE = 20           # 20 points per batch
NUM_BATCHES = 50
TOTAL_CYCLES = BATCH_SIZE * NUM_BATCHES

MID_POINT = 5

from vitalguard.ml_analyzer import VitalSignsAnalyzer


def generate_sick_point(cycle: int, timestamp: datetime) -> Dict[str, Any]:
    """
    Generate one sick person data point:
    - Heart rate: vibrating around 110 bpm (elevated due to illness)
    - Body temperature: high fever (38.5-39.5°C)
    - SpO2: slightly lower than normal (94-96%)
    - PPG signals: slightly elevated due to increased heart rate
    - Acceleration: minimal (resting/inactive state)
    - Force: 0 (not standing/walking)
    """
    # Progress of the illness monitoring: 0 -> 1
    progress = (cycle - 1) / float(TOTAL_CYCLES - 1)

    # --- Heart rate: vibrating around 110 bpm ---
    # Slightly elevated and fluctuating due to fever
    base_hr = 110
    heartrate = int(base_hr + random.uniform(-8, 12))  # 102-122 bpm range

    # --- PPG red: elevated due to increased heart rate ---
    base_red = 50000  # Higher baseline due to fever
    red = int(base_red + random.uniform(-800, 800))

    # --- PPG IR: elevated due to increased heart rate ---
    base_ir = 52000  # Higher baseline
    ir = int(base_ir + random.uniform(-800, 800))

    # --- SpO2: slightly lower (94-96%) due to illness ---
    spo2 = round(random.uniform(94.0, 96.5), 1)

    # --- Temperature: HIGH FEVER (38.5-39.5°C) ---
    # Stable high temperature with small fluctuations
    base_temp = 38.8  # High fever
    temperature = round(base_temp + random.uniform(-0.3, 0.7), 2)  # 38.5-39.5°C

    # --- Humidity: slightly higher due to sweating ---
    base_humidity = 55.0  # Higher humidity due to perspiration
    humidity = round(base_humidity + random.uniform(-2.0, 2.0), 2)

    # --- Acceleration: MINIMAL (resting in bed) ---
    # Very small movements, person is lying down/resting
    rest_amp = 0.05   # Very minimal movement

    ax = random.uniform(-rest_amp, rest_amp)
    ay = random.uniform(-rest_amp, rest_amp)
    az = 1.0 + random.uniform(-rest_amp, rest_amp)  # Around 1g (lying horizontally)

    # --- Force: 0 (not standing/walking) ---
    force = 0.0

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
            "force": force,
            "accel": {
                "ax": round(ax, 3),
                "ay": round(ay, 3),
                "az": round(az, 3),
            },
        },
    }
    return point


def send_sick_batches(ml_analyzer_instance: VitalSignsAnalyzer = None) -> None:
    """
    Send sick person data batches simulating fever and resting state.
    Total: NUM_BATCHES batches, each with BATCH_SIZE data points.
    """
    base_time = datetime(2025, 1, 1, 14, 0, 0)  # Different time from running test
    current_cycle = 1

    for batch_index in range(NUM_BATCHES):
        batch_start_cycle = current_cycle
        data_points: List[Dict[str, Any]] = []

        # Build one batch of 20 points
        for i in range(BATCH_SIZE):
            timestamp = base_time + timedelta(seconds=current_cycle - 1)
            point = generate_sick_point(current_cycle, timestamp)
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

        # Set analyzer states to reflect sick person
        if ml_analyzer_instance is not None and data_points:
            # Set activity state to resting
            if batch_index == MID_POINT:
                ml_analyzer_instance.set_activity_state("resting")
                print("set activity_state to 'resting' in ml_analyzer_instance")

            # Set sleep state to awake (sick, can't sleep well)
            if batch_index == MID_POINT + 1:
                ml_analyzer_instance.set_sleep_state("awake")
                print("set sleep_state to 'awake' in ml_analyzer_instance")

            # Check average heart rate and temperature in this batch
            avg_hr = sum(point["vital_signs"]["ppg"]["heartrate"] for point in data_points) / len(data_points)
            avg_temp = sum(point["vital_signs"]["temperature"] for point in data_points) / len(data_points)
            avg_spo2 = sum(point["vital_signs"]["ppg"]["spo2"] for point in data_points) / len(data_points)

            # Set heart rate level to elevated
            if avg_hr > 100:
                ml_analyzer_instance.set_heart_rate_level("high")
                print(f"set heart_rate_level to 'elevated' (avg HR: {avg_hr:.1f} bpm)")

            # Set temperature status to high
            if avg_temp > 38.0:
                ml_analyzer_instance.set_temperature_status("high")
                print(f"set temperature_status to 'high' (avg Temp: {avg_temp:.1f}°C)")

            # Set SpO2 status to low_normal
            if avg_spo2 < 97:
                ml_analyzer_instance.set_spo2_status("low_normal")
                print(f"set spo2_status to 'low_normal' (avg SpO2: {avg_spo2:.1f}%)")

        # Optional small delay to avoid overloading server
        time.sleep(1)


if __name__ == "__main__":
    send_sick_batches()


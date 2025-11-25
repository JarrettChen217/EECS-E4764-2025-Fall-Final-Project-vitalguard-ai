#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import json
import random
import argparse
import requests
from datetime import datetime

def pretty(resp: requests.Response) -> str:
    """Pretty print JSON response safely."""
    try:
        return json.dumps(resp.json(), ensure_ascii=False, indent=2)
    except Exception:
        return f"(non-json) {resp.text[:300]}"

def gen_single_point(cycle: int, ts_ms: int) -> dict:
    """Generate a single vital sign payload for POST /api/vitals (single point)."""
    ir = random.randint(35000, 65000)
    red = random.randint(30000, 60000)
    temp = round(random.uniform(36.3, 37.1), 2)
    return {
        "cycle": cycle,
        "timestamp": ts_ms,
        "ppg": {
            "ir": ir,
            "red": red
        },
        "temperature": temp,
        "humidity": round(random.uniform(35.0, 55.0), 1),
        "force": round(random.uniform(0.0, 1.5), 2)
    }

def gen_batch_payload(device_id: str, start_cycle: int, count: int, start_ts_ms: int, sample_rate_hz: int = 100) -> dict:
    """Generate a batch payload for POST /api/vitals (batch mode)."""
    period_ms = int(1000 / sample_rate_hz)
    data_points = []

    for i in range(count):
        cycle = start_cycle + i
        ts_ms = start_ts_ms + i * period_ms
        ir = random.randint(35000, 65000)
        red = random.randint(30000, 60000)
        temp = round(random.uniform(36.3, 37.1), 2)

        data_points.append({
            "cycle": cycle,
            "timestamp": ts_ms,
            "vital_signs": {
                "ppg": {"ir": ir, "red": red},
                "temperature": temp,
                "humidity": round(random.uniform(35.0, 55.0), 1),
                "force": round(random.uniform(0.0, 1.5), 2)
            }
        })

    payload = {
        "device_id": device_id,
        "batch_info": {
            "start_cycle": start_cycle,
            "end_cycle": start_cycle + count - 1,
            "sample_rate_hz": sample_rate_hz,
            "batch_id": f"{device_id}-{start_cycle}-{start_cycle + count - 1}",
            "total_points" : count
        },
        "data": data_points
    }
    return payload

def main():
    parser = argparse.ArgumentParser(description="Simple tester for VitalGuard AI Flask APIs")
    parser.add_argument("--base-url", default=os.getenv("BASE_URL", "http://localhost:9999"), help="Base URL of the Flask server")
    parser.add_argument("--device-id", default="VG-ESP32-TEST-001", help="Device ID used in test payloads")
    parser.add_argument("--batch-size", type=int, default=50, help="Number of points per batch POST")
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    session = requests.Session()
    headers = {"Content-Type": "application/json"}

    print(f"[i] Testing server base: {base}")

    # 1) GET /
    r = session.get(f"{base}/")
    print("\n[GET /] status=", r.status_code)
    print(pretty(r))

    # 2) GET /health
    r = session.get(f"{base}/health")
    print("\n[GET /health] status=", r.status_code)
    print(pretty(r))

    # 3) POST /api/vitals (single)
    now_ms = int(time.time() * 1000)
    single_payload = gen_single_point(cycle=1000, ts_ms=now_ms)
    r = session.post(f"{base}/api/vitals", data=json.dumps(single_payload), headers=headers, timeout=10)
    print("\n[POST /api/vitals single] status=", r.status_code)
    print(pretty(r))

    # 4) POST /api/vitals (batch)
    batch_payload = gen_batch_payload(
        device_id=args.device_id,
        start_cycle=2000,
        count=args.batch_size,
        start_ts_ms=now_ms + 100,
        sample_rate_hz=100
    )
    r = session.post(f"{base}/api/vitals", data=json.dumps(batch_payload), headers=headers, timeout=20)
    print("\n[POST /api/vitals batch] status=", r.status_code)
    print(pretty(r))

    # 5) GET /api/buffer
    r = session.get(f"{base}/api/buffer", timeout=10)
    print("\n[GET /api/buffer] status=", r.status_code)
    print(pretty(r))

    # 6) GET /api/recent?limit=50
    r = session.get(f"{base}/api/recent", params={"limit": 50}, timeout=10)
    print("\n[GET /api/recent?limit=50] status=", r.status_code)
    print(pretty(r))

    print("\n[i] Done.")

if __name__ == "__main__":
    main()

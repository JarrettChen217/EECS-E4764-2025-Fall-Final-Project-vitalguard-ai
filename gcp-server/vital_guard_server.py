# vital_guard_server.py
# VitalGuard AI Health Monitoring System - GCP Server Side
# Function: Receive ESP32 multi-sensor data, process in real-time, LLM health analysis.

import os
import json
import time
import threading
from datetime import datetime
from collections import deque
from typing import Optional, Deque, Dict, Any, List
from abc import ABC, abstractmethod

import numpy as np
from flask import Flask, request, jsonify
from openai import OpenAI, OpenAIError

# ======================= CONFIGURATION =======================
# --- LLM Configuration ---
API_KEY = os.environ.get("OPENAI_API_KEY", "your-api-key-here")
BASE_URL = None
MODEL_NAME = "gpt-4o-mini"
TEMPERATURE = 0.2
TIMEOUT_SEC = 45
RETRY = 2

# --- Data Processing Configuration ---
WINDOW_POINTS = 300  # Window size: 300 data points for heart rate calculation (approximately 6 seconds @ 20ms sampling).
PREDICTION_INTERVAL_SEC = 30  # LLM analysis interval: Generate a health report every 30 seconds.
MAX_DATA_BUFFER_SIZE = 1500  # Maximum buffer: 1500 data points (approximately 30 seconds of data).

# --- Flask Server Configuration ---
FLASK_HOST = '0.0.0.0'
FLASK_PORT = 9999
DATA_FILE = 'vital_signs_data.jsonl'  # Persistent storage file.

# --- Device Information ---
DEVICE_TYPE = "ESP32 VitalGuard"
SENSOR_LOCATION = "Wrist"


# ======================= DATA MODELS =======================
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


# ======================= SHARED DATA STORE (ENHANCED) =======================
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


# ======================= DATA VALIDATION =======================
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


# ======================= LLM INTERFACE (UNCHANGED) =======================
class LLMInterface(ABC):
    """LLM client abstract base class."""

    @abstractmethod
    def predict(self, prompt: str) -> str:
        pass


class OpenAI_LLM(LLMInterface):
    """
    Concrete implementation of LLMInterface for OpenAI models.
    Handles API calls with retry logic.
    """

    def __init__(self, api_key: str, model: str, base_url: Optional[str] = None,
                 temperature: float = 0.2, timeout: int = 45, retries: int = 2):

        if api_key.strip() == 'sk-proj-...':
            print("API_KEY is not set. Please replace with your actual key.")

        self.model = model
        self.temperature = temperature
        self.timeout = timeout
        self.retries = retries
        self.client = OpenAI(api_key=api_key, base_url=base_url)

        print(f"INFO: OpenAI_LLM initialized with model: {self.model}")

    def predict(self, prompt: str) -> str:
        last_error = None
        for attempt in range(self.retries + 1):
            try:
                print(f"INFO: Sending request to OpenAI API (attempt {attempt + 1}/{self.retries + 1})...")

                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": "You are a health monitoring AI assistant."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=self.temperature,
                    timeout=self.timeout
                )
                print("✅ LLM response received")
                return response.choices[0].message.content.strip()

            except OpenAIError as e:
                last_error = e
                print(f"⚠️  LLM API call failed: {e}")
                if attempt < self.retries:
                    time.sleep(1.0)

        raise RuntimeError(f"LLM failed after {self.retries + 1} attempts: {last_error}")


# ======================= FLASK SERVER =======================
def create_flask_app(data_store: SharedDataStore) -> Flask:
    """
    Creates and configures the Flask application.
    Args:
        data_store: The shared data store instance to write incoming data to.
    Returns:
        Configured Flask app instance.
    """
    app = Flask(__name__)

    @app.route('/')
    def home():
        """Server status endpoint."""
        buffer_info = data_store.get_buffer_info()
        return jsonify({
            "status": "running",
            "service": "VitalGuard AI Health Monitoring System",
            "version": "2.0",
            "buffer_status": buffer_info,
            "endpoints": {
                "/": "Server status",
                "/api/vitals": "Receive vital signs data (POST)",
                "/api/buffer": "Check buffer status (GET)",
                "/api/recent": "Get recent data (GET)",
                "/health": "Health check for server (GET)"
            }
        })

    @app.route('/api/vitals', methods=['POST'])
    def receive_vital_signs():
        """
        Receiving vital signs data from ESP32
        Supports bulk data transmission (recommended) and single-point transmission (compatible).
        """
        try:
            request_data = request.get_json()

            if not request_data:
                return jsonify({
                    "success": False,
                    "error": {
                        "code": "EMPTY_REQUEST",
                        "message": "Request body is empty"
                    }
                }), 400

            # ===== Batch Data Processing (Recommended). =====
            if 'data' in request_data and 'batch_info' in request_data:
                is_valid, error_msg = DataValidator.validate_batch_request(request_data)
                if not is_valid:
                    return jsonify({
                        "success": False,
                        "error": {
                            "code": "VALIDATION_FAILED",
                            "message": error_msg
                        }
                    }), 400

                # Parsing batch data.
                device_id = request_data['device_id']
                batch_info = request_data['batch_info']
                data_points_raw = request_data['data']
                data_points: List[VitalSignsDataPoint] = []
                parsing_errors: List[str] = []
                for idx, point in enumerate(data_points_raw):
                    try:
                        vital_signs = point['vital_signs']
                        ppg = vital_signs['ppg']
                        accel = vital_signs.get('accel', {}) or {}
                        data_point = VitalSignsDataPoint(
                            cycle=point['cycle'],
                            timestamp=str(point['timestamp']),
                            ir=ppg.get('ir', 0),
                            red=ppg.get('red', 0),
                            temperature=vital_signs.get('temperature', 0.0),
                            humidity=vital_signs.get('humidity', 0.0),
                            force=vital_signs.get('force', 0.0),
                            heartrate=ppg.get('heartrate'),
                            spo2=ppg.get('spo2'),
                            ax=accel.get('ax'),
                            ay=accel.get('ay'),
                            az=accel.get('az')
                        )
                        data_points.append(data_point)
                    except Exception as e:
                        parsing_errors.append(f"Point {idx}: {str(e)}")

                # Batch Add to Data Store.
                added_count = data_store.add_batch(data_points)

                # Return the processing result.
                response = {
                    "success": True,
                    "message": f"Batch processed successfully",
                    "device_id": device_id,
                    "batch_info": {
                        "cycles": f"{batch_info.get('start_cycle')}-{batch_info.get('end_cycle')}",
                        "total_received": len(data_points_raw),
                        "successfully_stored": added_count,
                        "parsing_errors": len(parsing_errors)
                    }
                }

                if parsing_errors:
                    response["warnings"] = parsing_errors[:10]
                print(f"📦 Batch received: {added_count} points from {device_id}")
                return jsonify(response), 201

            # ===== Backward Compatibility =====
            else:
                # Check the required fields.
                required = ['cycle', 'timestamp', 'ppg', 'temperature']
                if not all(k in request_data for k in required):
                    return jsonify({
                        "success": False,
                        "error": {
                            "code": "MISSING_FIELDS",
                            "message": f"Required fields: {required}"
                        }
                    }), 400
                ppg = request_data['ppg']
                accel = request_data.get('accel', {}) or {}
                data_point = VitalSignsDataPoint(
                    cycle=request_data['cycle'],
                    timestamp=request_data['timestamp'],
                    ir=ppg.get('ir', 0),
                    red=ppg.get('red', 0),
                    temperature=request_data['temperature'],
                    humidity=request_data.get('humidity', 0.0),
                    force=request_data.get('force', 0.0),
                    heartrate=ppg.get('heartrate'),
                    spo2=ppg.get('spo2'),
                    ax=accel.get('ax'),
                    ay=accel.get('ay'),
                    az=accel.get('az')
                )

                data_store.add_batch([data_point])

                return jsonify({
                    "success": True,
                    "message": "Single data point received"
                }), 201

        except Exception as e:
            print(f"❌ Error processing request: {e}")
            import traceback
            traceback.print_exc()

            return jsonify({
                "success": False,
                "error": {
                    "code": "SERVER_ERROR",
                    "message": str(e)
                }
            }), 500

    @app.route('/api/buffer', methods=['GET'])
    def get_buffer_status():
        """Get data buffer status."""
        try:
            buffer_info = data_store.get_buffer_info()
            return jsonify({
                "success": True,
                "buffer": buffer_info
            }), 200
        except Exception as e:
            return jsonify({
                "success": False,
                "error": str(e)
            }), 500

    @app.route('/api/recent', methods=['GET'])
    def get_recent_data():
        """Get the most recent data points (for debugging and visualization)."""
        try:
            limit = request.args.get('limit', default=50, type=int)
            limit = min(limit, 500)  # 最多返回500个点

            recent_data = data_store.get_recent_data(limit)

            if recent_data is None:
                return jsonify({
                    "success": False,
                    "message": "Insufficient data",
                    "available": data_store.get_buffer_info()['current_size']
                }), 404

            # Format returned data.
            response_data = {
                "success": True,
                "count": limit,
                "data": {
                    "ppg": {
                        "ir": recent_data['ir'].tolist(),
                        "red": recent_data['red'].tolist()
                    },
                    "temperature": recent_data['temperature'].tolist(),
                    "humidity": recent_data['humidity'].tolist(),
                    "force": recent_data['force'].tolist(),
                    "timestamps": recent_data['timestamps']
                }
            }

            return jsonify(response_data), 200

        except Exception as e:
            return jsonify({
                "success": False,
                "error": str(e)
            }), 500

    @app.route('/health', methods=['GET'])
    def health_check():
        """Health check endpoint."""
        return jsonify({
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "service": "VitalGuard AI"
        }), 200

    return app


# ======================= MAIN APPLICATION =======================
def initialize_application():
    """
    Initialize the application (data store and Flask app).
    This function is called both in development mode and by Gunicorn.
    """
    print("=" * 70)
    print("  🩺 VitalGuard AI - Health Monitoring System")
    print("  📡 Real-time Vital Signs Processing Server")
    print("=" * 70)
    print()

    # Initialize data storage.
    print("🔧 Initializing data store...")
    data_store = SharedDataStore(
        max_size=MAX_DATA_BUFFER_SIZE,
        persist_file=DATA_FILE
    )

    # Create a Flask application.
    print("🔧 Creating Flask server...")
    app = create_flask_app(data_store)

    print(f"📊 Buffer capacity: {MAX_DATA_BUFFER_SIZE} data points")
    print(f"💾 Data persistence: {DATA_FILE}")
    print("=" * 70)
    print("✅ Application initialized successfully")
    print("=" * 70)

    return app


# ======================= MODULE-LEVEL APP (for Gunicorn) =======================
# Gunicorn will import this app object
app = initialize_application()


# ======================= DEVELOPMENT MODE ENTRY POINT =======================
def main():
    """
    Development mode entry point.
    Used when running: python main.py
    """
    print(f"\n🚀 Starting server on {FLASK_HOST}:{FLASK_PORT}...")
    print(f"🔗 Send POST requests to: http://{FLASK_HOST}:{FLASK_PORT}/api/vitals")
    print("\nPress Ctrl+C to stop the server\n")
    try:
        # Use Flask built-in server for development
        app.run(host=FLASK_HOST, port=FLASK_PORT, debug=False, threaded=True)
    except KeyboardInterrupt:
        print("\n⚠️  Received shutdown signal")
    finally:
        print("👋 Server stopped. Goodbye!")


# ======================= DIRECT EXECUTION =======================
if __name__ == "__main__":
    main()
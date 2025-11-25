# integrated_har_app.py
# An integrated application that:
# 1. Runs a Flask server to receive accelerometer data from ESP32
# 2. Stores recent data in memory
# 3. Periodically processes the data using LLM for activity recognition
# All components run in the same process using threading.

import os
import json
import time
import threading
from datetime import datetime
from collections import deque
from typing import Optional, Deque, Dict, Any
from abc import ABC, abstractmethod

import numpy as np
from flask import Flask, request, jsonify
from openai import OpenAI, OpenAIError

# ======================= CONFIGURATION =======================
# --- LLM Configuration ---
API_KEY = os.environ.get("OPENAI_API_KEY", "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")

BASE_URL = None  # Keep as None for standard OpenAI endpoint
MODEL_NAME = "gpt-4.1-mini"
TEMPERATURE = 0.2
TIMEOUT_SEC = 45
RETRY = 2

# --- Data Processing Configuration ---
WINDOW_POINTS = 120  # Number of data points needed for one prediction
PREDICTION_INTERVAL_SEC = 10  # How often to run predictions (in seconds)
MAX_DATA_BUFFER_SIZE = 200  # Maximum number of data points to keep in memory

# --- Flask Server Configuration ---
FLASK_HOST = '0.0.0.0'  # Listen on all interfaces (for cloud deployment)
FLASK_PORT = 9999  # Port for the Flask server
DATA_FILE = 'accelerometer_data.jsonl'  # File to persist data

DEVICE = "ESP32 Sensor"
ATTACHED_LOC = "Waist"
SETTING = "Real-time streaming data"

# ======================= SHARED DATA STORE =======================
class SharedDataStore:
    """
    Thread-safe data store for accelerometer readings.
    Stores recent data points in memory and optionally persists to disk.
    """

    def __init__(self, max_size: int, persist_file: Optional[str] = None):
        self.max_size = max_size
        self.persist_file = persist_file
        # Use deque for efficient append and automatic size limiting
        self.data_buffer: Deque[Dict[str, Any]] = deque(maxlen=max_size)
        self.lock = threading.Lock()  # Thread-safe access

        print(f"INFO: SharedDataStore initialized with max_size={max_size}")

        # Create persist file if it doesn't exist
        if self.persist_file and not os.path.exists(self.persist_file):
            open(self.persist_file, 'w').close()
            print(f"INFO: Created data persistence file: {self.persist_file}")

    def add_data_point(self, x: float, y: float, z: float,
                       client_timestamp: Optional[str] = None) -> None:
        """
        Adds a new accelerometer data point to the buffer.
        Thread-safe operation.
        """
        data_point = {
            'x': x,
            'y': y,
            'z': z,
            'client_timestamp': client_timestamp,
            'server_timestamp': datetime.now().isoformat()
        }

        with self.lock:
            self.data_buffer.append(data_point)

        # Optionally persist to disk
        if self.persist_file:
            try:
                with open(self.persist_file, 'a') as f:
                    f.write(json.dumps(data_point) + '\n')
            except Exception as e:
                print(f"WARNING: Failed to persist data to disk: {e}")

    def get_recent_data(self, count: int) -> Optional[np.ndarray]:
        """
        Retrieves the most recent 'count' data points as a numpy array.

        Returns:
            numpy array of shape (3, count) with [x, y, z] channels,
            or None if insufficient data is available.
        """
        with self.lock:
            buffer_size = len(self.data_buffer)

            if buffer_size < count:
                print(f"WARNING: Requested {count} points but only {buffer_size} available in buffer.")
                return None

            # Get the last 'count' items
            recent_items = list(self.data_buffer)[-count:]

            # Extract x, y, z arrays
            x_values = [item['x'] for item in recent_items]
            y_values = [item['y'] for item in recent_items]
            z_values = [item['z'] for item in recent_items]

            # Stack into (3, count) array
            sensor_data = np.array([x_values, y_values, z_values])

            return sensor_data

    def get_buffer_info(self) -> Dict[str, Any]:
        """Returns information about the current buffer state."""
        with self.lock:
            return {
                'current_size': len(self.data_buffer),
                'max_size': self.max_size,
                'utilization': f"{len(self.data_buffer) / self.max_size * 100:.1f}%"
            }


# ======================= LLM INTERFACE =======================
class LLMInterface(ABC):
    """
    Abstract Base Class for LLM clients.
    Defines a standard interface for making predictions.
    """

    @abstractmethod
    def predict(self, prompt: str) -> str:
        """
        Sends a prompt to the LLM and returns the response.

        Args:
            prompt: The input prompt string for the LLM.

        Returns:
            The text response from the LLM.
        """
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
        """
        Sends a prompt to OpenAI API with retry mechanism.
        """
        last_error = None

        for attempt in range(self.retries + 1):
            try:
                print(f"INFO: Sending request to OpenAI API (attempt {attempt + 1}/{self.retries + 1})...")

                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {
                            "role": "system",
                            "content": "" # TODO: You can add system-level instructions here if needed
                        },
                        {"role": "user", "content": prompt}
                    ],
                    temperature=self.temperature,
                    timeout=self.timeout
                )

                print("INFO: Successfully received response from OpenAI API.")
                return response.choices[0].message.content.strip()

            except OpenAIError as e:
                last_error = e
                print(f"WARNING: OpenAI API call failed: {e}")
                if attempt < self.retries:
                    time.sleep(1.0)  # Wait before retry

        # All retries failed
        raise RuntimeError(f"LLM call failed after {self.retries + 1} attempts. Last error: {last_error}")


# ======================= FLASK SERVER =======================
def create_flask_app(data_store: SharedDataStore) -> Flask:
    """
    Creates and configures the Flask application.
    Args:
        data_store: The shared data store instance to write incoming data to.
        llm_client: The LLM client instance for making predictions.
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
            "service": "Integrated HAR System",
            "buffer_status": buffer_info,
            "endpoints": {
                "/": "Server status",
                "/api/accelerometer": "Receive sensor data (POST)",
                "/api/buffer": "Check buffer status (GET)",
                "/api/har_predict": "Trigger a HAR prediction (GET)",
                "/health": "Health check"
            }
        })

    @app.route('/api/accelerometer', methods=['POST'])
    def receive_accelerometer_data():
        """
        接收来自 ESP32 或其他传感器的加速度计数据窗口。
        Receives a window of accelerometer data from ESP32 or other sensors.

        期望的 JSON 格式 (Expected JSON format):
        {
            "data": [
                {"x": 0.123, "y": -0.456, "z": 9.81},
                {"x": 0.124, "y": -0.457, "z": 9.82},
                ...
            ]
        }

        或者兼容旧格式 (Or backward compatible with old format):
        {
            "x": 0.123,
            "y": -0.456,
            "z": 9.81
        }
        """
        try:
            request_data = request.get_json()

            # 验证请求数据是否存在
            if not request_data:
                return jsonify({
                    "success": False,
                    "error": {
                        "code": "INVALID_REQUEST",
                        "message": "Request body is empty or not JSON"
                    }
                }), 400

            # 🆕 新增：检查是批量数据还是单个数据点
            if 'data' in request_data:
                # ===== 批量数据处理逻辑 (Batch Data Processing) =====
                data_points = request_data['data']

                # 验证 data 字段是否为列表
                if not isinstance(data_points, list):
                    return jsonify({
                        "success": False,
                        "error": {
                            "code": "INVALID_FORMAT",
                            "message": "'data' field must be an array"
                        }
                    }), 400

                # 验证列表不为空
                if len(data_points) == 0:
                    return jsonify({
                        "success": False,
                        "error": {
                            "code": "EMPTY_DATA",
                            "message": "Data array is empty"
                        }
                    }), 400

                # 逐个验证并添加每个数据点
                added_count = 0
                errors = []

                for idx, point in enumerate(data_points):
                    # 验证每个数据点的必需字段
                    if not all(key in point for key in ['x', 'y', 'z']):
                        errors.append(f"Point {idx}: Missing required fields (x, y, z)")
                        continue

                    try:
                        # 添加数据点到缓冲区
                        data_store.add_data_point(
                            x=point['x'],
                            y=point['y'],
                            z=point['z'],
                            client_timestamp=point.get('timestamp')
                        )
                        added_count += 1
                    except Exception as e:
                        errors.append(f"Point {idx}: {str(e)}")

                # 返回批量处理结果
                response = {
                    "success": True,
                    "message": f"Batch data processed: {added_count}/{len(data_points)} points added",
                    "stats": {
                        "total_received": len(data_points),
                        "successfully_added": added_count,
                        "errors": len(errors)
                    }
                }

                if errors:
                    response["warnings"] = errors

                print(f"INFO: Batch processed - {added_count} points added, {len(errors)} errors")
                return jsonify(response), 201

            else:
                # ===== 单个数据点处理逻辑 (兼容旧格式) =====
                # Single Data Point Processing (Backward Compatibility)

                # 验证必需字段
                if not all(key in request_data for key in ['x', 'y', 'z']):
                    return jsonify({
                        "success": False,
                        "error": {
                            "code": "MISSING_FIELDS",
                            "message": "Missing required fields: x, y, z"
                        }
                    }), 400

                # 添加单个数据点到缓冲区
                data_store.add_data_point(
                    x=request_data['x'],
                    y=request_data['y'],
                    z=request_data['z'],
                    client_timestamp=request_data.get('timestamp')
                )

                return jsonify({
                    "success": True,
                    "message": "Single data point received successfully"
                }), 201

        except Exception as e:
            print(f"ERROR: Failed to process incoming data: {e}")
            import traceback
            traceback.print_exc()  # 打印完整的错误堆栈，便于调试

            return jsonify({
                "success": False,
                "error": {
                    "code": "SERVER_ERROR",
                    "message": str(e)
                }
            }), 500

    @app.route('/api/buffer', methods=['GET'])
    def get_buffer_status():
        """Returns current buffer status for debugging."""
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


    @app.route('/health', methods=['GET'])
    def health_check():
        """Health check endpoint."""
        return jsonify({
            "status": "healthy",
            "timestamp": datetime.now().isoformat()
        }), 200

    @app.route('/api/data', methods=['GET'])
    def get_recent_data():
        """get the most recent accelerometer data records, for debugging purposes"""
        try:
            # read 'limit' query parameter, default to 10
            limit = request.args.get('limit', default=10, type=int)

            # read all lines and parse the last 'limit' lines
            data_list = []
            with open(DATA_FILE, 'r') as f:
                lines = f.readlines()
                for line in lines[-limit:]:
                    if line.strip():
                        data_list.append(json.loads(line))

            return jsonify({
                "count": len(data_list),
                "data": data_list
            }), 200

        except Exception as e:
            return jsonify({
                "success": False,
                "error": str(e)
            }), 500

    return app


# ======================= MAIN APPLICATION =======================
def main():
    """
    Main entry point for the integrated HAR application.
    Starts both the Flask server and the prediction worker.
    """
    print("=" * 60)
    print("  Integrated Human Activity Recognition System")
    print("=" * 60)
    print()

    # Initialize shared components
    print("INFO: Initializing shared data store...")
    data_store = SharedDataStore(
        max_size=MAX_DATA_BUFFER_SIZE,
        persist_file=DATA_FILE
    )

    print("INFO: Initializing LLM client...")
    try:
        llm_client = OpenAI_LLM(
            api_key=API_KEY,
            model=MODEL_NAME,
            base_url=BASE_URL,
            temperature=TEMPERATURE,
            timeout=TIMEOUT_SEC,
            retries=RETRY
        )
    except ValueError as e:
        print(f"FATAL: {e}")
        return

    # Create Flask app
    print("INFO: Creating Flask server...")
    app = create_flask_app(data_store, llm_client)

    # Start prediction worker in a background thread
    # print("INFO: Starting prediction worker thread...")
    # prediction_thread = threading.Thread(
    #     target=prediction_worker,
    #     args=(data_store, llm_client, PREDICTION_INTERVAL_SEC, WINDOW_POINTS),
    #     daemon=True  # Thread will automatically close when main thread exits
    # )
    # prediction_thread.start()

    # Start Flask server (this will block)
    print(f"INFO: Starting Flask server on {FLASK_HOST}:{FLASK_PORT}...")
    print("INFO: Server is ready to receive data from ESP32.\n")
    print("=" * 60)
    print("Press Ctrl+C to stop the server")
    print("=" * 60 + "\n")

    try:
        # Run Flask server
        # Note: For production deployment, use a production WSGI server like gunicorn
        app.run(host=FLASK_HOST, port=FLASK_PORT, debug=False, threaded=True)
    except KeyboardInterrupt:
        print("\nINFO: Received shutdown signal. Stopping server...")
    finally:
        print("INFO: Application stopped.")


if __name__ == "__main__":
    # Prerequisites:
    # 1. Install required packages: pip install flask openai numpy
    # 2. Set your OpenAI API key in the API_KEY variable at the top
    # 3. Deploy this script to your cloud server
    # 4. Configure your ESP32 to send POST requests to: http://your-server-ip:9999/api/accelerometer
    main()

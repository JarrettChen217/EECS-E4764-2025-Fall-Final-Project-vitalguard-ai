# vital_guard_server.py
# VitalGuard AI Health Monitoring System - GCP Server Side
# Function: Receive ESP32 multi-sensor data, process in real-time, LLM health analysis.

import os
import json
import threading
from datetime import datetime
from collections import deque
from typing import Optional, Deque, Dict, Any, List

import numpy as np
from flask import Flask, request, jsonify

from vitalguard import (VitalSignsDataPoint, SharedDataStore,
                        DataValidator, VitalSignsAnalyzer,
                        HealthReportService, OpenAI_LLM)

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

# Static folder for Web UI
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "vitalguard", "web", "static")


# ======================= FLASK SERVER =======================
def create_flask_app(data_store: SharedDataStore,
                     analyzer: VitalSignsAnalyzer,
                     report_service: HealthReportService) -> Flask:
    """
    Creates and configures the Flask application.
    Args:
        data_store: The shared data store instance to write incoming data to.
        analyzer: The VitalSignsAnalyzer instance for computing vital sign status.
        report_service: The HealthReportService instance for generating health reports.
    Returns:
        Configured Flask app instance.
    """
    app = Flask(__name__,
                static_folder=STATIC_DIR,
                static_url_path="/static")
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

    @app.route('/api/status/current', methods=['GET'])
    def get_current_status():
        """
        Get current discretized vital-sign status (for UI).
        """
        try:
            status = analyzer.compute_current_status()
            history = analyzer.get_history(limit=20)
            return jsonify({
                "success": True,
                "status": status,
                "history": history
            }), 200
        except ValueError as e:
            # Typically insufficient data
            return jsonify({
                "success": False,
                "error": str(e)
            }), 400
        except Exception as e:
            return jsonify({
                "success": False,
                "error": str(e)
            }), 500

    @app.route('/api/report/manual', methods=['POST', 'GET'])
    def generate_manual_report():
        """
        Manually trigger LLM-based health report generation.
        """
        try:
            report = report_service.generate_report()
            return jsonify({
                "success": True,
                "report": report
            }), 200
        except ValueError as e:
            return jsonify({
                "success": False,
                "error": str(e)
            }), 400
        except Exception as e:
            return jsonify({
                "success": False,
                "error": str(e)
            }), 500

    @app.route('/ui', methods=['GET'])
    def ui_index():
        """
        Serve the main Web UI page.
        iPhone can open http://<server>:<port>/ui to see dashboard.
        """
        return app.send_static_file('index.html')

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
    # Initialize ML analyzer.
    print("🔧 Initializing ML analyzer...")
    analyzer = VitalSignsAnalyzer(
        data_store=data_store,
        window_points=WINDOW_POINTS,
        history_size=200
    )
    # Initialize LLM interface.
    print("🔧 Initializing LLM interface...")
    llm_client = OpenAI_LLM(
        api_key=API_KEY,
        base_url=BASE_URL,
        model=MODEL_NAME,
        temperature=TEMPERATURE,
        timeout=TIMEOUT_SEC,
        retries=RETRY
    )

    # Initialize health report service.
    print("🔧 Initializing health report service...")
    report_service = HealthReportService(
        analyzer=analyzer,
        llm_client=llm_client
    )

    # Create a Flask application.
    print("🔧 Creating Flask server...")
    app = create_flask_app(data_store, analyzer, report_service)

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

# vital_guard_server.py
# VitalGuard AI 健康监测系统 - GCP服务器端
# 功能：接收ESP32多传感器数据、实时处理、LLM健康分析

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
WINDOW_POINTS = 300  # 窗口大小：300个数据点用于心率计算 (约6秒@20ms采样)
PREDICTION_INTERVAL_SEC = 30  # LLM分析间隔：每30秒生成一次健康报告
MAX_DATA_BUFFER_SIZE = 1500  # 最大缓冲：1500个数据点 (约30秒数据)

# --- Flask Server Configuration ---
FLASK_HOST = '0.0.0.0'
FLASK_PORT = 9999
DATA_FILE = 'vital_signs_data.jsonl'  # 持久化存储文件

# --- Device Information ---
DEVICE_TYPE = "ESP32 VitalGuard"
SENSOR_LOCATION = "Wrist"


# ======================= DATA MODELS =======================
class VitalSignsDataPoint:
    """
    单个周期的生命体征数据点模型
    Represents a single cycle of vital signs measurement
    """

    def __init__(self,
                 cycle: int,
                 timestamp: str,
                 ir: int,
                 red: int,
                 temperature: float,
                 humidity: float,
                 force: float):
        self.cycle = cycle
        self.timestamp = timestamp
        # PPG数据
        self.ir = ir
        self.red = red
        # 环境数据
        self.temperature = temperature
        self.humidity = humidity
        # 力学数据
        self.force = force
        # 服务器接收时间
        self.server_timestamp = datetime.now().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            'cycle': self.cycle,
            'timestamp': self.timestamp,
            'ppg': {
                'ir': self.ir,
                'red': self.red
            },
            'temperature': self.temperature,
            'humidity': self.humidity,
            'force': self.force,
            'server_timestamp': self.server_timestamp
        }


# ======================= SHARED DATA STORE (ENHANCED) =======================
class SharedDataStore:
    """
    线程安全的多传感器数据存储
    支持批量写入、时序查询、数据聚合
    """

    def __init__(self, max_size: int, persist_file: Optional[str] = None):
        self.max_size = max_size
        self.persist_file = persist_file

        # 使用deque实现高效的FIFO缓冲
        self.data_buffer: Deque[VitalSignsDataPoint] = deque(maxlen=max_size)
        self.lock = threading.Lock()

        # 统计信息
        self.total_received = 0
        self.total_batches = 0

        print(f"✅ SharedDataStore initialized: max_size={max_size}")

        # 创建持久化文件
        if self.persist_file and not os.path.exists(self.persist_file):
            open(self.persist_file, 'w').close()
            print(f"📁 Created persistence file: {self.persist_file}")

    def add_batch(self, data_points: List[VitalSignsDataPoint]) -> int:
        """
        批量添加数据点（线程安全）
        Returns: 成功添加的数据点数量
        """
        added_count = 0

        with self.lock:
            for point in data_points:
                self.data_buffer.append(point)
                added_count += 1

            self.total_received += added_count
            self.total_batches += 1

        # 异步持久化（避免阻塞）
        if self.persist_file and added_count > 0:
            threading.Thread(
                target=self._persist_batch,
                args=(data_points,),
                daemon=True
            ).start()

        return added_count

    def _persist_batch(self, data_points: List[VitalSignsDataPoint]) -> None:
        """后台线程：批量持久化数据"""
        try:
            with open(self.persist_file, 'a') as f:
                for point in data_points:
                    f.write(json.dumps(point.to_dict()) + '\n')
        except Exception as e:
            print(f"⚠️  Persistence failed: {e}")

    def get_recent_data(self, count: int) -> Optional[Dict[str, np.ndarray]]:
        """
        获取最近的N个数据点，按传感器类型组织

        Returns:
            {
                'ir': np.array([...]),
                'red': np.array([...]),
                'temperature': np.array([...]),
                'humidity': np.array([...]),
                'force': np.array([...]),
                'timestamps': [...]
            }
            如果数据不足则返回None
        """
        with self.lock:
            buffer_size = len(self.data_buffer)

            if buffer_size < count:
                print(f"⚠️  Insufficient data: requested {count}, available {buffer_size}")
                return None

            # 获取最近的count个数据点
            recent_items = list(self.data_buffer)[-count:]

            # 按传感器类型组织数据
            return {
                'ir': np.array([item.ir for item in recent_items]),
                'red': np.array([item.red for item in recent_items]),
                'temperature': np.array([item.temperature for item in recent_items]),
                'humidity': np.array([item.humidity for item in recent_items]),
                'force': np.array([item.force for item in recent_items]),
                'timestamps': [item.timestamp for item in recent_items]
            }

    def get_ppg_window(self, window_size: int = 300) -> Optional[Dict[str, np.ndarray]]:
        """
        获取用于心率计算的PPG数据窗口
        专门用于信号处理算法
        """
        data = self.get_recent_data(window_size)
        if data is None:
            return None

        return {
            'ir': data['ir'],
            'red': data['red'],
            'timestamps': data['timestamps']
        }

    def get_buffer_info(self) -> Dict[str, Any]:
        """获取缓冲区状态信息"""
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
    """数据包验证器：确保接收的数据格式正确"""

    @staticmethod
    def validate_batch_request(data: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """
        验证批量数据请求格式
        Returns: (is_valid, error_message)
        """
        # 必需字段检查
        required_fields = ['device_id', 'batch_info', 'data']
        for field in required_fields:
            if field not in data:
                return False, f"Missing required field: {field}"

        # batch_info验证
        batch_info = data['batch_info']
        required_batch_fields = ['start_cycle', 'end_cycle', 'total_points']
        for field in required_batch_fields:
            if field not in batch_info:
                return False, f"Missing batch_info field: {field}"

        # 数据数组验证
        data_array = data['data']
        if not isinstance(data_array, list) or len(data_array) == 0:
            return False, "Data array is empty or not a list"

        # 验证第一个数据点的结构（采样验证）
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

        return True, None


# ======================= LLM INTERFACE (UNCHANGED) =======================
class LLMInterface(ABC):
    """LLM客户端抽象基类"""

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
        接收来自ESP32的生命体征数据
        支持批量数据传输（推荐）和单点传输（兼容）
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

            # ===== 批量数据处理 (Recommended) =====
            if 'data' in request_data and 'batch_info' in request_data:
                # 验证数据格式
                is_valid, error_msg = DataValidator.validate_batch_request(request_data)
                if not is_valid:
                    return jsonify({
                        "success": False,
                        "error": {
                            "code": "VALIDATION_FAILED",
                            "message": error_msg
                        }
                    }), 400

                # 解析批量数据
                device_id = request_data['device_id']
                batch_info = request_data['batch_info']
                data_points_raw = request_data['data']

                # 转换为VitalSignsDataPoint对象
                data_points = []
                parsing_errors = []

                for idx, point in enumerate(data_points_raw):
                    try:
                        vital_signs = point['vital_signs']
                        ppg = vital_signs['ppg']

                        data_point = VitalSignsDataPoint(
                            cycle=point['cycle'],
                            timestamp=point['timestamp'],
                            ir=ppg['ir'],
                            red=ppg['red'],
                            temperature=vital_signs.get('temperature', 0.0),
                            humidity=vital_signs.get('humidity', 0.0),
                            force=vital_signs.get('force', 0.0)
                        )
                        data_points.append(data_point)
                    except Exception as e:
                        parsing_errors.append(f"Point {idx}: {str(e)}")

                # 批量添加到数据存储
                added_count = data_store.add_batch(data_points)

                # 返回处理结果
                response = {
                    "success": True,
                    "message": f"Batch processed successfully",
                    "device_id": device_id,
                    "batch_info": {
                        "cycles": f"{batch_info['start_cycle']}-{batch_info['end_cycle']}",
                        "total_received": len(data_points_raw),
                        "successfully_stored": added_count,
                        "parsing_errors": len(parsing_errors)
                    }
                }

                if parsing_errors:
                    response["warnings"] = parsing_errors[:10]  # 只返回前10个错误

                print(f"📦 Batch received: {added_count} points from {device_id}")
                return jsonify(response), 201

            # ===== 单点数据处理 (Backward Compatibility) =====
            else:
                # 检查必需字段
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
                data_point = VitalSignsDataPoint(
                    cycle=request_data['cycle'],
                    timestamp=request_data['timestamp'],
                    ir=ppg['ir'],
                    red=ppg['red'],
                    temperature=request_data['temperature'],
                    humidity=request_data.get('humidity', 0.0),
                    force=request_data.get('force', 0.0)
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
        """获取数据缓冲区状态"""
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
        """获取最近的数据点（用于调试和可视化）"""
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

            # 格式化返回数据
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
        """健康检查端点（用于负载均衡器）"""
        return jsonify({
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "service": "VitalGuard AI"
        }), 200

    return app


# ======================= MAIN APPLICATION =======================
def main():
    """主程序入口"""
    print("=" * 70)
    print("  🩺 VitalGuard AI - Health Monitoring System")
    print("  📡 Real-time Vital Signs Processing Server")
    print("=" * 70)
    print()

    # 初始化数据存储
    print("🔧 Initializing data store...")
    data_store = SharedDataStore(
        max_size=MAX_DATA_BUFFER_SIZE,
        persist_file=DATA_FILE
    )

    # 创建Flask应用
    print("🔧 Creating Flask server...")
    app = create_flask_app(data_store)

    # 启动服务器
    print(f"🚀 Starting server on {FLASK_HOST}:{FLASK_PORT}...")
    print(f"📊 Buffer capacity: {MAX_DATA_BUFFER_SIZE} data points")
    print(f"💾 Data persistence: {DATA_FILE}")
    print()
    print("=" * 70)
    print("✅ Server is ready to receive data from ESP32")
    print("🔗 Send POST requests to: http://your-server-ip:9999/api/vitals")
    print("=" * 70)
    print("\nPress Ctrl+C to stop the server\n")

    try:
        app.run(host=FLASK_HOST, port=FLASK_PORT, debug=False, threaded=True)
    except KeyboardInterrupt:
        print("\n⚠️  Received shutdown signal")
    finally:
        print("👋 Server stopped. Goodbye!")
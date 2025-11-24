# integrated_har_app.py
# An integrated application that:
# 1. Runs a Flask server to receive accelerometer data from ESP32
# 2. Stores recent data in memory
# 3. Periodically processes the data using LLM for activity recognition
# All components run in the same process using threading.

import os
import re
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

from NormWear.zero_shot.msitf_fusion import NormWearZeroShot
import torch
from torch import nn

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

# --- HAR Task Configuration ---
CANDIDATES = ["WALKING", "WALKING_UPSTAIRS", "WALKING_DOWNSTAIRS",
              "SITTING", "STANDING", "LAYING"]
DEVICE = "ESP32 Sensor"
ATTACHED_LOC = "Waist"
SETTING = "Real-time streaming data"


# =============================================================
class LinearHead(nn.Module):
    """用于加载分类器权重的模型结构，必须与训练时一致"""
    def __init__(self, in_dim, num_classes):
        super().__init__()
        self.fc = nn.Linear(in_dim, num_classes)
    def forward(self, x):
        return self.fc(x)

class UCIHARDeployment:
    def __init__(self, encoder_weight_path, msitf_ckpt_path, classifier_ckpt_path, device='cpu'):
        self.device = torch.device(device)
        # 加载冻结的预训练编码器
        self.encoder = NormWearZeroShot(weight_path=encoder_weight_path, msitf_ckpt=msitf_ckpt_path).to(self.device)
        self.encoder.eval()
        # 加载训练好的分类器
        checkpoint = torch.load(classifier_ckpt_path, map_location=self.device)
        emb_dim = checkpoint['embedding_dim']
        num_classes = checkpoint['num_classes']
        self.classifier = LinearHead(emb_dim, num_classes).to(self.device)
        self.classifier.load_state_dict(checkpoint['model_state_dict'])
        self.classifier.eval()
        # 定义任务和标签映射
        self.task_prompt = "Recognize the type of human physical activity based on IMU signals."
        self.label_map = {
            0: "WALKING", 1: "WALKING_UPSTAIRS", 2: "WALKING_DOWNSTAIRS",
            3: "SITTING", 4: "STANDING", 5: "LAYING"
        }
    @torch.no_grad()
    def predict(self, X_signal):
        """
        输入: X_signal - torch.Tensor, shape [batch_size, 3, 128]
        输出: 活动类别字符串列表
        """
        # 提取 embedding
        txt_embed = self.encoder.txt_encode([self.task_prompt])
        query_embed = txt_embed[:1, :]
        emb = self.encoder.signal_encode(X_signal, query_embed, sampling_rate=50)
        if emb.dim() == 3:
            emb = emb.mean(dim=1)
        # 分类
        logits = self.classifier(emb)
        preds = torch.argmax(logits, dim=1).cpu().numpy()
        # 转换为活动名称
        return [self.label_map[p] for p in preds]

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
                            "content": "You are a HAR (Human Activity Recognition) classifier. Always answer with exactly one label from the provided candidate activities."
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


# ======================= PROMPT BUILDER =======================
def format_array(arr: np.ndarray, precision: int = 3) -> str:
    """Formats a numpy array into a readable string."""
    return "[" + ", ".join(f"{v:.{precision}f}" for v in arr.tolist()) + "]"


def build_har_prompt(sensor_data: np.ndarray, style: str = "cot") -> str:
    """
    Constructs a structured prompt for HAR classification.

    Args:
        sensor_data: numpy array of shape (3, N) containing [acc_x, acc_y, acc_z]
        style: Prompt style, either "cot" for chain-of-thought or "direct".

    Returns:
        A formatted prompt string for the LLM.
    """
    acc_x, acc_y, acc_z = sensor_data[0], sensor_data[1], sensor_data[2]

    candidates_str = "{" + ", ".join(CANDIDATES) + "}"

    prompt = f"""Device: {DEVICE}
        Attached Location: {ATTACHED_LOC}
        Setting: {SETTING}

        Task: Human Activity Recognition (HAR). Choose exactly one label from {candidates_str}.

        Signal Specification:
        - Window length: {sensor_data.shape[1]} samples from continuous data stream
        - Channels (C=3):
          0: acc_x -> X-axis total acceleration (includes gravity)
          1: acc_y -> Y-axis total acceleration (includes gravity)
          2: acc_z -> Z-axis total acceleration (includes gravity)
        - Units: Raw sensor values (approximate g-units, where ~9.8 represents gravity)

        Accelerometer Data:
        X-axis: {format_array(acc_x)}
        Y-axis: {format_array(acc_y)}
        Z-axis: {format_array(acc_z)}
        """.strip()

    if style == "cot":
        tail = (
            "Question: Which activity is being performed?\n"
            f"Please explain your reasoning step by step, then give the final activity label strictly as one of {candidates_str}.\n"
            "End your response with a single line in the form: ANSWER: <LABEL>."
        )
    else:
        tail = (
            "Question: Which activity is being performed?\n"
            f"Give only the activity label strictly as one of {candidates_str}. Respond with exactly one label and nothing else."
        )
    return prompt + "\n\n" + tail


# ======================= LABEL EXTRACTION =======================
_LABEL_RE = re.compile(r"(WALKING_UPSTAIRS|WALKING_DOWNSTAIRS|WALKING|SITTING|STANDING|LAYING)", re.I)


def extract_activity_label(text: str) -> str | None:
    m = re.search(r"ANSWER:\s*([A-Za-z_]+)", text)
    if m:
        cand = m.group(1).upper()
        if cand in CANDIDATES:
            return cand
    m = _LABEL_RE.search(text.upper())
    if m:
        return m.group(1).upper()
    return None


# ======================= FLASK SERVER =======================
def create_flask_app(data_store: SharedDataStore, llm_client: LLMInterface) -> Flask:
    """
    Creates and configures the Flask application.
    Args:
        data_store: The shared data store instance to write incoming data to.
        llm_client: The LLM client instance for making predictions.
    Returns:
        Configured Flask app instance.
    """
    app = Flask(__name__)

    # ======================= LOAD TORCH MODELS =======================
    print("INFO: Loading models, please wait...")
    try:
        predictor = UCIHARDeployment(
            encoder_weight_path="/Users/haochen/Documents/Gogs_Repositories/AIoT_Repositories/EECS-E4764-2025-Fall-Labs/Lab6/dev/NormWear/pre_trained_models/normwear_last_checkpoint-15470-correct.pth",
            msitf_ckpt_path="/Users/haochen/Documents/Gogs_Repositories/AIoT_Repositories/EECS-E4764-2025-Fall-Labs/Lab6/dev/NormWear/pre_trained_models/normwear_msitf_zeroshot_last_checkpoint-5.pth",
            classifier_ckpt_path="/Users/haochen/Documents/Gogs_Repositories/AIoT_Repositories/EECS-E4764-2025-Fall-Labs/Lab6/dev/uci_har_linear_head.pth",
            device='cpu'
        )
        print("INFO: Models loaded successfully!")
    except Exception as e:
        print(f"FATAL: Failed to load models. Error: {e}")
        predictor = None

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

    @app.route('/api/har_predict', methods=['GET'])
    def trigger_har_prediction():
        """
        On-demand endpoint to trigger a HAR prediction.
        Called by ESP32 or other clients.
        """
        try:
            # 1. Get Data
            sensor_data = data_store.get_recent_data(WINDOW_POINTS)
            # Check if data is sufficient
            if sensor_data is None:
                buffer_info = data_store.get_buffer_info()
                return jsonify({
                    "success": False,
                    "error": {
                        "code": "INSUFFICIENT_DATA",
                        "message": f"Insufficient data for prediction. Required: {WINDOW_POINTS} points, Available: {buffer_info['current_size']} points."
                    }
                }), 422  # 422 Unprocessable Entity is a good status code here
            # 2. Build Prompt
            prompt = build_har_prompt(sensor_data)
            # 3. Call LLM for prediction
            try:
                llm_response = llm_client.predict(prompt)
                print(llm_response) # TODO: remove debug print
            except RuntimeError as e:
                # LLM call failed
                return jsonify({
                    "success": False,
                    "error": {
                        "code": "LLM_API_ERROR",
                        "message": str(e)
                    }
                }), 503  # 503 Service Unavailable
            # 4. Extract Label
            predicted_label = extract_activity_label(llm_response)
            if not predicted_label:
                # Failed to extract label
                return jsonify({
                    "success": False,
                    "error": {
                        "code": "LABEL_EXTRACTION_FAILED",
                        "message": "Could not extract a valid activity label from the LLM response.",
                        "llm_raw_response": llm_response
                    }
                }), 500
            # 5. Return success response
            print(f"INFO: Successful prediction triggered via API. Label: {predicted_label}")
            return jsonify({
                "success": True,
                "prediction": {
                    "label": predicted_label,
                    "llm_raw_response_snippet": f"{llm_response[:100]}..."
                },
                "timestamp": datetime.now().isoformat()
            }), 200
        except Exception as e:
            # Catch any other unexpected errors
            print(f"ERROR: Unexpected error in /api/har_predict: {e}")
            return jsonify({
                "success": False,
                "error": {
                    "code": "INTERNAL_SERVER_ERROR",
                    "message": "An unexpected error occurred on the server."
                }
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

    @app.route('/api/har_predict_torch', methods=['GET'])
    def trigger_har_predict_torch():
        """
        触发式端点：从 data_store 读取最近的传感器数据，使用微调的 Torch 模型进行预测
        由 ESP32 或其他客户端调用，无需在请求体中传递数据
        """
        if not predictor:
            return jsonify({
                "success": False,
                "error": {
                    "code": "MODEL_UNAVAILABLE",
                    "message": "Model is not available. Check server logs for details."
                }
            }), 503  # Service Unavailable

        try:
            # 1. 从 data_store 获取最近的传感器数据
            sensor_data = data_store.get_recent_data(WINDOW_POINTS)

            # 2. 检查数据是否充足
            if sensor_data is None:
                buffer_info = data_store.get_buffer_info()
                return jsonify({
                    "success": False,
                    "error": {
                        "code": "INSUFFICIENT_DATA",
                        "message": f"Insufficient data for prediction. Required: {WINDOW_POINTS} points, Available: {buffer_info['current_size']} points."
                    }
                }), 422  # 422 Unprocessable Entity

            # 3. 🔥 数据格式转换 (核心步骤)
            #    sensor_data 是一个包含三个 numpy array 的元组/列表
            #    每个 array 的形状是 (128,)
            #    我们需要将它转换为 [1, 3, 128] 的 Tensor
            acc_x, acc_y, acc_z = sensor_data[0], sensor_data[1], sensor_data[2]

            # 验证数据格式和长度
            if not (isinstance(acc_x, np.ndarray) and isinstance(acc_y, np.ndarray) and isinstance(acc_z, np.ndarray)):
                return jsonify({
                    "success": False,
                    "error": {
                        "code": "INVALID_DATA_FORMAT",
                        "message": "Sensor data must be numpy arrays."
                    }
                }), 500

            if not (len(acc_x) == WINDOW_POINTS and len(acc_y) == WINDOW_POINTS and len(acc_z) == WINDOW_POINTS):
                return jsonify({
                    "success": False,
                    "error": {
                        "code": "INVALID_DATA_LENGTH",
                        "message": f"Sensor data length mismatch. Expected: {WINDOW_POINTS}, Got: x={len(acc_x)}, y={len(acc_y)}, z={len(acc_z)}"
                    }
                }), 500

            # 堆叠三个轴的数据成 (3, 128) 的 array，然后增加 batch 维度变为 (1, 3, 128)
            signal_window = np.stack([
                acc_x.astype(np.float32),
                acc_y.astype(np.float32),
                acc_z.astype(np.float32)
            ], axis=0)[None, :, :]  # [None, :, :] 增加 batch 维度

            # 转换为 Torch Tensor
            signal_tensor = torch.from_numpy(signal_window).to(predictor.device)

            # 4. 调用 PyTorch 模型进行预测
            predictions = predictor.predict(signal_tensor)

            # 因为我们一次只预测一个窗口，所以结果列表里只有一个元素
            predicted_label = predictions[0]

            print(f"INFO: Successful Torch prediction triggered via API. Label: {predicted_label}")

            # 5. 返回成功响应
            return jsonify({
                "success": True,
                "prediction": {
                    "label": predicted_label,
                    "model_type": "pytorch_finetuned"
                },
                "timestamp": datetime.now().isoformat()
            }), 200

        except Exception as e:
            # 捕获任何其他意外错误
            print(f"ERROR: Unexpected error in /api/trigger_har_predict_torch: {e}")
            import traceback
            traceback.print_exc()  # 打印完整的错误堆栈，便于调试
            return jsonify({
                "success": False,
                "error": {
                    "code": "INTERNAL_SERVER_ERROR",
                    "message": "An unexpected error occurred on the server."
                }
            }), 500

    return app


# ======================= PREDICTION WORKER =======================
def prediction_worker(data_store: SharedDataStore, llm_client: LLMInterface,
                      interval: int, window_size: int):
    """
    Background worker that periodically performs HAR predictions.
    Runs in a separate thread.

    Args:
        data_store: Shared data store to read sensor data from.
        llm_client: LLM client instance for making predictions.
        interval: Time to wait between predictions (in seconds).
        window_size: Number of data points needed for one prediction.
    """
    print("INFO: Prediction worker started.")
    print(f"INFO: Will perform predictions every {interval} seconds using {window_size} data points.\n")

    prediction_count = 0

    while True:
        try:
            # Wait for the specified interval
            time.sleep(interval)

            # Fetch recent data from the shared store
            sensor_data = data_store.get_recent_data(window_size)

            if sensor_data is None:
                print("INFO: Insufficient data for prediction. Waiting for more data...")
                continue

            # Build prompt and get prediction
            prompt = build_har_prompt(sensor_data)

            try:
                llm_response = llm_client.predict(prompt)
                predicted_label = extract_activity_label(llm_response)

                prediction_count += 1

                # Log the prediction result
                print("\n" + "=" * 60)
                print(f"Prediction #{prediction_count}")
                print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"Predicted Activity: {predicted_label if predicted_label else 'UNCERTAIN'}")
                print(f"LLM Response Snippet: '{llm_response[:80]}...'")
                print("=" * 60 + "\n")

            except RuntimeError as e:
                print(f"ERROR: Prediction failed: {e}")

        except KeyboardInterrupt:
            print("INFO: Prediction worker received shutdown signal.")
            break
        except Exception as e:
            print(f"ERROR: Unexpected error in prediction worker: {e}")
            time.sleep(5)  # Wait before retrying after error


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

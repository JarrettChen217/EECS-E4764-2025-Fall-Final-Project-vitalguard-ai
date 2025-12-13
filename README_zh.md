<!-- Language Switcher -->
<div align="right">
  <a href="README.md">English</a> | <b>中文</b>
</div>

# VitalGuard AI: An AIoT Wearable for Real-Time Health Insights & Alerts

**VitalGuard AI** 是一个紧凑的可穿戴 AIoT 系统，通过持续融合多传感器生命体征数据（心率、体温、活动等），提供个性化的健康洞察，并在检测到异常时触发实时紧急警报。

## 🚀 项目简介 (About The Project)

在慢性病和老年护理领域，诊所之外的持续、低成本监控至关重要。本项目旨在通过 AIoT 技术，为用户提供一种有效的方式来跟踪健康趋势、获取可行的生活建议（如补水、休息提醒），并在发生跌倒或生命体征异常时自动发出警报，从而实现更安全的独立生活，也让家人和护理人员更加安心。

### 主要功能 (Key Features)

-   **持续多维监测**: 集成心率、血氧 (SpO₂)、体温、活动和压力等多个传感器，进行全天候数据采集。
-   **实时数据分析**: 数据通过 ESP32 在边缘端进行初步处理，并实时上传至云端服务器 (GCP)。
-   **AI 驱动的健康报告**: 利用大型语言模型 (LLM) 分析处理后的数据，生成易于理解的健康报告和个性化建议。
-   **紧急警报系统**: 当检测到跌倒或生命体征严重异常时，系统会自动向紧急联系人发送通知。
-   **Web 可视化界面**: 提供一个简洁的 Web UI，用户可以方便地查看自己的健康数据、趋势和 AI 生成的报告。

## 🛠️ 技术栈 (Tech Stack)

| 类别        | 技术                                                         |
| :---------- | :----------------------------------------------------------- |
| **硬件**    | `ESP32`, `MAX86150` (心率/血氧), `TMP117` (体温), `ADXL345` (运动/跌倒) |
| **嵌入式**  | `MicroPython`                                                |
| **云平台**  | `Google Cloud Platform (GCP)`                                |
| **后端**    | `Python`, `Flask` (Web 框架)                                 |
| **部署**    | `Systemd` (服务持久化)                                       |
| **AI 模型** | 通过 API 调用第三方大型语言模型 (LLM)                        |
| **前端**    | `HTML`, `CSS`, `JavaScript`                                  |

## 📂 项目结构 (Project Structure)

```
.
├── `esp32/`                   # ESP32 (MicroPython) code and sensor tests
│   ├── `esp32_main.py`
│   ├── `main.py`
│   └── `sensor_test_codes/`
│       ├── `force.py`
│       ├── `heartrate.py`
│       ├── `heartrate_parse.py`
│       ├── `temp_humidity.py`
│       └── ...
├── `gcp-server/`              # Backend Flask service + utils + web UI
│   ├── `main.py`              # optional local run helper
│   ├── `vital_guard_server.py`# Flask app module (exposes `app`)
│   ├── `requirements.txt`
│   ├── `simple_api_tester.py`
│   ├── `test_llm.py`
│   ├── `vital_signs_data.jsonl`
│   ├── `vitalguard/`         # Python package used by the server
│   │   ├── `__init__.py`
│   │   ├── `config.py`
│   │   ├── `llm_interface.py`
│   │   ├── `llm_service.py`
│   │   ├── `ml_analyzer.py`
│   │   ├── `models.py`
│   │   ├── `storage.py`
│   │   └── `validation.py`
│   └── `web/`
│       ├── `project_website/` # !!**static team website**!!
│       └── `static/`          # lightweight frontend assets used by deployment
├── `docs/`                    # design docs, datasheets, diagrams
│   ├── `Block_Diagram.png`
│   ├── `HDC1080.pdf`
│   └── ...
├── `README.md`
└── `README_zh.md`
```

## 🏁 开始使用 (Getting Started)

本指南将引导你完成从硬件配置到云端服务部署的完整流程。

### 依赖环境 (Prerequisites)

-   **通用**: `Git`
-   **硬件端**: Python 3.x, `pip`, `esptool`, `mpfshell`
-   **服务端**: GCP 账户, 一台配置好的 Ubuntu 服务器, Python 3.x, `pip`, `venv`

---

### **第一部分: ESP32 硬件设置**

此部分将指导你为 ESP32 开发板刷写 MicroPython 固件并上传项目代码。

#### 步骤 1: 安装必要工具

在你的本地计算机上打开终端，安装 `esptool` 和 `mpfshell`。

```bash
pip install esptool
pip install mpfshell
```

#### 步骤 2: 安装 USB 驱动并检查端口

1.  **安装驱动**: 从 [Silicon Labs官网](https://www.silabs.com/developers/usb-to-uart-bridge-vcp-drivers) 下载并安装对应的 USB to UART 驱动。
2.  **连接 ESP32**: 将 ESP32 开发板连接到你的电脑。
3.  **查找端口号**: 在终端中运行以下命令找到你的设备端口号。
    -   **macOS**: `ls /dev/tty.*` (通常是 `/dev/tty.SLAB_USBtoUART` 或 `/dev/tty.usbserial-xxxxxxxx`)
    -   **Linux**: `ls /dev/ttyUSB*` (通常是 `/dev/ttyUSB0`)
    
    > 记下这个端口号，后续步骤会用到 (下文将以 `<YOUR_PORT_NAME>` 代替)。

#### 步骤 3: 刷写 MicroPython 固件

1.  **下载固件**: 从 [MicroPython官网](https://micropython.org/download/ESP32_GENERIC/) 下载最新的稳定版 `.bin` 固件。
2.  **执行刷写**: 在终端中，进入固件文件所在的目录(e.g., `ls /dev/tty.*`)，然后依次执行以下命令。
    ```bash
    # 擦除 ESP32 上的现有固件
    esptool erase_flash
    ```
    ```bash
    # 刷写新固件 (将文件名替换为你下载的版本)
    esptool --baud 460800 write-flash 0x1000 ESP32_GENERIC-20250809-v1.26.0.bin
    ```

#### 步骤 4: 上传项目代码

进入本项目的 `esp32/` 目录，使用 `mpfshell` 将所有 `.py` 文件上传到 ESP32。

```bash
# 示例命令 (请去掉端口名前的 /dev/)
# 例如, 如果端口是 /dev/tty.usbserial-1234, 则使用 tty.usbserial-1234
# mpfshell -nc "open <YOUR_PORT_NAME_WITHOUT_/dev/>; cd esp32; mput .*\.py; repl"
```

```bash
cd esp32
mpfshell -nc "open tty.usbserial-59690942381; mput main.py"
```

#### 步骤 5: 查看 ESP32 输出 (调试)

你可以使用 `tio` 命令来查看 ESP32 的 `print` 输出。

```bash
# 连接到 ESP32 (115200是波特率)
tio /dev/tty.usbserial-59690942381
# 按下 ESP32 上的 "RST" 或 "EN" 按钮重启，即可看到输出
# 如何退出 tio: 按下 Ctrl + T 然后再按 Q 即可退出。
```

---

### **Part 2: GCP Backend Service Setup**

本节说明如何在 GCP Ubuntu 服务器上部署和运行 VitalGuard 的 Flask 后端服务。分为两种使用方式：

- **本地开发 / 调试模式**：手动运行 Python 进程，便于调试
- **生产 / 持久化部署模式**：通过 `systemd + gunicorn` 实现 24/7 持久运行

> 说明：以下命令默认在 GCP 实例上，以用户 `hc3625` 登录。如果你使用的是其他用户名，请将路径中的 `hc3625` 替换为你的用户名。

---

#### Phase A: Local Development & Testing

用于本地调试、快速验证 API、查看错误栈等。

1. **SSH 登录到 GCP 实例**

   ```bash
   # 示例（以 gcloud 为例）可以使用网页Console工具登录
   gcloud compute ssh instance-2 --zone=<your-zone>
   ```

2. **进入项目后端目录**

   ```bash
   cd /home/hc3625/github_repo/EECS-E4764-2025-Fall-Final-Project-vitalguard-ai/gcp-server
   ```

3. **激活虚拟环境**

   我们统一使用已创建好的虚拟环境：`/home/hc3625/esp32_env`

   ```bash
   source /home/hc3625/esp32_env/bin/activate
   ```

4. **安装依赖（首次或依赖有更新时执行）**
    
    `EECS-E4764-2025-Fall-Final-Project-vitalguard-ai/gcp-server/requirements.txt` 中列出了所有依赖包。
   ```bash
   pip install -r requirements.txt
   ```

5. **本地运行后端服务器（开发模式）**

   推荐两种等价方式（二选一）：

   - 方式 A：直接运行主程序入口
     ```bash
     python main.py
     ```
     或（如果在 `vital_guard_server.py` 中也写了 `if __name__ == "__main__":`）
     ```bash
     python vital_guard_server.py
     ```

   - 方式 B：如果你只想跑 Flask 内置服务器（仅调试用）
     ```bash
     export FLASK_APP=vital_guard_server:app
     flask run --host=0.0.0.0 --port=9999
     ```

6. **验证服务是否正常运行**

   在服务器上或本地通过端口转发，访问健康检查接口：

   ```bash
   curl http://localhost:9999/health
   ```

   预期返回类似 JSON：

   ```json
   {
     "status": "healthy",
     "timestamp": "2025-11-27T06:20:00.123456",
     "service": "VitalGuard AI"
   }
   ```

---

#### Phase B: Persistent Deployment on GCP with systemd + gunicorn

这一部分是“真正用于上线跑 ESP32 数据”的生产部署方式。特点：

- 服务器开机自动启动
- 进程崩溃自动重启
- 支持多 worker 并发处理请求
- 日志可通过 `journalctl` 和独立 log 文件查看

> 仅需在 **GCP 实例上执行一次完整配置**，之后只需用 `systemctl` 管理服务即可。

---

##### B1. 确认目录和虚拟环境

1. **后端项目目录**

   ```bash
   /home/hc3625/github_repo/EECS-E4764-2025-Fall-Final-Project-vitalguard-ai/gcp-server
   ```

2. **虚拟环境**

   ```bash
   /home/hc3625/esp32_env
   ```

   激活方法：

   ```bash
   source /home/hc3625/esp32_env/bin/activate
   ```

3. **安装 gunicorn（若尚未安装）**

   ```bash
   source /home/hc3625/esp32_env/bin/activate
   pip install gunicorn
   ```

4. **创建日志目录（若尚未创建）**

   ```bash
   mkdir -p /home/hc3625/github_repo/EECS-E4764-2025-Fall-Final-Project-vitalguard-ai/gcp-server/logs
   ```

---

##### B2. 创建 systemd 服务文件

我们使用一个专门的服务单元：`vitalguard-api.service`，用于运行后端 API 服务器。

1. **创建 / 编辑服务文件**

   ```bash
   sudo nano /etc/systemd/system/vitalguard-api.service
   ```

2. **目前使用以下配置**

   ```ini
   [Unit]
   Description=VitalGuard AI Health Monitoring API Service
   After=network-online.target
   Wants=network-online.target

   [Service]
   Type=simple

   # 运行该服务的用户与用户组（当前为 hc3625）
   User=hc3625
   Group=hc3625

   # 后端代码所在目录
   WorkingDirectory=/home/hc3625/github_repo/EECS-E4764-2025-Fall-Final-Project-vitalguard-ai/gcp-server

   # 基本环境变量
   Environment="PATH=/home/hc3625/esp32_env/bin:/usr/local/bin:/usr/bin:/bin"
   Environment="PYTHONUNBUFFERED=1"

   # 使用 Gunicorn 启动 Flask 应用
   # vital_guard_server:app  =>  模块名:Flask应用对象名
   ExecStart=/home/hc3625/esp32_env/bin/gunicorn \
       --bind 0.0.0.0:9999 \
       --workers 4 \
       --threads 2 \
       --timeout 120 \
       --worker-class sync \
       --access-logfile /home/hc3625/github_repo/EECS-E4764-2025-Fall-Final-Project-vitalguard-ai/gcp-server/logs/access.log \
       --error-logfile /home/hc3625/github_repo/EECS-E4764-2025-Fall-Final-Project-vitalguard-ai/gcp-server/logs/error.log \
       --log-level info \
       vital_guard_server:app

   # 自动重启策略
   Restart=always
   RestartSec=10
   StartLimitInterval=200
   StartLimitBurst=5

   # 安全相关（可选）
   NoNewPrivileges=true
   PrivateTmp=true

   # 系统资源限制（根据需要调整）
   LimitNOFILE=65535
   LimitNPROC=4096

   # 日志输出到 systemd journal
   StandardOutput=journal
   StandardError=journal
   SyslogIdentifier=vitalguard-api

   [Install]
   WantedBy=multi-user.target
   ```

> 如果你在其他机器或其他用户名下部署：
> - 把 `User=hc3625` 和 `Group=hc3625` 改成你自己的用户名和组名
> - 把所有 `/home/hc3625/...` 路径中的 `hc3625` 替换为你的用户名

---

##### B3. 让 systemd 识别并启动服务

1. **重新加载 systemd 配置**

   ```bash
   sudo systemctl daemon-reload
   ```

2. **启动服务**

   ```bash
   sudo systemctl start vitalguard-api.service
   ```

3. **设置开机自启**

   ```bash
   sudo systemctl enable vitalguard-api.service
   ```

4. **检查服务状态**

   ```bash
   sudo systemctl status vitalguard-api.service
   ```

   正常情况下，你会看到类似输出：

   ```text
   ● vitalguard-api.service - VitalGuard AI Health Monitoring API Service
        Loaded: loaded (/etc/systemd/system/vitalguard-api.service; enabled)
        Active: active (running) since ...
      Main PID: 12345 (gunicorn)
        Tasks: 5 (limit: ...)
       Memory: ...
       CGroup: /system.slice/vitalguard-api.service
               ├─12345 /home/hc3625/esp32_env/bin/python3 /home/hc3625/esp32_env/bin/gunicorn ...
               ├─12346 gunicorn: worker [vital_guard_server:app]
               └─...
   ```

---

##### B4. 验证后端 API 是否正常对外服务

1. **在 GCP 实例上测试**

   ```bash
   curl http://localhost:9999/health
   ```

2. **在本地电脑上测试（将 `<SERVER_IP>` 换成你的 GCP 公网 IP）**

   ```bash
   curl http://<SERVER_IP>:9999/health
   ```

   预期返回 JSON：

   ```json
   {
     "status": "healthy",
     "timestamp": "...",
     "service": "VitalGuard AI"
   }
   ```

ESP32 端代码中，后端接收数据的地址应设置为：

```text
http://<SERVER_IP>:9999/api/vitals
```

---

##### B5. 日志查看与调试

你有两种查看日志的途径：`systemd journal` 和 Gunicorn 的独立日志文件。

1. **使用 `journalctl` 查看实时日志**

   ```bash
   # 实时查看（Ctrl + C 退出）
   sudo journalctl -u vitalguard-api.service -f

   # 查看最近 100 行日志
   sudo journalctl -u vitalguard-api.service -n 100
   ```

2. **查看 Gunicorn 独立日志文件**

   ```bash
   cd /home/hc3625/github_repo/EECS-E4764-2025-Fall-Final-Project-vitalguard-ai/gcp-server

   # 访问日志（每次请求一行）
   tail -f logs/access.log

   # 错误日志（异常、traceback 等）
   tail -f logs/error.log
   ```

---

##### B6. 常用运维命令速查表

```bash
# 进入后端项目目录
cd /home/hc3625/github_repo/EECS-E4764-2025-Fall-Final-Project-vitalguard-ai/gcp-server

# 激活虚拟环境（调试时手动跑用得到）
source /home/hc3625/esp32_env/bin/activate

# ========== systemd 服务管理 ==========
# 启动服务
sudo systemctl start vitalguard-api.service

# 停止服务
sudo systemctl stop vitalguard-api.service

# 重启服务（修改代码后一般用这个）
sudo systemctl restart vitalguard-api.service

# 查看服务状态
sudo systemctl status vitalguard-api.service

# 设置开机自启（只需执行一次）
sudo systemctl enable vitalguard-api.service

# ========== 日志 ==========
# 实时查看 systemd 日志
sudo journalctl -u vitalguard-api.service -f

# 查看最近 100 行日志
sudo journalctl -u vitalguard-api.service -n 100

# 查看 Gunicorn 访问日志
tail -f logs/access.log

# 查看 Gunicorn 错误日志
tail -f logs/error.log

# ========== 本地手动调试运行（非 systemd 模式） ==========
# 手动运行 Flask 后端（开发模式）
python main.py

# 或者直接用 gunicorn 手动试跑
gunicorn --bind 0.0.0.0:9999 vital_guard_server:app
```

## 📈 开发流程 (Team Workflow)

为了保证代码质量和 `main` 分支的稳定性，请所有团队成员遵循以下开发流程：

1.  **同步最新代码**: 在开始新任务前，务必先从远程拉取最新的 `develop` 分支。
    ```bash
    git checkout develop
    git pull origin develop
    ```
2.  **创建特性分支**: 从 `develop` 分支创建一个新的特性分支，命名要清晰，例如 `feature/add-temperature-sensor`。
    ```bash
    git checkout -b feature/your-feature-name
    ```
3.  **开发与提交**: 在你的特性分支上进行开发，并进行有意义的、小步的提交。
4.  **发起合并请求 (Pull Request)**: 功能完成后，将你的分支推送到远程，并在 GitHub 上创建一个 Pull Request，请求将你的分支合并到 `develop` 分支。
5.  **代码审查 (Code Review)**: 至少需要一位其他团队成员审查代码，确认无误后方可合并。
6.  **合并到主干**: 当 `develop` 分支经过测试，准备进行版本发布或部署时，才可将其合并到 `main` 分支。

## 👥 团队成员 (Team)

-   **Group 19**
    -   Daolin Li (Uni: dl3832) [dl3832@columbia.edu](mailto:dl3832@columbia.edu)
    -   Hao CHEN (Uni: hc3625) [hc3625@columbia.edu](mailto:hc3625@columbia.edu)
    -   Sripad Karne (Uni: sk5695) [sk5695@columbia.edu](mailto:sk5695@columbia.edu)
    -   Yizheng TANG (Uni: yt2992) [yt2992@columbia.edu](mailto:yt2992@columbia.edu)
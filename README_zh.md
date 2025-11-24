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
├── esp32/          # ESP32 (MicroPython) 代码
├── gcp-server/     # GCP Flask 后端服务代码
├── docs/           # 项目文档
├── .gitignore      # Git 忽略文件配置
└── README.md       # 项目说明
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
2.  **执行刷写**: 在终端中，进入固件文件所在的目录，然后依次执行以下命令。
    ```bash
    # 擦除 ESP32 上的现有固件
    esptool.py --port <YOUR_PORT_NAME> erase_flash
    
    # 刷写新固件 (将文件名替换为你下载的版本)
    esptool.py --port <YOUR_PORT_NAME> --baud 460800 write_flash -z 0x1000 ESP32_GENERIC-v1.2x.x.bin
    ```

#### 步骤 4: 上传项目代码

进入本项目的 `esp32/` 目录，使用 `mpfshell` 将所有 `.py` 文件上传到 ESP32。

```bash
# 示例命令 (请去掉端口名前的 /dev/)
# 例如, 如果端口是 /dev/tty.usbserial-1234, 则使用 tty.usbserial-1234
mpfshell -nc "open <YOUR_PORT_NAME_WITHOUT_/dev/>; cd esp32; mput .*\.py; repl"
```

#### 步骤 5: 查看 ESP32 输出 (调试)

你可以使用 `screen` 命令来查看 ESP32 的 `print` 输出。

```bash
# 连接到 ESP32 (115200是波特率)
screen /dev/<YOUR_PORT_NAME> 115200

# 按下 ESP32 上的 "RST" 或 "EN" 按钮重启，即可看到输出
# 如何退出 screen: 按下 Ctrl + A, 然后按 k, 再按 y
```

---

### **第二部分: GCP 后端服务设置**

此部分指导如何在 GCP 的 Ubuntu 服务器上部署 Flask 应用。

#### 阶段 A: 本地开发与测试

在部署到云端前，建议先在本地运行测试。

1.  **进入项目目录**: `cd gcp-server/`
2.  **创建并激活虚拟环境**:
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```
3.  **安装依赖**: `pip install -r requirements.txt`
4.  **运行本地服务器**: `flask run`

#### 阶段 B: 在 GCP 上使用 Systemd 进行持久化部署

为了让我们的服务能在服务器上 24/7 稳定运行，并且在服务器重启后能自动启动，我们使用 `systemd`。

1.  **创建 `systemd` 服务文件**:
    通过 SSH 连接到你的 GCP 服务器，然后执行以下命令创建一个服务配置文件。
    ```bash
    sudo nano /etc/systemd/system/vitalguard.service
    ```
2.  **粘贴配置内容**:
    将以下内容粘贴到文件中。**请务必修改 `User` 和路径相关的字段**，使其与你的服务器配置匹配。
    ```ini
    [Unit]
    Description=VitalGuard AI Flask Server
    After=network.target
    
    [Service]
    User=<your_username>  # 例如: hc3625
    Group=<your_username> # 例如: hc3625
    WorkingDirectory=<path_to_project>/gcp-server  # 例如: /home/hc3625/vitalguard-ai/gcp-server
    
    # 指定虚拟环境的路径
    Environment="PATH=<path_to_project>/gcp-server/venv/bin" 
    
    # 启动命令
    ExecStart=<path_to_project>/gcp-server/venv/bin/gunicorn --workers 3 --bind unix:app.sock -m 007 wsgi:app
    
    # 异常重启策略
    Restart=always
    RestartSec=3
    
    [Install]
    WantedBy=multi-user.target
    ```
    > **注意**: 为提高性能和稳定性，生产环境推荐使用 `gunicorn`。请先在虚拟环境中 `pip install gunicorn`，并创建一个 `wsgi.py` 文件，内容为: `from main import app as application`。

3.  **管理服务**:
    现在，你可以使用 `systemctl` 命令来管理你的服务了。
    ```bash
    # 重新加载 systemd 配置，让新服务文件生效
    sudo systemctl daemon-reload
    
    # 启动你的服务
    sudo systemctl start vitalguard
    
    # 查看服务状态，检查是否有错误
    sudo systemctl status vitalguard
    
    # 将服务设置为开机自启动
    sudo systemctl enable vitalguard
    ```

4.  **查看日志**:
    如果服务运行出错或你想查看请求日志，请使用 `journalctl`。
    ```bash
    # 查看服务的实时日志
    sudo journalctl -u vitalguard -f
    
    # 查看最近的100行日志
    sudo journalctl -u vitalguard -n 100
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
<!-- Language Switcher -->

<div align="right">
  <b>English</b> | <a href="README_zh.md">中文</a>
</div>

# VitalGuard AI: An AIoT Wearable for Real-Time Health Insights & Alerts

**VitalGuard AI** is a compact wearable AIoT system that provides personalized health insights and triggers real-time emergency alerts by continuously fusing multi-sensor vital signs (e.g., heart rate, temperature, activity).

## 🚀 About The Project

In the fields of chronic disease management and elderly care, continuous and low-cost monitoring outside of clinical settings is crucial. This project leverages AIoT technology to provide users with an effective way to track health trends, receive actionable lifestyle suggestions (such as hydration and rest reminders), and automatically trigger alerts in case of falls or abnormal vitals. Our goal is to enable safer independent living and provide peace of mind for families and caregivers.

### Key Features

-   **Continuous Multi-Sensor Monitoring**: Integrates sensors for heart rate, SpO₂, temperature, activity, and stress to perform 24/7 data collection.
-   **Real-Time Data Analytics**: Data is pre-processed on the edge by an ESP32 and uploaded to a cloud server (GCP) in real time.
-   **AI-Driven Health Reports**: Utilizes a Large Language Model (LLM) to analyze processed data and generate easy-to-understand health reports and personalized advice.
-   **Emergency Alert System**: Automatically sends notifications to emergency contacts when a fall or critical vital sign anomaly is detected.
-   **Web Visualization Dashboard**: A clean web UI for users to easily view their health data, trends, and AI-generated reports.

## 🛠️ Tech Stack

| Category         | Technologies                                                            |
| :--------------- | :---------------------------------------------------------------------- |
| **Hardware**     | `ESP32`, `MAX86150` (HR/SpO₂), `TMP117` (Temp), `ADXL345` (Motion/Fall) |
| **Embedded**     | `MicroPython`                                                           |
| **Cloud Platform** | `Google Cloud Platform (GCP)`                                           |
| **Backend**      | `Python`, `Flask`                                                       |
| **Deployment**   | `Systemd`, `Gunicorn`                                                   |
| **AI Model**     | Third-party LLM via API                                                 |
| **Frontend**     | `HTML`, `CSS`, `JavaScript`                                             |

## 📂 Project Structure

```
.
├── esp32/          # ESP32 (MicroPython) code
├── gcp-server/     # GCP Flask backend service code
├── docs/           # Project documentation
├── .gitignore      # Git ignore configuration
└── README.md       # Project overview
```

## 🏁 Getting Started

This guide will walk you through the entire setup process, from hardware configuration to cloud service deployment.

### Prerequisites

-   **General**: `Git`
-   **Hardware-Side**: Python 3.x, `pip`, `esptool`, `mpfshell`
-   **Server-Side**: A GCP account with a configured Ubuntu server, Python 3.x, `pip`, `venv`

---

### **Part 1: ESP32 Hardware Setup**

This section guides you through flashing the MicroPython firmware onto your ESP32 board and uploading the project code.

#### Step 1: Install Required Tools

Open a terminal on your local machine and install `esptool` and `mpfshell`.

```bash
pip install esptool
pip install mpfshell
```

#### Step 2: Install USB Driver and Check Port

1.  **Install Driver**: Download and install the appropriate USB to UART driver from the [Silicon Labs website](https://www.silabs.com/developers/usb-to-uart-bridge-vcp-drivers).
2.  **Connect ESP32**: Plug the ESP32 board into your computer.
3.  **Find Port Name**: Run the following command in your terminal to find the device port name.
    -   **macOS**: `ls /dev/tty.*` (e.g., `/dev/tty.SLAB_USBtoUART` or `/dev/tty.usbserial-xxxxxxxx`)
    -   **Linux**: `ls /dev/ttyUSB*` (e.g., `/dev/ttyUSB0`)
    > Take note of this port name; it will be referred to as `<YOUR_PORT_NAME>` in the following steps.

#### Step 3: Flash MicroPython Firmware

1.  **Download Firmware**: Download the latest stable `.bin` firmware from the [MicroPython website](https://micropython.org/download/ESP32_GENERIC/).
2.  **Flash Firmware**: In your terminal, navigate to the directory where you saved the firmware file and run the commands below.
    ```bash
    # Erase the existing flash on the ESP32
    esptool.py --port <YOUR_PORT_NAME> erase_flash
    
    # Flash the new firmware (replace the filename with the version you downloaded)
    esptool.py --port <YOUR_PORT_NAME> --baud 460800 write_flash -z 0x1000 ESP32_GENERIC-v1.2x.x.bin
    ```

#### Step 4: Upload Project Code

Navigate to the `esp32/` directory of this project and use `mpfshell` to upload all `.py` files to the ESP32.

```bash
# Example command (remove the "/dev/" prefix from the port name)
# e.g., if your port is /dev/tty.usbserial-1234, use tty.usbserial-1234
mpfshell -nc "open <PORT_NAME_WITHOUT_/dev/>; cd esp32; mput .*\.py; repl"
```

#### Step 5: View ESP32 Output (Debugging)

You can use the `screen` command to view `print` statements from the ESP32.

```bash
# Connect to the ESP32 serial port (115200 is the baud rate)
screen /dev/<YOUR_PORT_NAME> 115200

# Press the "RST" or "EN" button on the ESP32 to see the output.
# To exit screen: Press Ctrl + A, then k, then y.
```

---

### **Part 2: GCP Backend Service Setup**

This section explains how to deploy and run the VitalGuard Flask backend on a GCP Ubuntu server. There are two ways to use it:

- **Local development / debug mode**: run the Python process manually for debugging
- **Production / persistent deployment mode**: use `systemd + gunicorn` to keep it running 24/7

> Note: All commands assume you are logged into the GCP instance as user `hc3625`.
> If you use a different username, replace `hc3625` in all paths with your own username.

---

#### Phase A: Local Development & Testing

Use this mode for local debugging, quick API verification, and viewing error stack traces.

1. **SSH into the GCP instance**

   ```bash
   # Example (using gcloud), could use web console to SSH in.
   gcloud compute ssh instance-2 --zone=<your-zone>
   ```

2. **Go to the backend project directory**

   ```bash
   cd EECS-E4764-2025-Fall-Final-Project-vitalguard-ai/gcp-server
   ```

3. **Activate the virtual environment**

   We use a shared virtual environment: `/.../esp32_env`

   ```bash
   # this path may vary based on your setup
   source /.../esp32_env/bin/activate
   ```

4. **Install dependencies** (run the first time or when dependencies change)

   ```bash
   # file locates in `gcp-server/requirements.txt`
   pip install -r requirements.txt
   ```

5. **Run the backend server locally (development mode)**

   There are two equivalent options (choose one):

   - Option A: run the main entry script directly
     ```bash
     python main.py
     ```
     Or (if you also added `if __name__ == "__main__":` in `vital_guard_server.py`)
     ```bash
     python vital_guard_server.py
     ```

   - Option B: run the built-in Flask development server only (for debugging)
     ```bash
     export FLASK_APP=vital_guard_server:app
     flask run --host=0.0.0.0 --port=9999
     ```

6. **Verify that the service is running correctly**

   On the server (or locally via port forwarding), call the health check endpoint:

   ```bash
   curl http://localhost:9999/health
   ```

   Expected JSON response:

   ```json
   {
     "status": "healthy",
     "timestamp": "2025-11-27T06:20:00.123456",
     "service": "VitalGuard AI"
   }
   ```

---

#### Phase B: Persistent Deployment on GCP with systemd + gunicorn

This part describes the production deployment used for real ESP32 data. Key characteristics:

- Starts automatically when the server boots
- Automatically restarts if the process crashes
- Supports multiple workers to handle concurrent requests
- Logs are available via `journalctl` and separate log files

> You only need to perform the full setup **once** on the GCP instance.
> After that, you manage the service with `systemctl`.

---

##### B1. Confirm directories and virtual environment

1. **Backend project directory**

   ```bash
   /.../github_repo/EECS-E4764-2025-Fall-Final-Project-vitalguard-ai/gcp-server
   ```

2. **Virtual environment**

   ```bash
   /.../esp32_env
   ```

   To activate:

   ```bash
   source /.../esp32_env/bin/activate
   ```

3. **Install gunicorn (if not already installed)**

   ```bash
   # Activate the virtual environment (may vary based on your setup)
   source /.../esp32_env/bin/activate
   pip install gunicorn
   ```

4. **Create the logs directory (if it does not exist)**

   ```bash
   mkdir -p EECS-E4764-2025-Fall-Final-Project-vitalguard-ai/gcp-server/logs
   ```

---

##### B2. Create the systemd service file

We use a dedicated service unit, `vitalguard-api.service`, to run the backend API server.

1. **Access the service file**

   ```bash
   sudo nano /etc/systemd/system/vitalguard-api.service
   ```

2. **Current configuration**

   ```ini
   [Unit]
   Description=VitalGuard AI Health Monitoring API Service
   After=network-online.target
   Wants=network-online.target

   [Service]
   Type=simple

   # User and group that run this service (currently hc3625)
   User=hc3625
   Group=hc3625

   # Backend code directory
   WorkingDirectory=/.../github_repo/EECS-E4764-2025-Fall-Final-Project-vitalguard-ai/gcp-server

   # Basic environment variables
   Environment="PATH=/.../esp32_env/bin:/usr/local/bin:/usr/bin:/bin"
   Environment="PYTHONUNBUFFERED=1"

   # Start the Flask app with Gunicorn
   # vital_guard_server:app  =>  module_name:flask_app_object_name
   ExecStart=/.../esp32_env/bin/gunicorn \
       --bind 0.0.0.0:9999 \
       --workers 4 \
       --threads 2 \
       --timeout 120 \
       --worker-class sync \
       --access-logfile /.../github_repo/EECS-E4764-2025-Fall-Final-Project-vitalguard-ai/gcp-server/logs/access.log \
       --error-logfile /.../github_repo/EECS-E4764-2025-Fall-Final-Project-vitalguard-ai/gcp-server/logs/error.log \
       --log-level info \
       vital_guard_server:app

   # Automatic restart policy
   Restart=always
   RestartSec=10
   StartLimitInterval=200
   StartLimitBurst=5

   # Security-related options (optional)
   NoNewPrivileges=true
   PrivateTmp=true

   # System resource limits (adjust if needed)
   LimitNOFILE=65535
   LimitNPROC=4096

   # Log output to the systemd journal
   StandardOutput=journal
   StandardError=journal
   SyslogIdentifier=vitalguard-api

   [Install]
   WantedBy=multi-user.target
   ```

> If you deploy on another machine or under a different username:
> - Change `User=hc3625` and `Group=hc3625` to your own user and group
> - Replace `hc3625` in all `/.../...` paths with your own username

---

##### B3. Make systemd load and start the service

1. **Reload systemd configuration**

   ```bash
   sudo systemctl daemon-reload
   ```

2. **Start the service**

   ```bash
   sudo systemctl start vitalguard-api.service
   ```

3. **Enable auto-start on boot**

   ```bash
   sudo systemctl enable vitalguard-api.service
   ```

4. **Check service status**

   ```bash
   sudo systemctl status vitalguard-api.service
   ```

   If everything is working, you should see output similar to:

   ```text
   ● vitalguard-api.service - VitalGuard AI Health Monitoring API Service
        Loaded: loaded (/etc/systemd/system/vitalguard-api.service; enabled)
        Active: active (running) since ...
      Main PID: 12345 (gunicorn)
        Tasks: 5 (limit: ...)
       Memory: ...
       CGroup: /system.slice/vitalguard-api.service
               ├─12345 /.../esp32_env/bin/python3 /.../esp32_env/bin/gunicorn ...
               ├─12346 gunicorn: worker [vital_guard_server:app]
               └─...
   ```

---

##### B4. Verify that the backend API is accessible

1. **Test on the GCP instance**

   ```bash
   curl http://localhost:9999/health
   ```

2. **Test from your local machine** (replace `<SERVER_IP>` with your GCP public IP)

   ```bash
   curl http://<SERVER_IP>:9999/health
   # e.g, curl http://136.113.226.196:9999/health this for our project server (instance-2)
   ```

   Expected JSON response:

   ```json
   {
     "status": "healthy",
     "timestamp": "...",
     "service": "VitalGuard AI"
   }
   ```

In the ESP32 code, set the backend data endpoint to:

```text
http://<SERVER_IP>:9999/api/vitals
```

---

##### B5. Log viewing and debugging

There are two ways to view logs: via the `systemd` journal and via Gunicorn log files.

1. **Use `journalctl` to view logs**

   ```bash
   # Live logs (Ctrl + C to exit)
   sudo journalctl -u vitalguard-api.service -f

   # View the last 100 log lines
   sudo journalctl -u vitalguard-api.service -n 100
   ```

2. **View Gunicorn log files**

   ```bash
   cd /.../EECS-E4764-2025-Fall-Final-Project-vitalguard-ai/gcp-server

   # Access log (one line per request)
   tail -f logs/access.log

   # Error log (exceptions, tracebacks, etc.)
   tail -f logs/error.log
   ```

---

##### B6. Common operations cheat sheet

```bash
# Go to the backend project directory
cd /.../EECS-E4764-2025-Fall-Final-Project-vitalguard-ai/gcp-server

# Activate the virtual environment (used when running things manually)
source /.../esp32_env/bin/activate

# ========== systemd service management ==========
# Start the service
sudo systemctl start vitalguard-api.service

# Stop the service
sudo systemctl stop vitalguard-api.service

# Restart the service (use this after code changes)
sudo systemctl restart vitalguard-api.service

# Check service status
sudo systemctl status vitalguard-api.service

# Enable auto-start on boot (only needs to be done once)
sudo systemctl enable vitalguard-api.service

# ========== Logs ==========
# View live systemd logs
sudo journalctl -u vitalguard-api.service -f

# View the last 100 log lines
sudo journalctl -u vitalguard-api.service -n 100

# View Gunicorn access log
tail -f logs/access.log

# View Gunicorn error log
tail -f logs/error.log

# ========== Local manual run (non-systemd mode) ==========
# Run the Flask backend manually (development mode)
python main.py

# Or test-run it manually with gunicorn
gunicorn --bind 0.0.0.0:9999 vital_guard_server:app
```

---
## 📈 Development Workflow

To ensure code quality and the stability of the `main` branch, all team members must follow this workflow:

1.  **Sync Latest Code**: Before starting a new task, always pull the latest changes from the remote `develop` branch.
    ```bash
    git checkout develop
    git pull origin develop
    ```
2.  **Create a Feature Branch**: Create a new branch from `develop` with a descriptive name, e.g., `feature/add-temperature-sensor`.
    ```bash
    git checkout -b feature/your-feature-name
    ```
3.  **Develop and Commit**: Make your changes on the feature branch, using small, meaningful commits.
4.  **Open a Pull Request**: Once your feature is complete, push your branch to the remote and open a Pull Request on GitHub to merge it into `develop`.
5.  **Code Review**: At least one other team member must review the code before it can be merged.
6.  **Merge to Main**: Only when the `develop` branch is fully tested and ready for a release should it be merged into the `main` branch.

## 👥 Team Members

-   **Group 19**
    -   Daolin Li (Uni: dl3832) [dl3832@columbia.edu](mailto:dl3832@columbia.edu)
    -   Hao CHEN (Uni: hc3625) [hc3625@columbia.edu](mailto:hc3625@columbia.edu)
    -   Sripad Karne (Uni: sk5695) [sk5695@columbia.edu](mailto:sk5695@columbia.edu)
    -   Yizheng TANG (Uni: yt2992) [yt2992@columbia.edu](mailto:yt2992@columbia.edu)
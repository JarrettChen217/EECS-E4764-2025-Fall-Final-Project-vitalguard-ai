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

This section covers deploying the Flask application on a GCP Ubuntu server.

#### Phase A: Local Development & Testing

Before deploying to the cloud, it's recommended to run the server locally.

1.  **Navigate to the directory**: `cd gcp-server/`
2.  **Create and activate a virtual environment**:
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```
3.  **Install dependencies**: `pip install -r requirements.txt`
4.  **Run the local server**: `flask run`

#### Phase B: Persistent Deployment on GCP with Systemd

We use `systemd` to ensure our service runs 24/7 and starts automatically on boot.

1.  **Create a `systemd` Service File**:
    SSH into your GCP server and run the following command to create a service configuration file.
    ```bash
    sudo nano /etc/systemd/system/vitalguard.service
    ```
2.  **Paste the Configuration**:
    Paste the following content into the file. **Be sure to modify the `User` and path fields** to match your server's configuration.
    ```ini
    [Unit]
    Description=VitalGuard AI Flask Server
    After=network.target
    
    [Service]
    User=<your_username>  # e.g., hc3625
    Group=<your_username> # e.g., hc3625
    WorkingDirectory=<path_to_project>/gcp-server  # e.g., /home/hc3625/vitalguard-ai/gcp-server
    
    # Specify the path to the virtual environment
    Environment="PATH=<path_to_project>/gcp-server/venv/bin" 
    
    # Command to start the app using Gunicorn
    ExecStart=<path_to_project>/gcp-server/venv/bin/gunicorn --workers 3 --bind 0.0.0.0:5000 wsgi:app
    
    # Restart policy
    Restart=always
    RestartSec=3
    
    [Install]
    WantedBy=multi-user.target
    ```
    > **Note**: For production, `gunicorn` is recommended for better performance and stability. Install it via `pip install gunicorn` in your virtual environment and create a `wsgi.py` file with the content: `from main import app as application`.

3.  **Manage the Service**:
    You can now manage your service using `systemctl`.
    ```bash
    # Reload the systemd daemon to recognize the new service
    sudo systemctl daemon-reload
    
    # Start your service
    sudo systemctl start vitalguard
    
    # Check the service status for any errors
    sudo systemctl status vitalguard
    
    # Enable the service to start on boot
    sudo systemctl enable vitalguard
    ```

4.  **Viewing Logs**:
    Use `journalctl` to view logs if the service fails or to monitor requests.
    ```bash
    # View real-time logs for the service
    sudo journalctl -u vitalguard -f
    
    # View the last 100 log entries
    sudo journalctl -u vitalguard -n 100
    ```

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
# NI-Sensor-data-logger-and-Interpretor
This repository is a professional-grade solution for logging data from sensors like Thermocouples, Accelerometers, Acoustic Pressure Sensors, and Laser Sensors. It features a robust Python-based DAQ engine integrated with a real-time Web Dashboard.

# 🌡️ NI Thermocouple Logger & Web Dashboard (v2.7)

![Status](https://img.shields.io/badge/Status-Production%20Ready-success)
![Version](https://img.shields.io/badge/Version-2.7-orange)
![Python](https://img.shields.io/badge/Python-3.x-blue)

A "Self-Healing" data acquisition system for National Instruments (NI) hardware. Optimized for the **NI 9213** module, this system logs data to local CSVs and Google Sheets while providing a secure, interactive web interface.

---

## 🚀 NEW in Version 2.7: Standalone Distribution
We now provide a **Standalone Station** for seamless deployment in labs without requiring manual environment management.

### **📦 NI_Sensor_Station**
The `NI_Sensor_Station` folder is a self-contained package designed for lab technicians:
1.  **`SETUP_PREREQUISITES.bat`**: One-click setup. Creates a virtual environment and installs all dependencies.
2.  **`START_SYSTEM.bat`**: One-click launcher. Activates the environment and starts the dashboard.
3.  **Organized Storage**:
    *   `config/`: Managed settings (`config.json`) and credentials.
    *   `data/`: Automated CSV logging directory.
    *   `logs/`: Application performance and error logs.

---

## ✨ Key Features

*   **v2.7 Precision:** Now supports **3-decimal precision** for high-accuracy industrial logging.
*   **Dynamic UI:**
    *   **Custom Sensor Tagging:** Name your channels (e.g., "Oven-1", "Ambient") directly from the UI.
    *   **Dynamic Gauge Ranges:** Set custom Min/Max ranges for each gauge in the Settings panel.
    *   **Real-time Trends:** Interactive Chart.js plots showing the last 100 samples.
*   **Industrial Resilience:**
    *   **CSV Buffer Protection:** Continues logging even if the CSV file is locked (e.g., open in Excel).
    *   **Cloud Throttling:** Smart reconnection to Google Sheets to prevent network flooding during outages.
*   **On-Demand DAQ:** Start and Stop data acquisition directly from the Web Dashboard.

---

## 🛠️ Hardware Requirements

*   **Chassis:** NI cDAQ-9174, cDAQ-9178, or similar.
*   **Module:** [NI 9213](https://www.ni.com/en-us/support/model.ni-9213.html) (16-Channel Thermocouple Input).
*   **Sensors:** Thermocouples (Types K, J, T, E supported).

---

## ⚙️ Installation & Usage

### **Option 1: Lab Technician (Standalone)**
1.  Download the `NI_Sensor_Station` folder.
2.  Run `SETUP_PREREQUISITES.bat` once.
3.  Run `START_SYSTEM.bat` to launch the dashboard at `http://localhost:5000`.

### **Option 2: Developer (Manual)**
1.  Install [NI-DAQmx Drivers](https://www.ni.com/en-us/support/downloads/drivers/download.ni-daqmx.html).
2.  Clone the repository:
    ```bash
    git clone https://github.com/Ajiket/NI-Sensor-data-logger-and-Interpretor.git
    cd NI-Sensor-data-logger-and-Interpretor
    ```
3.  Install dependencies: `pip install nidaqmx flask gspread google-auth`
4.  Run: `python production_logger.py`

---

## 📂 Project Structure
```text
📦 NI-Sensor-data-logger-and-Interpretor
 ┣ 📂 NI_Sensor_Station       # Standalone distribution package
 ┃ ┣ 📂 config                # Settings and Credentials
 ┃ ┣ 📂 data                  # Logged CSV files
 ┃ ┣ 📂 logs                  # App logs
 ┃ ┣ 📜 SETUP_PREREQUISITES.bat
 ┃ ┗ 📜 START_SYSTEM.bat
 ┣ 📂 Specs                   # Architectural & UX Specifications
 ┣ 📜 production_logger.py    # Main Application Source
 ┣ 📜 sync_session.bat        # Automated GitHub Sync Tool
 ┗ 📜 README.md               # This documentation
```

---

## 🔧 Troubleshooting
*   **"Device Not Found":** Ensure the `DEVICE_NAME` in Settings matches the name in **NI MAX** (e.g., `cDAQ1Mod1`).
*   **"Open" Status:** The system detects open circuits (broken wires). Check your sensor connections.
*   **Demo Mode:** If NI-DAQmx is not installed, the system will automatically run in Demo Mode for UI testing.

---

## 📜 License
This project is licensed under the MIT License.

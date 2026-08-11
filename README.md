# NI-Sensor-data-logger-and-Interpretor v2.8

This repository is a professional-grade solution for logging data from sensors like Thermocouples, Accelerometers, Acoustic Pressure Sensors, and Laser Sensors. It features a robust Python-based backend, a real-time web dashboard, and an **AI-driven Inference Engine powered by Google Gemini**.

![Status](https://img.shields.io/badge/Status-Production%20Ready-success)
![Version](https://img.shields.io/badge/Version-2.8-orange)
![Python](https://img.shields.io/badge/Python-3.x-blue)

---

## 🚀 NEW in Version 2.8: Gemini AI & Robust Deployment

### **🧠 Gemini AI Layer**
*   **Predictive Maintenance**: Gemini LLM analyzes trends to predict sensor failures or calibration drift.
*   **Safety Inferences**: Built-in statistical detection for **Thermal Runaway** (rate of change > 2°C/s) and **Sensor Drift**.
*   **Industrial Insights**: High-level AI interpretation of sensor data context.

### **📦 NI_Sensor_Station (Standalone Distribution)**
The `NI_Sensor_Station` folder is a self-contained package designed for lab technicians:
1.  **`SETUP_PREREQUISITES.bat`**: One-click setup. Now uses robust path-independent installation.
2.  **`START_SYSTEM.bat`**: One-click launcher with automatic hardware detection.
3.  **Demo Mode Fallback**: Automatically activates if NI-DAQmx hardware or drivers are missing, allowing UI and logic testing on any machine.

---

## ✨ Key Features

*   **Modular Architecture:** Clean separation between Core, DAQ, and Web layers.
*   **Real-Time Dashboard:** 
    *   **Custom Sensor Tagging:** Name your channels (e.g., "Oven-1") from the UI.
    *   **Dynamic Gauges:** Speedometer-style visualization with custom Min/Max ranges.
    *   **Trend Charts:** Real-time Chart.js plots showing historical data.
*   **Industrial Resilience:**
    *   **CSV Buffer Protection:** Continues logging even if the CSV file is locked (e.g., open in Excel).
    *   **Cloud Logging:** Secure, throttled streaming to Google Sheets.

---

## 🛠️ Prerequisites & Hardware

### **Software Requirements**
1.  **Python 3.9+**
2.  **NI-DAQmx Runtime:** (CRITICAL for hardware logging) [Download here](https://www.ni.com/en-in/support/downloads/drivers/download.ni-daqmx.html).
3.  **Google Gemini API Key:** (Optional) Set as `GEMINI_API_KEY` in your environment for AI insights.

### **Hardware Requirements**
*   **Chassis:** NI cDAQ-9174, cDAQ-9178, or similar.
*   **Module:** [NI 9213](https://www.ni.com/en-us/support/model.ni-9213.html) (16-Channel Thermocouple Input).
*   **Sensors:** Thermocouples (Types K, J, T, E supported).

---

## ⚙️ Installation & Usage

### **Option 1: Lab Technician (Standalone Station)**
1.  Download the `NI_Sensor_Station` folder.
2.  Run `SETUP_PREREQUISITES.bat` once.
3.  Run `START_SYSTEM.bat` to launch the dashboard at `http://localhost:5000`.

### **Option 2: Developer (Manual Setup)**
1.  Ensure **NI-DAQmx Drivers** are installed.
2.  Clone the repository and install dependencies:
    ```bash
    pip install -r requirements.txt
    ```
3.  Run: `python app.py`

---

## 🔧 Troubleshooting
*   **"Device Not Found":** Ensure the `DEVICE_NAME` in Settings matches the name in **NI MAX** (e.g., `cDAQ1Mod3`).
*   **"FileNotFoundError: Could not find module 'nicaiu'":** This means the **NI-DAQmx Driver** is missing. Download and install it from the link in the Prerequisites section.
*   **AI Insights Missing:** Check that your `GEMINI_API_KEY` is correctly set and the machine has internet access.

---

## 📜 License
This project is licensed under the MIT License.

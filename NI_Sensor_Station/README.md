# 🌡️ NI 9213 Thermocouple Logger & Web Dashboard

![Status](https://img.shields.io/badge/Status-Production%20Ready-success)
![Python](https://img.shields.io/badge/Python-3.x-blue)

A robust, "Self-Healing" data acquisition system for National Instruments (NI) hardware. This project logs thermocouple data from an **NI 9213** module to local CSV files and Google Sheets while hosting a live, secure Web Dashboard for remote monitoring and system configuration.

---

## ✨ Key Features

* **Universal Logging:** Simultaneously logs to Local CSV and Google Sheets.
* **Self-Healing Architecture:** Auto-reconnects to the cloud and buffers CSV data if the file is locked.
* **Web Dashboard:** Live temperature gauges, real-time trend plots, and hardware status.
* **Dynamic Configuration:** Configure channels, labels, ranges, and logging targets directly from the Web UI. No code changes required.
* **Robust Hardware Detection:** Automatically formats and handles channels regardless of physical sequence (e.g., Slot 3: TC1, TC2, TC14, TC15).

---

## 🚀 How to Use (For Lab Technicians)

This folder contains a fully self-contained application.

### First-Time Setup
1. Double-click **`SETUP_PREREQUISITES.bat`**.
2. Wait for it to create the Python virtual environment and install all dependencies automatically.

### Running the System
1. Double-click **`START_SYSTEM.bat`**.
2. A terminal window will open, and the system will start.
3. Open your web browser and go to: **`http://localhost:5000`**
4. Log in (Default test emails: `admin@company.com` or `engineer@lab.com` with passwords `admin123` or `engineer123` respectively).
5. Click **"Start Logger"** on the dashboard.

---

## ⚙️ Hardware Configuration

The system uses `config/config.json` for persistent settings. However, **you can change almost all settings directly from the Settings page in the Web Dashboard.**

* **Chassis Setup:** If you need to change the physical module location, you can update the `config.json` file in the `config/` folder.
* **Channels:** The system supports dynamic sequences like `ai1,ai2,ai14,ai15`.

---

## 📂 Project Structure

📦 NI_Sensor_Station
 ┣ 📂 config
 ┃ ┗ 📜 config.json          # Persistent configuration state
 ┣ 📂 src                    # Modular application code (core, daq, web)
 ┣ 📂 logs                   # Application logs
 ┣ 📜 app.py                 # Application entry point
 ┣ 📜 START_SYSTEM.bat       # Launcher script
 ┣ 📜 SETUP_PREREQUISITES.bat# Installation script
 ┣ 📜 requirements.txt       # Dependencies
 ┗ 📜 README.md              # This file

---

## 🔧 Troubleshooting

* **Q: I see "Open" or "Error" instead of temperature.**
  The NI 9213 returns an open-circuit warning if a wire is broken or disconnected. Check your physical sensor wiring on the module.
* **Q: The dashboard won't load.**
  Ensure `START_SYSTEM.bat` is running in the background and that no errors are printed in the terminal.

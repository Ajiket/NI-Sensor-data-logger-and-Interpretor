# NI-Sensor-data-logger-and-Interpretor
This repository will be used to log data from sensors like Thermocouples, Accelerometers, Acoustic Pressure Sensors, Laser Sensors etc. After logging data there will be a Gemini base layer to analyze and interpret the data collected. 

# 🌡️ NI 9213 Thermocouple Logger & Web Dashboard

![Status](https://img.shields.io/badge/Status-Production%20Ready-success)
![Python](https://img.shields.io/badge/Python-3.x-blue)
![License](https://img.shields.io/badge/License-MIT-green)

A robust, "Self-Healing" data acquisition system for National Instruments (NI) hardware. This project logs thermocouple data from an **NI 9213** module to local CSV files and Google Sheets while hosting a live, secure Web Dashboard for remote monitoring.

---

## ✨ Key Features

* **Universal Logging:** Simultaneously logs to:
    * 📂 **Local CSV:** With buffer protection against file locks (e.g., if open in Excel).
    * ☁️ **Google Sheets:** Real-time cloud upload.
    * 🌐 **Web Dashboard:** Live temperature view accessible via browser.
* **Self-Healing Architecture:**
    * **Auto-Reconnect:** Automatically attempts to restore Google Sheets connection if Wi-Fi drops.
    * **Data Buffering:** Queues data in memory if the CSV file is locked, preventing data loss.
* **Secure Access:** Email-based login system for the Web Dashboard.
* **Configurable Speed:** Supports both **High Accuracy** (default) and **High Speed** modes.

---

## 🛠️ Hardware Requirements

* **Chassis:** NI cDAQ-9174, cDAQ-9178, or similar USB/Ethernet chassis.
* **Module:** [NI 9213](https://www.ni.com/en-us/support/model.ni-9213.html) (16-Channel Thermocouple Input).
* **Sensors:** K-Type Thermocouples (configurable for J/T/E).

---

## ⚙️ Software Prerequisites

1.  **Python 3.7+**
2.  **NI-DAQmx Driver:** Download and install from [NI.com](https://www.ni.com/en-us/support/downloads/drivers/download.ni-daqmx.html).
3.  **Google Cloud Project:** (Optional, for Sheets logging)
    * Enable **Google Sheets API** and **Drive API**.
    * Download service account keys as `credentials.json`
  
    
**2. Create Virtual Environment**
     # Windows
python -m venv venv
.\venv\Scripts\activate

# Linux/Mac
python3 -m venv venv
source venv/bin/activate

**3. Install Dependencies**

pip install nidaqmx flask gspread

4. Setup Google Credentials (Optional)

Configuration

Variable,Description,Default
DEVICE_NAME,"The name of your module in NI MAX (e.g., cDAQ1Mod1)","""cDAQ1Mod1"""
CHANNELS_STR,"Range of channels to scan (e.g., ai0:3)","""ai0:3"""
ENABLE_CSV_LOGGING,Toggle local file saving,True
ENABLE_GOOGLE_SHEETS,Toggle cloud uploading,True
SAMPLING_INTERVAL,Seconds between data points,2.0
ENABLE_HIGH_SPEED,Set True for fast scanning (<1s),False
ALLOWED_USERS,List of emails allowed to login,['admin@...']

▶️ **Usage**
1. Start the System
Run the main script:

python production_logger.py

**2.** Access the Dashboard**
****Local PC: Open your browser to http://localhost:5000**

**Remote Device: Open http://<HOST_PC_IP>:5000 (e.g., http://192.168.1.15:5000)**

**3. Login**
Use one of the email addresses defined in the ALLOWED_USERS list config.

**📂 Project Structure
📦 ni-thermocouple-logger
 ┣ 📜 production_logger.py   # Main application (DAQ + Web Server)
 ┣ 📜 credentials.json       # Google Cloud API Key (DO NOT COMMIT THIS)
 ┣ 📜 thermocouple_data.csv  # Generated log file
 ┗ 📜 README.md              # Project Documentation**

 🔧 **Troubleshooting**
Q: The script says "Device not found".

Open NI MAX on your PC.

Check the name under Devices and Interfaces.

Update DEVICE_NAME in the script to match (e.g., Dev1 vs cDAQ1Mod1).

Q: I see "Open" instead of temperature.

The NI 9213 returns a high value (>2000°C) when a wire is broken or disconnected. Check your sensor wiring.

Q: Can I open the CSV while logging?

Yes. The system will detect the file lock, buffer the data in memory, and write it all at once when you close the file.

📜 License
This project is licensed under the MIT License - see the LICENSE file for details.
---

## 🚀 Installation

### 1. Clone the Repository
```bash
git clone [https://github.com/your-username/ni-thermocouple-logger.git](https://github.com/your-username/ni-thermocouple-logger.git)
cd ni-thermocouple-logger

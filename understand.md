# 🧠 Understanding the NI-Sensor System (First Principles)

This document deconstructs the **NI-Sensor-data-logger-and-Interpretor** system into its fundamental engineering principles. It serves as the primary knowledge base for understanding how data moves from physical sensors to the digital dashboard.

---

## 1. Hardware Interaction (The Physical Truth)
The system communicates with National Instruments (NI) hardware using the **NI-DAQmx** driver framework.
*   **Tasks & Channels:** The core unit of work is a `nidaqmx.Task`. We dynamically add Analog Input (AI) Thermocouple channels (`add_ai_thrmcpl_chan`) based on the user's `config.json`.
*   **The "Open Circuit" Phenomenon:** Thermocouple modules like the **NI 9213** return a very high value (typically >2000.0) when a sensor is disconnected. The system uses this physical property to report an "Open" status in the UI.
*   **Sampling Strategy:** We use `CONTINUOUS` acquisition mode. The `SAMPLING_INTERVAL` defines the sleep time between reads, balancing data resolution with CPU overhead.

---

## 2. Concurrency Model (The Dual-Engine Design)
To ensure the dashboard remains responsive while data is being logged, the system employs a multi-threaded architecture:
*   **The DAQ Engine (Daemon Thread):** A dedicated background thread responsible for the heavy lifting. It executes a strict 7-step loop:
    1. Read Hardware -> 2. Process Data -> 3. Push to Buffer -> 4. Flush CSV -> 5. Cloud Upload -> 6. Update Shared Memory -> 7. Sleep.
*   **The Flask Web Server (Main Thread):** Handles user requests, authentication, and serves the dashboard UI.
*   **Shared Memory (The Bridge):** A thread-safe `SharedMemory` class with `threading.RLock()` allows these two engines to exchange data safely without race conditions.

---

## 3. Data Lifecycle & Persistence
A single data point follows this journey:
1.  **Capture:** Read from NI-DAQmx as a raw float.
2.  **Validation:** Checked against the 2000°C threshold.
3.  **Buffering:** Stored in an in-memory `csv_buffer`.
4.  **Local Storage:** Appended to a CSV file in the `data/` folder.
5.  **Cloud Storage:** Uploaded to Google Sheets (if enabled).
6.  **Visualization:** Pulled by the Dashboard via the `/api/data` AJAX endpoint and rendered on SVG gauges.

---

## 4. Resilience & "Self-Healing"
Industrial environments are unpredictable. The system is designed to "heal" itself from common failures:
*   **CSV File Locks:** If a technician opens the CSV file in Excel (which locks the file), the `DAQEngine` detects the `PermissionError`, keeps the data in the memory buffer, and retries until the file is closed. No data is lost.
*   **Network Drops:** If the Google Sheets connection fails, the system enters a "Throttled Retry" state (`CLOUD_RECONNECT_INTERVAL`), preventing the application from hanging while waiting for network timeouts.
*   **Hardware Absence:** If the NI-DAQmx drivers or hardware are missing, the system gracefully degrades to **Demo Mode**, generating synthetic data so the UI can still be tested.

---

## 5. State Management
The system is "State-Aware":
*   **config.json:** The source of truth for all hardware and logging settings.
*   **Runtime Updates:** Settings can be changed via the `/settings` page. To prevent data corruption, the system locks configuration changes while the `DAQEngine` is actively running.
*   **Test Snapshots (.config):** Every time settings are saved, a snapshot of the setup is stored. This ensures that a specific physical test setup can be reproduced later.

---

## 6. Future "Gemini" Layer
The architecture is prepared for an AI interpretation layer. The `SharedMemory` already aggregates "Inferences" (like average temperature and trend direction). The next phase involves feeding this structured data into a Gemini LLM to provide:
*   **Predictive Maintenance:** "Sensor Ch2 is trending 5% higher than normal, check insulation."
*   **Safety Alerts:** "Thermal runaway detected on Ch0. Immediate shutdown recommended."

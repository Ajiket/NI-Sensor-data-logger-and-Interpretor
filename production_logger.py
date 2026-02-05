"""
Production Logger for NI Thermocouple System
Version: 2.1 (Configurable UI)
Project: NI_Thermocouple_Logger_Web_System

This module integrates:
- NI-DAQmx hardware data acquisition with dynamic configuration
- Flask web dashboard with session-based authentication
- CSV local logging with buffer management
- Google Sheets cloud synchronization
- Runtime settings interface for configuration changes
"""

import threading
import time
import csv
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Any
from functools import wraps

import nidaqmx
import gspread
from google.oauth2.service_account import Credentials
from flask import Flask, render_template_string, request, jsonify, session, redirect, url_for, flash
from werkzeug.security import check_password_hash, generate_password_hash

# ============================================================================
# GLOBAL MUTABLE CONFIGURATION (from architecture.yaml v2.1)
# ============================================================================

class GlobalConfig:
    """Mutable configuration container supporting runtime updates."""
    
    def __init__(self):
        self.lock = threading.RLock()
        self.CONFIG_FILE = "config.json"
        self.restart_required = threading.Event()
        
        # config_hardware: Device and channel specifications
        self.config_hardware = {
            "DEVICE_NAME": "cDAQ1Mod1",
            "CHANNELS_STR": "ai0:3",
            "NUM_CHANNELS": 4,
            "TC_TYPE": "K",  # K, J, T, or E
        }
        
        # config_logging: Data persistence settings
        self.config_logging = {
            "ENABLE_CSV_LOGGING": True,
            "ENABLE_GOOGLE_SHEETS": True,
            "CSV_FOLDER": "./Data",  # NEW v2.5: Configurable output folder
            "CSV_FILENAME": "thermocouple_data.csv",  # NEW v2.5: Configurable filename
            "GOOGLE_SHEETS_LINK": "",  # NEW v2.5: User-provided Sheets link (optional)
        }
        
        # config_timing: Sampling and precision settings
        self.config_timing = {
            "SAMPLING_INTERVAL": 2.0,  # seconds
            "DECIMAL_PLACES": 2,
            "ENABLE_HIGH_SPEED": False,
            "CLOUD_RECONNECT_INTERVAL": 60.0
        }
        
        # config_ui: UI customization (v2.4)
        self.config_ui = {
            "sensor_labels": {}  # UI-04: Custom sensor labels {Ch0: "Oven_1", Ch1: "Ambient", ...}
        }
        
        # security: User access control
        self.security = {
            "ALLOWED_USERS": ["admin@company.com", "engineer@lab.com"],
        }
        
        self.load_from_disk()
    
    def load_from_disk(self):
        """Load configuration from JSON file if it exists."""
        if os.path.exists(self.CONFIG_FILE):
            try:
                with open(self.CONFIG_FILE, 'r') as f:
                    data = json.load(f)
                    with self.lock:
                        self.config_hardware.update(data.get("config_hardware", {}))
                        self.config_logging.update(data.get("config_logging", {}))
                        self.config_timing.update(data.get("config_timing", {}))
                        self.config_ui.update(data.get("config_ui", {}))  # UI-04: Load sensor labels
                print("✅ Configuration loaded from config.json")
            except Exception as e:
                print(f"⚠️ Failed to load config.json: {e}")
    
    def save_to_disk(self):
        """Save current configuration to JSON file."""
        data = {
            "config_hardware": self.config_hardware,
            "config_logging": self.config_logging,
            "config_ui": self.config_ui,  # UI-04: Persist sensor labels
            "config_timing": self.config_timing
        }
        try:
            with open(self.CONFIG_FILE, 'w') as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            print(f"⚠️ Failed to save config: {e}")
    
    def update_config(self, section: str, updates: Dict[str, Any]):
        """Thread-safe configuration update."""
        with self.lock:
            if section in ["config_hardware", "config_logging", "config_timing", "security"]:
                getattr(self, section).update(updates)
        
        self.save_to_disk()
        
        # Trigger DAQ restart if hardware changed
        if section == "config_hardware":
            self.restart_required.set()
    
    def get_config(self, section: str) -> Dict[str, Any]:
        """Thread-safe configuration read."""
        with self.lock:
            if section in ["config_hardware", "config_logging", "config_timing", "security"]:
                return dict(getattr(self, section))
        return {}
    
    def get_all_config(self) -> Dict[str, Any]:
        """Get all configuration sections."""
        with self.lock:
            return {
                "config_hardware": dict(self.config_hardware),
                "config_logging": dict(self.config_logging),
                "config_timing": dict(self.config_timing),
                "security": dict(self.security),
            }


# Initialize global configuration
global_config = GlobalConfig()

# ============================================================================
# DAQ CONTROL STATE (New v2.5: On-Demand DAQ Management)
# ============================================================================

class DAQControlState:
    """Manages on-demand DAQ engine lifecycle and state tracking."""
    
    def __init__(self):
        self.lock = threading.RLock()
        self.running = False
        self.daq_engine = None
        self.daq_thread = None
        self.start_time = None
        self.elapsed_seconds = 0
    
    def is_running(self) -> bool:
        """Check if DAQ engine is currently running."""
        with self.lock:
            return self.running
    
    def get_status(self) -> Dict[str, Any]:
        """Get current DAQ status."""
        with self.lock:
            if self.running and self.start_time:
                elapsed = (datetime.now() - datetime.fromisoformat(self.start_time)).total_seconds()
                return {
                    "daq_running": True,
                    "start_time": self.start_time,
                    "elapsed_seconds": int(elapsed)
                }
            else:
                return {
                    "daq_running": False,
                    "start_time": None,
                    "elapsed_seconds": 0
                }


# Initialize DAQ control state (used for on-demand engine management)
daq_control_state = DAQControlState()

# Security Configuration
ALLOWED_USERS = global_config.security["ALLOWED_USERS"]

# File paths (deprecated - will use dynamic paths from config)
CSV_FILE = "thermocouple_data.csv"
CREDENTIALS_FILE = "credentials.json"
SESSION_SECRET_KEY = "production_logger_secret_key_2024"

# TC Type mappings
TC_TYPE_MAP = {
    "K": nidaqmx.constants.ThermocoupleType.K,
    "J": nidaqmx.constants.ThermocoupleType.J,
    "T": nidaqmx.constants.ThermocoupleType.T,
    "E": nidaqmx.constants.ThermocoupleType.E,
}

# ============================================================================
# LOGGING SETUP
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('production_logger.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ============================================================================
# SHARED STATE (Thread-safe Data Container)
# ============================================================================

class SharedMemory:
    """Thread-safe container for shared DAQ data."""
    
    def __init__(self):
        self.lock = threading.RLock()
        # Initialize sensor_data based on current config
        num_channels = global_config.config_hardware["NUM_CHANNELS"]
        self.sensor_data = {f"Ch{i}": None for i in range(num_channels)}
        self.sensor_labels = {f"Ch{i}": f"TC{i+1}" for i in range(num_channels)}  # UI-04: Custom Sensor Tagging
        self.sensor_type_map = {f"Ch{i}": global_config.config_hardware.get("TC_TYPE", "K") for i in range(num_channels)}
        self.sensor_history = {f"Ch{i}": [] for i in range(num_channels)}  # UI-05: For trend plotting (max 100 entries)
        self.timestamp = None
        self.csv_buffer = []
        self.buffer_warning = False
        self.connection_status = "Disconnected"
        self.last_cloud_sync = None
        self.error_log = []
    
    def reinitialize_sensors(self, num_channels: int):
        """Reinitialize sensor data for new channel count."""
        with self.lock:
            self.sensor_data = {f"Ch{i}": None for i in range(num_channels)}
            self.sensor_labels = {f"Ch{i}": f"TC{i+1}" for i in range(num_channels)}  # Reset labels to defaults
            self.sensor_type_map = {f"Ch{i}": global_config.config_hardware.get("TC_TYPE", "K") for i in range(num_channels)}
            self.sensor_history = {f"Ch{i}": [] for i in range(num_channels)}
    
    def update_sensor_data(self, channel_idx: int, value: float, is_open: bool = False):
        """Update sensor data for a specific channel."""
        with self.lock:
            decimal_places = global_config.config_timing["DECIMAL_PLACES"]
            if is_open:
                self.sensor_data[f"Ch{channel_idx}"] = "Open"
            else:
                self.sensor_data[f"Ch{channel_idx}"] = round(value, decimal_places)
            
            # UI-05: Add to trend history (keep last 100 entries)
            if not is_open and value is not None:
                ch_key = f"Ch{channel_idx}"
                timestamp = self.timestamp if self.timestamp else datetime.now().isoformat()
                self.sensor_history[ch_key].append({
                    "timestamp": timestamp,
                    "value": round(value, decimal_places)
                })
                # Keep only last 100 entries
                if len(self.sensor_history[ch_key]) > 100:
                    self.sensor_history[ch_key] = self.sensor_history[ch_key][-100:]
    
    def update_timestamp(self):
        """Update timestamp."""
        with self.lock:
            self.timestamp = datetime.now().isoformat()
    
    def get_snapshot(self) -> Dict[str, Any]:
        """Get current snapshot of all sensor data."""
        with self.lock:
            # Calculate average temperature across all open channels
            temp_values = [v for k, v in self.sensor_data.items() if isinstance(v, (int, float))]
            avg_temperature = sum(temp_values) / len(temp_values) if temp_values else None
            
            return {
                "sensors": dict(self.sensor_data),
                "labels": dict(self.sensor_labels),  # UI-04: Include custom labels
                "timestamp": self.timestamp,
                "connection_status": self.connection_status,
                "buffer_warning": self.buffer_warning,
                "last_cloud_sync": self.last_cloud_sync,
                "avg_temperature": round(avg_temperature, global_config.config_timing["DECIMAL_PLACES"]) if avg_temperature else None,  # UI-05: Average for inference panel
            }
    
    def add_to_csv_buffer(self, row: Dict[str, Any]):
        """Add a row to the CSV buffer."""
        with self.lock:
            self.csv_buffer.append(row)
            if len(self.csv_buffer) > 100:
                self.buffer_warning = True
    
    def flush_csv_buffer(self) -> List[Dict[str, Any]]:
        """Flush and return CSV buffer."""
        with self.lock:
            buffer = self.csv_buffer[:]
            self.csv_buffer = []
            self.buffer_warning = False
            return buffer
    
    def log_error(self, error_msg: str):
        """Log an error message."""
        with self.lock:
            self.error_log.append({
                "timestamp": datetime.now().isoformat(),
                "message": error_msg
            })
            # Keep only last 50 errors
            if len(self.error_log) > 50:
                self.error_log = self.error_log[-50:]
    
    def set_sensor_label(self, channel_key: str, label: str):
        """UI-04: Set custom label for a sensor."""
        with self.lock:
            if channel_key in self.sensor_labels:
                self.sensor_labels[channel_key] = label
    
    def get_sensor_label(self, channel_key: str) -> str:
        """UI-04: Get custom label for a sensor."""
        with self.lock:
            return self.sensor_labels.get(channel_key, f"TC{channel_key}")
    
    def get_trend_data(self, channel_key: str, limit: int = 100) -> List[Dict[str, Any]]:
        """UI-05: Get trend history for a sensor (time-series data)."""
        with self.lock:
            if channel_key in self.sensor_history:
                return self.sensor_history[channel_key][-limit:]
            return []


# Initialize shared memory
shared_memory = SharedMemory()

# ============================================================================
# DAQ ENGINE (Following system_workflow.yaml 7-step sequence)
# ============================================================================

class DAQEngine:
    """Data Acquisition Engine implementing 7-step workflow."""
    
    def __init__(self, shared_mem: SharedMemory):
        self.shared_mem = shared_mem
        self.task = None
        self.running = False
        self.gspread_client = None
        self.worksheet = None
        self.last_cloud_error = 0
        self._initialize_gspread()
    
    def _initialize_gspread(self):
        """Initialize Google Sheets connection."""
        config_logging = global_config.get_config("config_logging")
        if not config_logging.get("ENABLE_GOOGLE_SHEETS"):
            return
        
        try:
            creds = Credentials.from_service_account_file(
                CREDENTIALS_FILE,
                scopes=["https://www.googleapis.com/auth/spreadsheets"]
            )
            self.gspread_client = gspread.authorize(creds)
            logger.info("Google Sheets authentication successful")
        except Exception as e:
            logger.error(f"Failed to authenticate with Google Sheets: {e}")
            self.gspread_client = None
    
    def _open_nidaqmx_task(self):
        """Open and configure NI-DAQmx task."""
        try:
            config_hardware = global_config.get_config("config_hardware")
            config_timing = global_config.get_config("config_timing")
            
            device_name = config_hardware["DEVICE_NAME"]
            channels_str = config_hardware["CHANNELS_STR"]
            tc_type_str = config_hardware["TC_TYPE"]
            sampling_interval = config_timing["SAMPLING_INTERVAL"]
            
            self.task = nidaqmx.Task()
            tc_type = TC_TYPE_MAP.get(tc_type_str, nidaqmx.constants.ThermocoupleType.K)
            
            self.task.ai_channels.add_ai_thrmcpl_chan(
                f"{device_name}/{channels_str}",
                thermocouple_type=tc_type,
                units=nidaqmx.constants.TemperatureUnits.DEG_C
            )
            self.task.timing.cfg_samp_clk_timing(
                rate=1.0 / sampling_interval,
                sample_mode=nidaqmx.constants.AcquisitionType.CONTINUOUS
            )
            
            # FIX: Implement High Speed Mode
            if global_config.config_timing.get("ENABLE_HIGH_SPEED", False):
                self.task.ai_channels.all.ai_adc_timing_mode = nidaqmx.constants.ADCTimingMode.HIGH_SPEED
                
            self.task.start()
            self.shared_mem.connection_status = "Connected"
            num_channels = global_config.config_hardware["NUM_CHANNELS"]
            print(f"✅ DAQ Task Started: {num_channels} channels (High Speed: {global_config.config_timing.get('ENABLE_HIGH_SPEED')})")
        except Exception as e:
            logger.error(f"Failed to open NI-DAQmx task: {e}")
            self.shared_mem.connection_status = "Error"
            raise
    
    def _close_task(self):
        if self.task:
            try:
                self.task.close()
            except:
                pass
            self.task = None
    
    def _read_hardware(self) -> List[float]:
        """Step 1: Read Hardware based on current CONFIG state."""
        try:
            values = self.task.read(number_of_samples_per_channel=1)
            # Flatten list if needed
            if isinstance(values[0], list):
                return values[0]
            return values
        except Exception as e:
            logger.error(f"Hardware read error: {e}")
            self.shared_mem.log_error(f"Hardware read failed: {e}")
            num_channels = global_config.config_hardware["NUM_CHANNELS"]
            return [None] * num_channels
    
    def _process_data(self, raw_values: List[float]) -> Dict[str, Any]:
        """Step 2: Process Data (Check >2000 for open circuit)."""
        processed = {}
        for idx, value in enumerate(raw_values):
            if value is None:
                processed[idx] = {"value": None, "is_open": True, "label": "Error"}
            elif value > 2000:  # Open circuit threshold
                processed[idx] = {"value": value, "is_open": True, "label": "Open"}
            else:
                processed[idx] = {"value": value, "is_open": False, "label": "OK"}
        return processed
    
    def _push_to_csv_buffer(self, processed_data: Dict[str, Any]):
        """Step 3: Push to CSV Buffer (if CSV enabled)."""
        config_logging = global_config.get_config("config_logging")
        if not config_logging.get("ENABLE_CSV_LOGGING"):
            return
        
        self.shared_mem.update_timestamp()
        timestamp = self.shared_mem.timestamp
        
        # Parse ISO timestamp into date (DD/MM/YYYY) and time (HH:MM:SS) components
        dt = datetime.fromisoformat(timestamp)
        date_str = dt.strftime("%d/%m/%Y")
        time_str = dt.strftime("%H:%M:%S")
        
        num_channels = global_config.config_hardware["NUM_CHANNELS"]
        row = {"date": date_str, "time": time_str}
        for ch_idx in range(num_channels):
            if ch_idx in processed_data:
                ch_data = processed_data[ch_idx]
                if ch_data["is_open"]:
                    row[f"Ch{ch_idx}"] = "Open"
                else:
                    row[f"Ch{ch_idx}"] = ch_data["value"]
        
        self.shared_mem.add_to_csv_buffer(row)
    
    def _flush_csv_buffer(self):
        """Step 4: Attempt CSV Write (if CSV enabled). If locked, keep in buffer.
        
        NEW v2.5.1: Uses dynamic CSV path from config (CSV_FOLDER + CSV_FILENAME).
        """
        config_logging = global_config.get_config("config_logging")
        
        buffer = self.shared_mem.flush_csv_buffer()
        
        if not buffer or not config_logging.get("ENABLE_CSV_LOGGING"):
            return
        
        try:
            # NEW v2.5.1: Construct dynamic CSV path from config
            csv_folder = config_logging.get("CSV_FOLDER", "./Data")
            csv_filename = config_logging.get("CSV_FILENAME", "thermocouple_data.csv")
            
            # Ensure folder exists
            csv_path_obj = Path(csv_folder)
            csv_path_obj.mkdir(parents=True, exist_ok=True)
            
            # Construct full file path
            csv_file_path = csv_path_obj / csv_filename
            
            # Check if file exists
            file_exists = csv_file_path.exists()
            
            num_channels = global_config.config_hardware["NUM_CHANNELS"]
            with open(csv_file_path, 'a', newline='', encoding='utf-8') as csvfile:
                fieldnames = ["date", "time"] + [f"Ch{i}" for i in range(num_channels)]
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                
                if not file_exists:
                    writer.writeheader()
                
                for row in buffer:
                    writer.writerow(row)
            
            logger.info(f"Wrote {len(buffer)} rows to CSV at {csv_file_path}")
        
        except PermissionError:
            # File is locked, put data back in buffer
            logger.warning("CSV file locked, buffering data")
            with shared_memory.lock:
                shared_memory.csv_buffer = buffer + shared_memory.csv_buffer
        
        except Exception as e:
            logger.error(f"CSV write error: {e}")
            self.shared_mem.log_error(f"CSV write failed: {e}")
    
    def _upload_to_cloud(self):
        """Step 5: Attempt Cloud Upload (if Sheets enabled). If fail, set worksheet=None.
        
        NEW v2.5.1: Checks for GOOGLE_SHEETS_LINK in config and tries to open by URL first.
        Falls back to opening by sheet name if link is empty or fails.
        """
        config_logging = global_config.get_config("config_logging")
        if not config_logging.get("ENABLE_GOOGLE_SHEETS") or not self.gspread_client:
            return
        
        # FIX: Cloud Reconnect Interval (Prevent Network Hammer)
        retry_interval = global_config.config_timing.get("CLOUD_RECONNECT_INTERVAL", 60)
        if self.worksheet is None:
            if (time.time() - self.last_cloud_error) < retry_interval:
                return
        
        try:
            if self.worksheet is None:
                # NEW v2.5.1: Try to open using GOOGLE_SHEETS_LINK if provided
                google_sheets_link = config_logging.get("GOOGLE_SHEETS_LINK", "").strip()
                
                if google_sheets_link:
                    try:
                        # Extract spreadsheet ID from URL
                        # Expected format: https://docs.google.com/spreadsheets/d/{ID}/...
                        import re
                        match = re.search(r'/spreadsheets/d/([a-zA-Z0-9-_]+)', google_sheets_link)
                        if match:
                            sheet_id = match.group(1)
                            spreadsheet = self.gspread_client.open_by_key(sheet_id)
                            self.worksheet = spreadsheet.get_worksheet(0)
                            logger.info(f"Opened Google Sheet by URL: {sheet_id}")
                        else:
                            logger.warning(f"Could not extract sheet ID from URL: {google_sheets_link}")
                            raise ValueError("Invalid Google Sheets URL format")
                    except Exception as e:
                        # Fall back to opening by name
                        logger.warning(f"Failed to open sheet by URL, falling back to name: {e}")
                        self.worksheet = None
                
                # Fall back to opening by sheet name if link not provided or failed
                if self.worksheet is None:
                    spreadsheet = self.gspread_client.open("Thermocouple Logger")
                    self.worksheet = spreadsheet.get_worksheet(0)
                    logger.info("Opened Google Sheet by name: 'Thermocouple Logger'")
            
            # Get current data snapshot
            snapshot = self.shared_mem.get_snapshot()
            num_channels = global_config.config_hardware["NUM_CHANNELS"]
            row = [snapshot["timestamp"]]
            for i in range(num_channels):
                row.append(snapshot["sensors"].get(f"Ch{i}", ""))
            
            self.worksheet.append_row(row)
            self.shared_mem.last_cloud_sync = datetime.now().isoformat()
            # FIX: Reset error timer on success so we don't stay throttled
            self.last_cloud_error = 0
            logger.info("Successfully uploaded to Google Sheets")
        
        except Exception as e:
            logger.warning(f"Cloud upload failed: {e}")
            self.worksheet = None
            self.last_cloud_error = time.time()
            self.shared_mem.log_error(f"Cloud upload failed: {e}")
    
    def _update_shared_memory(self, processed_data: Dict[str, Any]):
        """Step 6: Update Shared Memory."""
        num_channels = global_config.config_hardware["NUM_CHANNELS"]
        for ch_idx in range(num_channels):
            if ch_idx in processed_data:
                ch_data = processed_data[ch_idx]
                self.shared_mem.update_sensor_data(
                    ch_idx,
                    ch_data["value"],
                    ch_data["is_open"]
                )
    
    def _sleep_interval(self, elapsed_time: float):
        """Step 7: Sleep (Calculated from Sampling Freq)."""
        config_timing = global_config.get_config("config_timing")
        sampling_interval = config_timing["SAMPLING_INTERVAL"]
        sleep_time = max(0, sampling_interval - elapsed_time)
        if sleep_time > 0:
            time.sleep(sleep_time)
    
    def run(self):
        """Main DAQ loop (7-step workflow).
        
        REMOVED v2.5.1: Hot-swap reconfiguration logic (dead code since v2.5).
        New workflow: Settings locked during DAQ run, must stop to reconfigure.
        """
        self.running = True
        self._open_nidaqmx_task()
        
        try:
            while self.running:
                loop_start = time.time()
                
                # Step 1: Read Hardware
                raw_values = self._read_hardware()
                
                # Step 2: Process Data
                processed_data = self._process_data(raw_values)
                
                # Step 3: Push to CSV Buffer
                self._push_to_csv_buffer(processed_data)
                
                # Step 4: Attempt CSV Write
                self._flush_csv_buffer()
                
                # Step 5: Attempt Cloud Upload
                self._upload_to_cloud()
                
                # Step 6: Update Shared Memory
                self._update_shared_memory(processed_data)
                
                # Step 7: Sleep
                elapsed = time.time() - loop_start
                self._sleep_interval(elapsed)
        
        except Exception as e:
            logger.error(f"DAQ engine fatal error: {e}")
            self.shared_mem.log_error(f"DAQ engine error: {e}")
        
        finally:
            self.stop()
    
    def stop(self):
        """Stop the DAQ engine and cleanup."""
        self.running = False
        if self.task:
            try:
                self.task.stop()
                self.task.close()
            except Exception as e:
                logger.error(f"Error closing DAQ task: {e}")
        self.shared_mem.connection_status = "Disconnected"
        logger.info("DAQ engine stopped")


# ============================================================================
# FLASK WEB APPLICATION
# ============================================================================

app = Flask(__name__)
app.secret_key = SESSION_SECRET_KEY

# Email-based user credentials (in production, use proper authentication)
USER_PASSWORDS = {
    "admin@company.com": generate_password_hash("admin123"),
    "engineer@lab.com": generate_password_hash("engineer123"),
}


def login_required(f):
    """Decorator to require login."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function


@app.route("/", methods=["GET"])
def index():
    """Redirect to login or dashboard."""
    if "user" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    """Login view with email-based authentication."""
    if request.method == "POST":
        email = request.form.get("email", "").lower()
        password = request.form.get("password", "")
        
        if email in ALLOWED_USERS and email in USER_PASSWORDS:
            if check_password_hash(USER_PASSWORDS[email], password):
                session["user"] = email
                logger.info(f"User logged in: {email}")
                return redirect(url_for("dashboard"))
        
        return render_template_string(LOGIN_TEMPLATE, error="Invalid credentials")
    
    return render_template_string(LOGIN_TEMPLATE)


@app.route("/dashboard", methods=["GET"])
@login_required
def dashboard():
    """Dashboard view."""
    # FIX: Pass dynamic channel count to template
    num_channels = global_config.config_hardware["NUM_CHANNELS"]
    return render_template_string(DASHBOARD_TEMPLATE, user=session["user"], num_thermocouples=num_channels)


@app.route("/logout", methods=["GET"])
def logout():
    """Logout user."""
    user = session.pop("user", None)
    logger.info(f"User logged out: {user}")
    return redirect(url_for("login"))


@app.route("/api/data", methods=["GET"])
@login_required
def api_data():
    """API endpoint for real-time sensor data (AJAX)."""
    snapshot = shared_memory.get_snapshot()
    return jsonify(snapshot)


@app.route("/api/errors", methods=["GET"])
@login_required
def api_errors():
    """API endpoint for error log."""
    with shared_memory.lock:
        errors = shared_memory.error_log[-10:]  # Last 10 errors
    return jsonify({"errors": errors})


@app.route("/api/sensors/tag", methods=["POST"])
@login_required
def api_sensors_tag():
    """UI-04: API endpoint for setting custom sensor labels."""
    try:
        data = request.get_json()
        channel_key = data.get("channel")  # e.g., "Ch0"
        label = data.get("label", "").strip()
        
        if not channel_key or not label:
            return jsonify({"error": "Missing channel or label"}), 400
        
        # Update label in shared memory
        shared_memory.set_sensor_label(channel_key, label)
        
        # Persist to config
        sensor_labels = global_config.config_ui.get("sensor_labels", {})
        sensor_labels[channel_key] = label
        global_config.update_config("config_ui", {"sensor_labels": sensor_labels})
        
        logger.info(f"Sensor label updated: {channel_key} -> {label}")
        return jsonify({"success": True, "message": f"Label updated: {label}"})
    
    except Exception as e:
        logger.error(f"Error updating sensor label: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/trends/<channel>", methods=["GET"])
@login_required
def api_trends(channel):
    """UI-05: API endpoint for trend data (time-series)."""
    try:
        channel_key = f"Ch{channel}" if not channel.startswith("Ch") else channel
        trend_data = shared_memory.get_trend_data(channel_key)
        
        return jsonify({
            "channel": channel_key,
            "label": shared_memory.get_sensor_label(channel_key),
            "data": trend_data
        })
    
    except Exception as e:
        logger.error(f"Error retrieving trend data: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/start", methods=["POST"])
@login_required
def api_start():
    """NEW v2.5: Start the DAQ engine on-demand."""
    try:
        # Check if DAQ already running
        if daq_control_state.is_running():
            return jsonify({"error": "DAQ Engine is already running"}), 409
        
        # Get current configuration
        config = global_config.get_all_config()
        csv_folder = config["config_logging"].get("CSV_FOLDER", "./Data")
        csv_filename = config["config_logging"].get("CSV_FILENAME", "thermocouple_data.csv")
        
        # Validate and create CSV folder if needed
        try:
            csv_path = Path(csv_folder)
            csv_path.mkdir(parents=True, exist_ok=True)
            logger.info(f"CSV folder verified/created: {csv_path.absolute()}")
        except Exception as e:
            logger.error(f"Failed to create CSV folder: {e}")
            return jsonify({"error": f"Invalid CSV folder: {csv_folder}"}), 400
        
        # Validate CSV filename (no path separators)
        if "/" in csv_filename or "\\" in csv_filename or ".." in csv_filename:
            return jsonify({"error": "CSV filename cannot contain path separators"}), 400
        
        # Start DAQ engine in a new thread
        with daq_control_state.lock:
            daq_control_state.daq_engine = DAQEngine(shared_memory)
            daq_control_state.daq_thread = threading.Thread(
                target=daq_control_state.daq_engine.run, 
                daemon=False  # Non-daemon so we can track it explicitly
            )
            daq_control_state.daq_thread.start()
            daq_control_state.running = True
            daq_control_state.start_time = datetime.now().isoformat()
        
        logger.info(f"DAQ Engine started. CSV: {csv_folder}/{csv_filename}")
        return jsonify({
            "status": "started",
            "message": "DAQ Engine Started",
            "start_time": daq_control_state.start_time,
            "csv_path": f"{csv_folder}/{csv_filename}"
        }), 200
    
    except Exception as e:
        logger.error(f"Failed to start DAQ Engine: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/stop", methods=["POST"])
@login_required
def api_stop():
    """NEW v2.5: Stop the DAQ engine gracefully."""
    try:
        # Check if DAQ is running
        if not daq_control_state.is_running():
            return jsonify({"error": "DAQ Engine is not running"}), 400
        
        # Stop the engine
        with daq_control_state.lock:
            if daq_control_state.daq_engine:
                daq_control_state.daq_engine.stop()
        
        # Wait for thread to finish (with timeout)
        if daq_control_state.daq_thread:
            daq_control_state.daq_thread.join(timeout=5.0)
            if daq_control_state.daq_thread.is_alive():
                logger.warning("DAQ thread did not terminate within timeout")
        
        # Update state
        with daq_control_state.lock:
            daq_control_state.running = False
            daq_control_state.daq_engine = None
            daq_control_state.daq_thread = None
        
        logger.info("DAQ Engine stopped")
        return jsonify({
            "status": "stopped",
            "message": "DAQ Engine Stopped"
        }), 200
    
    except Exception as e:
        logger.error(f"Failed to stop DAQ Engine: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/status", methods=["GET"])
@login_required
def api_status():
    """NEW v2.5: Get current DAQ engine status and configuration."""
    try:
        status = daq_control_state.get_status()
        config = global_config.get_all_config()
        
        return jsonify({
            "daq_running": status["daq_running"],
            "start_time": status["start_time"],
            "elapsed_seconds": status["elapsed_seconds"],
            "config": {
                "num_channels": config["config_hardware"]["NUM_CHANNELS"],
                "csv_folder": config["config_logging"].get("CSV_FOLDER", "./Data"),
                "csv_filename": config["config_logging"].get("CSV_FILENAME", "thermocouple_data.csv"),
                "csv_enabled": config["config_logging"].get("ENABLE_CSV_LOGGING", True),
                "sheets_enabled": config["config_logging"].get("ENABLE_GOOGLE_SHEETS", False),
            }
        }), 200
    
    except Exception as e:
        logger.error(f"Error retrieving DAQ status: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    """Settings view for configuration updates."""
    if request.method == "POST":
        # NEW v2.5: Prevent settings changes while DAQ is running
        if daq_control_state.is_running():
            flash("Cannot change settings while DAQ is running. Please stop the logger first.", "error")
            return redirect(url_for("settings"))
        
        # Parse Form Data (CONFIG-01 through CONFIG-08)
        try:
            num_thermocouples = int(request.form.get("num_thermocouples", 4))
            if not 1 <= num_thermocouples <= 16:
                flash("Number of Thermocouples must be between 1 and 16", "error")
                return redirect(url_for("settings"))
            
            tc_type = request.form.get("tc_type", "K")
            if tc_type not in ["K", "J", "T", "E"]:
                flash("Invalid Thermocouple Type", "error")
                return redirect(url_for("settings"))
            
            sampling_freq = float(request.form.get("sampling_freq", 0.5))
            if sampling_freq <= 0:
                flash("Sampling Frequency must be positive", "error")
                return redirect(url_for("settings"))
            
            enable_csv = request.form.get("enable_csv") == "on"
            enable_sheets = request.form.get("enable_sheets") == "on"
            
            # NEW v2.5: Get and validate CSV folder and filename
            csv_folder = request.form.get("csv_folder", "./Data").strip()
            csv_filename = request.form.get("csv_filename", "thermocouple_data.csv").strip()
            google_sheets_link = request.form.get("google_sheets_link", "").strip()
            
            # Validate CSV folder (reject dangerous paths)
            if ".." in csv_folder or "System" in csv_folder or "Windows" in csv_folder:
                flash("Invalid CSV folder path (cannot contain .., System, or Windows)", "error")
                return redirect(url_for("settings"))
            
            # Validate CSV filename (no path separators)
            if "/" in csv_filename or "\\" in csv_filename:
                flash("CSV filename cannot contain path separators", "error")
                return redirect(url_for("settings"))
            
            # Convert Frequency (Hz) to Interval (seconds)
            sampling_interval = 1.0 / sampling_freq
            
            # Update Global Configuration Dictionary
            global_config.update_config("config_hardware", {
                "NUM_CHANNELS": num_thermocouples,
                "CHANNELS_STR": f"ai0:{num_thermocouples-1}",
                "TC_TYPE": tc_type,
            })
            
            global_config.update_config("config_logging", {
                "ENABLE_CSV_LOGGING": enable_csv,
                "ENABLE_GOOGLE_SHEETS": enable_sheets,
                "CSV_FOLDER": csv_folder,  # NEW v2.5
                "CSV_FILENAME": csv_filename,  # NEW v2.5
                "GOOGLE_SHEETS_LINK": google_sheets_link,  # NEW v2.5
            })
            
            global_config.update_config("config_timing", {
                "SAMPLING_INTERVAL": sampling_interval,
            })
            
            # Reinitialize sensor data
            shared_memory.reinitialize_sensors(num_thermocouples)
            
            # FIX: Clear CSV buffer on reconfig to prevent data corruption
            with shared_memory.lock:
                shared_memory.csv_buffer = []
                shared_memory.buffer_warning = False
            
            logger.info(f"Settings updated: {num_thermocouples} channels, TC Type {tc_type}, "
                       f"Interval {sampling_interval:.2f}s, CSV={enable_csv}, Sheets={enable_sheets}")
            
            flash("Settings Saved Successfully", "success")
            return redirect(url_for("dashboard"))
        
        except ValueError as e:
            flash(f"Invalid input: {e}", "error")
            return redirect(url_for("settings"))
        except Exception as e:
            logger.error(f"Settings update error: {e}")
            flash(f"Error updating settings: {e}", "error")
            return redirect(url_for("settings"))
    
    # GET request: Render Settings Form with current config values
    config = global_config.get_all_config()
    hardware = config["config_hardware"]
    logging_config = config["config_logging"]
    timing = config["config_timing"]
    
    # Convert interval back to frequency
    current_freq = 1.0 / timing["SAMPLING_INTERVAL"]
    
    return render_template_string(
        SETTINGS_TEMPLATE,
        user=session["user"],
        num_thermocouples=hardware["NUM_CHANNELS"],
        tc_type=hardware["TC_TYPE"],
        sampling_freq=current_freq,
        enable_csv=logging_config["ENABLE_CSV_LOGGING"],
        enable_sheets=logging_config["ENABLE_GOOGLE_SHEETS"],
        csv_folder=logging_config.get("CSV_FOLDER", "./Data"),  # NEW v2.5
        csv_filename=logging_config.get("CSV_FILENAME", "thermocouple_data.csv"),  # NEW v2.5
        google_sheets_link=logging_config.get("GOOGLE_SHEETS_LINK", ""),  # NEW v2.5
        daq_running=daq_control_state.is_running(),  # NEW v2.5: Pass DAQ state to template
    )


# ============================================================================
# HTML TEMPLATES (from ux_design.yaml structure)
# ============================================================================

LOGIN_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Sensor Access</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        
        .login-card {
            background: white;
            border-radius: 8px;
            box-shadow: 0 10px 40px rgba(0, 0, 0, 0.2);
            padding: 40px;
            width: 100%;
            max-width: 400px;
        }
        
        .login-card h1 {
            text-align: center;
            color: #333;
            margin-bottom: 30px;
            font-size: 28px;
        }
        
        .form-group {
            margin-bottom: 20px;
        }
        
        .form-group label {
            display: block;
            margin-bottom: 8px;
            color: #555;
            font-weight: 500;
        }
        
        .form-group input {
            width: 100%;
            padding: 12px;
            border: 1px solid #ddd;
            border-radius: 4px;
            font-size: 14px;
            transition: border-color 0.3s;
        }
        
        .form-group input:focus {
            outline: none;
            border-color: #007bff;
            box-shadow: 0 0 0 3px rgba(0, 123, 255, 0.1);
        }
        
        .submit-btn {
            width: 100%;
            padding: 12px;
            background-color: #007bff;
            color: white;
            border: none;
            border-radius: 4px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: background-color 0.3s;
        }
        
        .submit-btn:hover {
            background-color: #0056b3;
        }
        
        .submit-btn:active {
            background-color: #003d82;
        }
        
        .error-message {
            background-color: #dc3545;
            color: white;
            padding: 12px;
            border-radius: 4px;
            margin-bottom: 20px;
            display: {% if error %}block{% else %}none{% endif %};
        }
    </style>
</head>
<body>
    <div class="login-card">
        <h1>Sensor Access</h1>
        {% if error %}
        <div class="error-message">{{ error }}</div>
        {% endif %}
        <form method="POST">
            <div class="form-group">
                <label for="email">Email</label>
                <input type="email" id="email" name="email" required>
            </div>
            <div class="form-group">
                <label for="password">Password</label>
                <input type="password" id="password" name="password" required>
            </div>
            <button type="submit" class="submit-btn">Login</button>
        </form>
    </div>
</body>
</html>
"""

DASHBOARD_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Thermocouple Logger Dashboard</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            background-color: #f5f7fa;
            color: #333;
        }
        
        /* Header */
        header {
            background-color: #2c3e50;
            color: white;
            padding: 20px 40px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
        }
        
        header h1 {
            font-size: 24px;
            font-weight: 600;
        }
        
        header .user-info {
            display: flex;
            align-items: center;
            gap: 20px;
        }
        
        header .user-email {
            font-size: 14px;
        }
        
        header a {
            color: white;
            text-decoration: none;
            font-size: 14px;
            padding: 8px 16px;
            background-color: #dc3545;
            border-radius: 4px;
            transition: background-color 0.3s;
        }
        
        header a:hover {
            background-color: #c82333;
        }
        
        /* Status Bar */
        .status-bar {
            background-color: #ecf0f1;
            padding: 15px 40px;
            border-bottom: 1px solid #bdc3c7;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 20px;
        }
        
        .status-item {
            display: flex;
            align-items: center;
            gap: 10px;
            font-size: 14px;
        }
        
        .status-indicator {
            display: inline-block;
            width: 12px;
            height: 12px;
            border-radius: 50%;
            background-color: #95a5a6;
        }
        
        .status-indicator.connected {
            background-color: #27ae60;
        }
        
        .status-indicator.disconnected {
            background-color: #e74c3c;
        }
        
        .buffer-warning {
            background-color: #fff3cd;
            color: #856404;
            padding: 8px 12px;
            border-radius: 4px;
            font-size: 12px;
        }
        
        /* Main Content */
        .container {
            max-width: 1200px;
            margin: 40px auto;
            padding: 0 20px;
        }
        
        /* Sensor Grid */
        .sensor-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 20px;
            margin-bottom: 40px;
        }
        
        .sensor-card {
            background: white;
            border-radius: 8px;
            padding: 20px;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
            transition: box-shadow 0.3s, transform 0.3s;
            position: relative;
            min-height: 300px;
        }
        
        .sensor-card:hover {
            box-shadow: 0 4px 16px rgba(0, 0, 0, 0.15);
            transform: translateY(-2px);
        }
        
        .sensor-card h3 {
            font-size: 12px;
            color: #7f8c8d;
            margin-bottom: 5px;
            font-weight: 500;
            text-transform: uppercase;
        }
        
        .sensor-label {
            font-size: 16px;
            font-weight: 600;
            color: #2c3e50;
            margin-bottom: 15px;
        }
        
        /* UI-06: Gauge Visualization */
        .gauge-container {
            width: 100%;
            height: 180px;
            display: flex;
            justify-content: center;
            align-items: center;
            margin-bottom: 10px;
        }
        
        .gauge-svg {
            width: 100%;
            height: 100%;
        }
        
        .sensor-value {
            font-size: 28px;
            font-weight: 700;
            color: #2c3e50;
            text-align: center;
            margin-bottom: 5px;
        }
        
        .sensor-unit {
            font-size: 12px;
            color: #95a5a6;
            text-align: center;
        }
        
        .sensor-status {
            display: inline-block;
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: 600;
            margin-top: 10px;
            width: 100%;
            text-align: center;
        }
        
        .sensor-status.ok {
            background-color: #d4edda;
            color: #155724;
        }
        
        .sensor-status.open {
            background-color: #f8d7da;
            color: #721c24;
        }
        
        .sensor-status.error {
            background-color: #f5c6cb;
            color: #721c24;
        }
        
        /* UI-05: Trend Plot Section */
        .trends-section {
            background: white;
            border-radius: 8px;
            padding: 20px;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
            margin-bottom: 40px;
        }
        
        .trends-section h2 {
            font-size: 18px;
            font-weight: 600;
            color: #2c3e50;
            margin-bottom: 20px;
        }
        
        .trends-container {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
        }
        
        .trend-chart-wrapper {
            background: white;
            border-radius: 8px;
            padding: 15px;
            border: 1px solid #ecf0f1;
        }
        
        .trend-chart {
            position: relative;
            height: 300px;
        }
        
        .inference-panel {
            background: #f8f9fa;
            border-radius: 8px;
            padding: 15px;
            border: 1px solid #ecf0f1;
        }
        
        .inference-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px 0;
            border-bottom: 1px solid #ecf0f1;
        }
        
        .inference-item:last-child {
            border-bottom: none;
        }
        
        .inference-label {
            font-weight: 600;
            color: #555;
            font-size: 14px;
        }
        
        .inference-value {
            font-size: 16px;
            font-weight: 700;
            color: #2c3e50;
        }
        
        /* Footer */
        footer {
            text-align: center;
            padding: 20px;
            color: #7f8c8d;
            font-size: 12px;
            margin-top: 40px;
        }
        
        /* Responsive */
        @media (max-width: 1024px) {
            .trends-container {
                grid-template-columns: 1fr;
            }
        }
        
        @media (max-width: 768px) {
            header {
                flex-direction: column;
                gap: 10px;
            }
            
            .status-bar {
                flex-direction: column;
                align-items: flex-start;
            }
            
            .sensor-grid {
                grid-template-columns: 1fr;
            }
        }
    </style>
</head>
<body>
    <header>
        <h1>Thermocouple Logger</h1>
        <div class="user-info">
            <div class="user-email">{{ user }}</div>
            <a href="/settings" style="background-color: #17a2b8;">Settings</a>
            <a href="/logout">Logout</a>
        </div>
    </header>
    
    <div class="status-bar">
        <div class="status-item">
            <span class="status-indicator" id="connectionStatus"></span>
            <span>Connection: <strong id="connectionText">Loading...</strong></span>
        </div>
        <div class="status-item">
            <span>Timestamp: <strong id="timestamp">--:--:--</strong></span>
        </div>
        <div id="bufferWarning" style="display: none;">
            <span class="buffer-warning">⚠️ CSV Buffer is filling up</span>
        </div>
    </div>
    
    <!-- NEW v2.5: DAQ Control Panel -->
    <div style="background-color: #f8f9fa; padding: 20px 40px; border-bottom: 1px solid #dee2e6;">
        <div style="max-width: 1200px; margin: 0 auto; display: flex; justify-content: space-between; align-items: center; gap: 20px; flex-wrap: wrap;">
            <div style="display: flex; align-items: center; gap: 15px;">
                <button id="startBtn" style="padding: 10px 20px; background-color: #28a745; color: white; border: none; border-radius: 4px; font-weight: 600; cursor: pointer; font-size: 14px; transition: background-color 0.3s;">
                    ▶ Start Logger
                </button>
                <button id="stopBtn" style="padding: 10px 20px; background-color: #dc3545; color: white; border: none; border-radius: 4px; font-weight: 600; cursor: pointer; font-size: 14px; transition: background-color 0.3s; opacity: 0.5; cursor: not-allowed;" disabled>
                    ⏹ Stop Logger
                </button>
            </div>
            <div style="display: flex; align-items: center; gap: 10px;">
                <span style="font-weight: 600; font-size: 14px;">Status:</span>
                <span id="daqStatus" style="display: inline-block; padding: 6px 12px; background-color: #dc3545; color: white; border-radius: 4px; font-weight: 600; font-size: 12px;">STOPPED</span>
                <span id="elapsedTime" style="font-size: 12px; color: #555; margin-left: 10px;"></span>
            </div>
        </div>
    </div>
    
    <div class="container">
        <div class="sensor-grid" id="sensorGrid">
            <!-- Sensor cards with gauges will be inserted here by JavaScript -->
        </div>
        
        <!-- UI-05: Real-Time Trend Plot Section -->
        <div class="trends-section">
            <h2>📊 Real-Time Trend Plot</h2>
            <div class="trends-container">
                <div class="trend-chart-wrapper">
                    <div class="trend-chart">
                        <canvas id="trendChart"></canvas>
                    </div>
                </div>
                <div class="inference-panel">
                    <h3 style="margin-bottom: 15px; color: #2c3e50;">Inference Panel</h3>
                    <div class="inference-item">
                        <span class="inference-label">Average Temperature:</span>
                        <span class="inference-value" id="avgTemp">--°C</span>
                    </div>
                    <div class="inference-item">
                        <span class="inference-label">Current Time:</span>
                        <span class="inference-value" id="currentTime" style="font-size: 14px;">--:--:--</span>
                    </div>
                    <div class="inference-item">
                        <span class="inference-label">Cursor Value:</span>
                        <span class="inference-value" id="cursorValue">Hover chart</span>
                    </div>
                    <div class="inference-item">
                        <span class="inference-label">Trend Direction:</span>
                        <span class="inference-value" id="trendDirection">--</span>
                    </div>
                </div>
            </div>
        </div>
    </div>
    
    <footer>
        <p>Data updates every 2 seconds | NI Thermocouple Logger v2.4 (Gauges, Trends & Tagging)</p>
    </footer>
    
    <!-- Chart.js Library for Trend Plotting -->
    <script src="https://cdn.jsdelivr.net/npm/chart.js@3.9.1/dist/chart.min.js"></script>
    
    <script>
        // Configuration
        const SENSOR_CHANNELS = {{ num_thermocouples }};
        const UPDATE_INTERVAL = 2000;  // 2 seconds
        let trendChart = null;
        const trendDataCache = {};  // Cache for trend data
        
        // Initialize trend data cache
        for (let i = 0; i < SENSOR_CHANNELS; i++) {
            trendDataCache[`Ch${i}`] = [];
        }
        
        // Color palette for different sensors
        const colors = [
            '#FF6384', '#36A2EB', '#FFCE56', '#4BC0C0',
            '#9966FF', '#FF9F40', '#FF6384', '#C9CBCF'
        ];
        
        // UI-06: Draw Gauge (Speedometer-style visualization)
        function drawGauge(container, value, label) {
            const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
            svg.setAttribute('viewBox', '0 0 200 120');
            svg.setAttribute('class', 'gauge-svg');
            
            const gauge = document.createElementNS('http://www.w3.org/2000/svg', 'g');
            
            // Background arc
            const arc = document.createElementNS('http://www.w3.org/2000/svg', 'path');
            arc.setAttribute('d', 'M 20 100 A 80 80 0 0 1 180 100');
            arc.setAttribute('stroke', '#ecf0f1');
            arc.setAttribute('stroke-width', '8');
            arc.setAttribute('fill', 'none');
            gauge.appendChild(arc);
            
            // Value arc (0-100 scale)
            const valueArc = document.createElementNS('http://www.w3.org/2000/svg', 'path');
            const normalizedValue = Math.max(0, Math.min(100, value ? (value + 50) / 1.5 : 0));  // Assume range -50 to 100°C
            const angle = (normalizedValue / 100) * Math.PI;
            const x = 100 + 80 * Math.cos(Math.PI - angle);
            const y = 100 + 80 * Math.sin(Math.PI - angle);
            valueArc.setAttribute('d', `M 20 100 A 80 80 0 0 1 ${x} ${y}`);
            valueArc.setAttribute('stroke', normalizedValue > 66 ? '#e74c3c' : normalizedValue > 33 ? '#f39c12' : '#27ae60');
            valueArc.setAttribute('stroke-width', '8');
            valueArc.setAttribute('fill', 'none');
            gauge.appendChild(valueArc);
            
            // Center circle
            const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
            circle.setAttribute('cx', '100');
            circle.setAttribute('cy', '100');
            circle.setAttribute('r', '5');
            circle.setAttribute('fill', '#2c3e50');
            gauge.appendChild(circle);
            
            // Needle
            const needle = document.createElementNS('http://www.w3.org/2000/svg', 'line');
            needle.setAttribute('x1', '100');
            needle.setAttribute('y1', '100');
            needle.setAttribute('x2', x);
            needle.setAttribute('y2', y);
            needle.setAttribute('stroke', '#2c3e50');
            needle.setAttribute('stroke-width', '3');
            needle.setAttribute('stroke-linecap', 'round');
            gauge.appendChild(needle);
            
            svg.appendChild(gauge);
            container.innerHTML = '';
            container.appendChild(svg);
        }
        
        function initializeSensorGrid() {
            const grid = document.getElementById('sensorGrid');
            grid.innerHTML = '';
            
            for (let i = 0; i < SENSOR_CHANNELS; i++) {
                const card = document.createElement('div');
                card.className = 'sensor-card';
                card.id = `sensor-ch${i}`;
                card.innerHTML = `
                    <h3>Channel ${i}</h3>
                    <div class="sensor-label" id="label-ch${i}">TC${i+1}</div>
                    <div class="gauge-container" id="gauge-ch${i}"></div>
                    <div class="sensor-value" id="value-ch${i}">--</div>
                    <span class="sensor-unit">°C</span>
                    <div class="sensor-status" id="status-ch${i}">Disconnected</div>
                `;
                grid.appendChild(card);
            }
        }
        
        function updateDashboard() {
            fetch('/api/data')
                .then(response => response.json())
                .then(data => {
                    // Update sensor values and gauges
                    for (let i = 0; i < SENSOR_CHANNELS; i++) {
                        const chKey = `Ch${i}`;
                        const value = data.sensors[chKey];
                        const label = data.labels && data.labels[chKey] ? data.labels[chKey] : `TC${i+1}`;
                        const valueElem = document.getElementById(`value-ch${i}`);
                        const statusElem = document.getElementById(`status-ch${i}`);
                        const labelElem = document.getElementById(`label-ch${i}`);
                        const gaugeContainer = document.getElementById(`gauge-ch${i}`);
                        
                        labelElem.textContent = label;
                        
                        if (value === 'Open') {
                            valueElem.textContent = 'Open';
                            statusElem.textContent = 'Circuit Open';
                            statusElem.className = 'sensor-status open';
                            drawGauge(gaugeContainer, null, label);
                        } else if (value === null || value === undefined || value === 'Error') {
                            valueElem.textContent = '--';
                            statusElem.textContent = 'Error';
                            statusElem.className = 'sensor-status error';
                            drawGauge(gaugeContainer, null, label);
                        } else {
                            valueElem.textContent = typeof value === 'number' ? value.toFixed(2) : value;
                            statusElem.textContent = 'OK';
                            statusElem.className = 'sensor-status ok';
                            drawGauge(gaugeContainer, value, label);
                        }
                    }
                    
                    // Update connection status
                    const connStatus = document.getElementById('connectionStatus');
                    const connText = document.getElementById('connectionText');
                    if (data.connection_status === 'Connected') {
                        connStatus.className = 'status-indicator connected';
                        connText.textContent = 'Connected';
                    } else {
                        connStatus.className = 'status-indicator disconnected';
                        connText.textContent = data.connection_status || 'Disconnected';
                    }
                    
                    // Update timestamp
                    if (data.timestamp) {
                        const dt = new Date(data.timestamp);
                        document.getElementById('timestamp').textContent = dt.toLocaleTimeString();
                        document.getElementById('currentTime').textContent = dt.toLocaleTimeString();
                    }
                    
                    // Update average temperature (UI-05: Inference Panel)
                    if (data.avg_temperature !== null && data.avg_temperature !== undefined) {
                        document.getElementById('avgTemp').textContent = data.avg_temperature.toFixed(2) + '°C';
                    }
                    
                    // Update buffer warning
                    const bufferWarning = document.getElementById('bufferWarning');
                    if (data.buffer_warning) {
                        bufferWarning.style.display = 'block';
                    } else {
                        bufferWarning.style.display = 'none';
                    }
                })
                .catch(error => {
                    console.error('Failed to fetch data:', error);
                });
            
            // Fetch trend data for all channels
            updateTrendPlot();
        }
        
        function updateTrendPlot() {
            // Fetch trend data for each channel
            const trendPromises = [];
            for (let i = 0; i < SENSOR_CHANNELS; i++) {
                trendPromises.push(
                    fetch(`/api/trends/Ch${i}`)
                        .then(response => response.json())
                        .then(data => {
                            trendDataCache[`Ch${i}`] = data.data || [];
                        })
                        .catch(error => console.error(`Failed to fetch trend for Ch${i}:`, error))
                );
            }
            
            Promise.all(trendPromises).then(() => {
                renderTrendChart();
            });
        }
        
        function renderTrendChart() {
            const ctx = document.getElementById('trendChart');
            if (!ctx) return;
            
            // Prepare datasets for all channels
            const datasets = [];
            for (let i = 0; i < SENSOR_CHANNELS; i++) {
                const chKey = `Ch${i}`;
                const trendData = trendDataCache[chKey] || [];
                
                if (trendData.length > 0) {
                    datasets.push({
                        label: `Ch${i}`,
                        data: trendData.map(d => ({
                            x: new Date(d.timestamp).toLocaleTimeString(),
                            y: d.value
                        })),
                        borderColor: colors[i % colors.length],
                        backgroundColor: colors[i % colors.length] + '20',
                        borderWidth: 2,
                        tension: 0.4,
                        fill: false,
                        pointRadius: 3,
                        pointBackgroundColor: colors[i % colors.length]
                    });
                }
            }
            
            // Destroy existing chart
            if (trendChart) {
                trendChart.destroy();
            }
            
            // Create new chart
            trendChart = new Chart(ctx, {
                type: 'line',
                data: {
                    datasets: datasets
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            position: 'top',
                        },
                        title: {
                            display: true,
                            text: 'Temperature Trend (Last 100 samples)'
                        }
                    },
                    scales: {
                        y: {
                            title: {
                                display: true,
                                text: 'Temperature (°C)'
                            }
                        },
                        x: {
                            title: {
                                display: true,
                                text: 'Time'
                            }
                        }
                    }
                }
            });
            
            // Calculate trend direction (simple: compare last 5 points)
            calculateTrendDirection();
        }
        
        function calculateTrendDirection() {
            let allValues = [];
            for (let i = 0; i < SENSOR_CHANNELS; i++) {
                const trendData = trendDataCache[`Ch${i}`] || [];
                allValues = allValues.concat(trendData.map(d => d.value));
            }
            
            if (allValues.length > 5) {
                const recent = allValues.slice(-5);
                const older = allValues.slice(-10, -5);
                const recentAvg = recent.reduce((a, b) => a + b, 0) / recent.length;
                const olderAvg = older.reduce((a, b) => a + b, 0) / older.length;
                
                const directionElem = document.getElementById('trendDirection');
                if (recentAvg > olderAvg) {
                    directionElem.textContent = '📈 Increasing';
                    directionElem.style.color = '#e74c3c';
                } else if (recentAvg < olderAvg) {
                    directionElem.textContent = '📉 Decreasing';
                    directionElem.style.color = '#3498db';
                } else {
                    directionElem.textContent = '➡️ Stable';
                    directionElem.style.color = '#27ae60';
                }
            }
        }
        
        // NEW v2.5: DAQ Control Handlers
        async function updateDaqStatus() {
            try {
                const response = await fetch('/api/status');
                const data = await response.json();
                
                const statusBadge = document.getElementById('daqStatus');
                const startBtn = document.getElementById('startBtn');
                const stopBtn = document.getElementById('stopBtn');
                const elapsedTime = document.getElementById('elapsedTime');
                
                if (data.daq_running) {
                    statusBadge.textContent = 'RUNNING';
                    statusBadge.style.backgroundColor = '#28a745';
                    startBtn.disabled = true;
                    startBtn.style.opacity = '0.5';
                    startBtn.style.cursor = 'not-allowed';
                    stopBtn.disabled = false;
                    stopBtn.style.opacity = '1';
                    stopBtn.style.cursor = 'pointer';
                    
                    if (data.start_time && data.elapsed_seconds !== undefined) {
                        elapsedTime.textContent = `Elapsed: ${data.elapsed_seconds}s`;
                    }
                } else {
                    statusBadge.textContent = 'STOPPED';
                    statusBadge.style.backgroundColor = '#dc3545';
                    startBtn.disabled = false;
                    startBtn.style.opacity = '1';
                    startBtn.style.cursor = 'pointer';
                    stopBtn.disabled = true;
                    stopBtn.style.opacity = '0.5';
                    stopBtn.style.cursor = 'not-allowed';
                    elapsedTime.textContent = '';
                }
            } catch (error) {
                console.error('Failed to update DAQ status:', error);
            }
        }
        
        // Initialize on page load
        document.addEventListener('DOMContentLoaded', function() {
            initializeSensorGrid();
            updateDashboard();
            updateDaqStatus();
            
            // NEW v2.5: Add event listeners for Start/Stop buttons
            document.getElementById('startBtn').addEventListener('click', async function() {
                try {
                    const response = await fetch('/api/start', {method: 'POST'});
                    const data = await response.json();
                    
                    if (response.ok) {
                        alert('Data Logger started successfully!');
                        updateDaqStatus();
                    } else {
                        alert('Error: ' + (data.error || 'Failed to start DAQ'));
                    }
                } catch (error) {
                    console.error('Error:', error);
                    alert('Failed to start logger');
                }
            });
            
            document.getElementById('stopBtn').addEventListener('click', async function() {
                if (confirm('Stop the data logger?')) {
                    try {
                        const response = await fetch('/api/stop', {method: 'POST'});
                        const data = await response.json();
                        
                        if (response.ok) {
                            alert('Data Logger stopped successfully!');
                            updateDaqStatus();
                        } else {
                            alert('Error: ' + (data.error || 'Failed to stop DAQ'));
                        }
                    } catch (error) {
                        console.error('Error:', error);
                        alert('Failed to stop logger');
                    }
                }
            });
            
            // Set up auto-refresh every 2 seconds
            setInterval(updateDashboard, UPDATE_INTERVAL);
            
            // NEW v2.5: Update DAQ status every 2 seconds as well
            setInterval(updateDaqStatus, UPDATE_INTERVAL);
        });
    </script>
</body>
</html>
"""

SETTINGS_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>System Configuration</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            background-color: #f5f7fa;
            color: #333;
        }
        
        /* Header */
        header {
            background-color: #2c3e50;
            color: white;
            padding: 20px 40px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
        }
        
        header h1 {
            font-size: 24px;
            font-weight: 600;
        }
        
        header .user-info {
            display: flex;
            align-items: center;
            gap: 20px;
        }
        
        header a {
            color: white;
            text-decoration: none;
            font-size: 14px;
            padding: 8px 16px;
            background-color: #dc3545;
            border-radius: 4px;
            transition: background-color 0.3s;
        }
        
        header a:hover {
            background-color: #c82333;
        }
        
        /* Main Content */
        .container {
            max-width: 600px;
            margin: 40px auto;
            padding: 0 20px;
        }
        
        /* Form Card */
        .settings-card {
            background: white;
            border-radius: 8px;
            padding: 30px;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
        }
        
        .settings-card h2 {
            margin-bottom: 30px;
            font-size: 22px;
            color: #2c3e50;
        }
        
        /* Flash Messages */
        .alert {
            padding: 12px 15px;
            border-radius: 4px;
            margin-bottom: 20px;
            display: none;
        }
        
        .alert.success {
            display: block;
            background-color: #d4edda;
            color: #155724;
            border: 1px solid #c3e6cb;
        }
        
        .alert.error {
            display: block;
            background-color: #f8d7da;
            color: #721c24;
            border: 1px solid #f5c6cb;
        }
        
        /* Form Groups */
        .form-group {
            margin-bottom: 25px;
        }
        
        .form-group label {
            display: block;
            margin-bottom: 8px;
            color: #555;
            font-weight: 500;
            font-size: 14px;
        }
        
        .form-group input,
        .form-group select {
            width: 100%;
            padding: 10px;
            border: 1px solid #ddd;
            border-radius: 4px;
            font-size: 14px;
            transition: border-color 0.3s;
        }
        
        .form-group input:focus,
        .form-group select:focus {
            outline: none;
            border-color: #007bff;
            box-shadow: 0 0 0 3px rgba(0, 123, 255, 0.1);
        }
        
        /* Checkbox Group */
        .checkbox-group {
            display: flex;
            flex-direction: column;
            gap: 12px;
        }
        
        .checkbox-item {
            display: flex;
            align-items: center;
        }
        
        .checkbox-item input[type="checkbox"] {
            width: auto;
            margin-right: 8px;
            cursor: pointer;
        }
        
        .checkbox-item label {
            margin: 0;
            font-weight: normal;
            cursor: pointer;
            display: flex;
            align-items: center;
        }
        
        /* Buttons */
        .button-group {
            display: flex;
            gap: 15px;
            margin-top: 30px;
        }
        
        .btn {
            padding: 12px 24px;
            border: none;
            border-radius: 4px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: background-color 0.3s;
            text-decoration: none;
            display: inline-block;
            text-align: center;
            flex: 1;
        }
        
        .btn-success {
            background-color: #28a745;
            color: white;
        }
        
        .btn-success:hover {
            background-color: #218838;
        }
        
        .btn-secondary {
            background-color: #6c757d;
            color: white;
        }
        
        .btn-secondary:hover {
            background-color: #5a6268;
        }
        
        /* Help Text */
        .help-text {
            font-size: 12px;
            color: #7f8c8d;
            margin-top: 5px;
        }
        
        /* Responsive */
        @media (max-width: 768px) {
            .container {
                margin: 20px auto;
            }
            
            .settings-card {
                padding: 20px;
            }
            
            .button-group {
                flex-direction: column;
            }
        }
    </style>
</head>
<body>
    <header>
        <h1>Thermocouple Logger</h1>
        <div class="user-info">
            <div style="font-size: 14px;">{{ user }}</div>
            <a href="/dashboard">Back to Dashboard</a>
        </div>
    </header>
    
    <div class="container">
        <div class="settings-card">
            <h2>System Configuration</h2>
            
            {% with messages = get_flashed_messages(with_categories=true) %}
                {% if messages %}
                    {% for category, message in messages %}
                        <div class="alert {{ category }}">{{ message }}</div>
                    {% endfor %}
                {% endif %}
            {% endwith %}
            
            <form method="POST" action="/settings">
                <!-- Number of Thermocouples (CONFIG-01) -->
                <div class="form-group">
                    <label for="num_thermocouples">Number of Thermocouples</label>
                    <input type="number" 
                           id="num_thermocouples" 
                           name="num_thermocouples" 
                           min="1" 
                           max="16" 
                           value="{{ num_thermocouples }}" 
                           required>
                    <div class="help-text">Valid range: 1 to 16 thermocouples</div>
                </div>
                
                <!-- Thermocouple Type (CONFIG-02) -->
                <div class="form-group">
                    <label for="tc_type">Thermocouple Type</label>
                    <select id="tc_type" name="tc_type" required>
                        <option value="K" {% if tc_type == 'K' %}selected{% endif %}>Type K (Chromel-Alumel)</option>
                        <option value="J" {% if tc_type == 'J' %}selected{% endif %}>Type J (Iron-Constantan)</option>
                        <option value="T" {% if tc_type == 'T' %}selected{% endif %}>Type T (Copper-Constantan)</option>
                        <option value="E" {% if tc_type == 'E' %}selected{% endif %}>Type E (Chromel-Constantan)</option>
                    </select>
                    <div class="help-text">Select the thermocouple type connected to your hardware</div>
                </div>
                
                <!-- Sampling Frequency (CONFIG-03) -->
                <div class="form-group">
                    <label for="sampling_freq">Sampling Frequency (Hz)</label>
                    <input type="number" 
                           id="sampling_freq" 
                           name="sampling_freq" 
                           min="0.1" 
                           step="0.1" 
                           value="{{ sampling_freq }}" 
                           required>
                    <div class="help-text">Data points per second (e.g., 0.5 Hz = 1 reading every 2 seconds)</div>
                </div>
                
                <!-- Logging Targets (CONFIG-04) -->
                <div class="form-group">
                    <label>Logging Targets</label>
                    <div class="checkbox-group">
                        <div class="checkbox-item">
                            <input type="checkbox" 
                                   id="enable_csv" 
                                   name="enable_csv"
                                   {% if enable_csv %}checked{% endif %}>
                            <label for="enable_csv">CSV File Logging</label>
                        </div>
                        <div class="checkbox-item">
                            <input type="checkbox" 
                                   id="enable_sheets" 
                                   name="enable_sheets"
                                   {% if enable_sheets %}checked{% endif %}>
                            <label for="enable_sheets">Google Sheets Upload</label>
                        </div>
                    </div>
                    <div class="help-text">Select where to store your data</div>
                </div>
                
                <!-- CSV Folder (CONFIG-06) - NEW v2.5 -->
                <div class="form-group">
                    <label for="csv_folder">CSV Output Folder</label>
                    <input type="text" 
                           id="csv_folder" 
                           name="csv_folder" 
                           value="{{ csv_folder }}" 
                           placeholder="./Data"
                           required>
                    <div class="help-text">Relative or absolute path (e.g., ./Data, /home/user/data). Will be created if missing.</div>
                </div>
                
                <!-- CSV Filename (CONFIG-07) - NEW v2.5 -->
                <div class="form-group">
                    <label for="csv_filename">CSV Filename</label>
                    <input type="text" 
                           id="csv_filename" 
                           name="csv_filename" 
                           value="{{ csv_filename }}" 
                           placeholder="thermocouple_data.csv"
                           required>
                    <div class="help-text">Filename only (no path separators). Default: thermocouple_data.csv</div>
                </div>
                
                <!-- Google Sheets Link (CONFIG-08) - NEW v2.5 -->
                <div class="form-group">
                    <label for="google_sheets_link">Google Sheets Link</label>
                    <input type="url" 
                           id="google_sheets_link" 
                           name="google_sheets_link" 
                           value="{{ google_sheets_link }}" 
                           placeholder="https://docs.google.com/spreadsheets/d/..."
                           required>
                    <div class="help-text">Optional: Provide the link to your Google Sheets for cloud sync (leave blank to disable)</div>
                </div>
                
                <!-- DAQ Status Warning - NEW v2.5 -->
                {% if daq_running %}
                <div class="alert error" style="display: block; margin-bottom: 20px;">
                    <strong>⚠️ Note:</strong> The data logger is currently running. Stop it before changing settings to avoid data corruption.
                </div>
                {% endif %}
                
                <!-- UI-04: Custom Sensor Tagging -->
                <div class="form-group">
                    <label>Custom Sensor Labels</label>
                    <div style="background-color: #f8f9fa; padding: 15px; border-radius: 4px; margin-top: 10px;">
                        <div id="sensor-labels-container">
                            <!-- Sensor label inputs will be inserted here by JavaScript -->
                        </div>
                    </div>
                    <div class="help-text">Assign custom names to each thermocouple (e.g., "Oven_Loc1", "Ambient", "Freezer")</div>
                </div>
                
                <!-- Buttons -->
                <div class="button-group">
                    <button type="submit" class="btn btn-success">Save & Apply</button>
                    <a href="/dashboard" class="btn btn-secondary">Back to Dashboard</a>
                </div>
            </form>
        </div>
    </div>
    
    <script>
        // UI-04: Initialize sensor label inputs on page load
        document.addEventListener('DOMContentLoaded', function() {
            const numThermocouples = parseInt(document.getElementById('num_thermocouples').value);
            const container = document.getElementById('sensor-labels-container');
            container.innerHTML = '';
            
            for (let i = 0; i < numThermocouples; i++) {
                const ch = `Ch${i}`;
                const inputDiv = document.createElement('div');
                inputDiv.style.marginBottom = '10px';
                inputDiv.innerHTML = `
                    <div style="display: flex; gap: 10px; align-items: center;">
                        <label style="min-width: 80px; font-weight: 500;">Channel ${i}:</label>
                        <input type="text" 
                               id="label_${i}" 
                               class="sensor-label-input"
                               data-channel="${ch}"
                               placeholder="e.g., TC${i+1}"
                               style="flex: 1; padding: 8px; border: 1px solid #ddd; border-radius: 4px;">
                        <button type="button" 
                                class="btn-save-label" 
                                data-channel="${ch}"
                                style="padding: 6px 12px; background-color: #17a2b8; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 12px;">
                            Save Label
                        </button>
                    </div>
                `;
                container.appendChild(inputDiv);
            }
            
            // Attach event listeners to "Save Label" buttons
            document.querySelectorAll('.btn-save-label').forEach(btn => {
                btn.addEventListener('click', function(e) {
                    e.preventDefault();
                    const channel = this.dataset.channel;
                    const inputId = `label_${channel.substring(2)}`;
                    const label = document.getElementById(inputId).value.trim();
                    
                    if (!label) {
                        alert('Please enter a label');
                        return;
                    }
                    
                    // Send to API
                    fetch('/api/sensors/tag', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                        },
                        body: JSON.stringify({
                            channel: channel,
                            label: label
                        })
                    })
                    .then(response => response.json())
                    .then(data => {
                        if (data.success) {
                            alert(data.message);
                        } else {
                            alert('Error: ' + data.error);
                        }
                    })
                    .catch(error => {
                        console.error('Error:', error);
                        alert('Failed to save label');
                    });
                });
            });
            
            // Update labels when thermocouple count changes
            document.getElementById('num_thermocouples').addEventListener('change', function() {
                location.reload();
            });
        });
    </script>
</body>
</html>
"""

# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

def main():
    """Start Flask web server only. DAQ engine starts on-demand via /api/start (Version 2.5)."""
    logger.info("Starting Production Logger System v2.5 (Dashboard Command Center)")
    logger.info("DAQ engine will start on-demand when user clicks 'Start Logger'")
    
    # Start Flask app (DAQ will be created and started via /api/start endpoint)
    try:
        logger.info("Starting Flask web server on http://127.0.0.1:5000")
        logger.info("Access dashboard at http://127.0.0.1:5000 to start data logger")
        app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
    except KeyboardInterrupt:
        logger.info("Shutdown signal received")
    except Exception as e:
        logger.error(f"Flask server error: {e}")
    finally:
        # Cleanup: Stop DAQ if running
        if daq_control_state.is_running() and daq_control_state.daq_engine:
            logger.info("Cleaning up: Stopping DAQ engine")
            daq_control_state.daq_engine.stop()
            if daq_control_state.daq_thread:
                daq_control_state.daq_thread.join(timeout=5.0)
        logger.info("Production Logger System stopped")


if __name__ == "__main__":
    main()

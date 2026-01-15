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
        }
        
        # config_timing: Sampling and precision settings
        self.config_timing = {
            "SAMPLING_INTERVAL": 2.0,  # seconds
            "DECIMAL_PLACES": 2,
            "ENABLE_HIGH_SPEED": False,
            "CLOUD_RECONNECT_INTERVAL": 60.0
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
                print("✅ Configuration loaded from config.json")
            except Exception as e:
                print(f"⚠️ Failed to load config.json: {e}")
    
    def save_to_disk(self):
        """Save current configuration to JSON file."""
        data = {
            "config_hardware": self.config_hardware,
            "config_logging": self.config_logging,
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

# Security Configuration
ALLOWED_USERS = global_config.security["ALLOWED_USERS"]

# File paths
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
    
    def update_sensor_data(self, channel_idx: int, value: float, is_open: bool = False):
        """Update sensor data for a specific channel."""
        with self.lock:
            decimal_places = global_config.config_timing["DECIMAL_PLACES"]
            if is_open:
                self.sensor_data[f"Ch{channel_idx}"] = "Open"
            else:
                self.sensor_data[f"Ch{channel_idx}"] = round(value, decimal_places)
    
    def update_timestamp(self):
        """Update timestamp."""
        with self.lock:
            self.timestamp = datetime.now().isoformat()
    
    def get_snapshot(self) -> Dict[str, Any]:
        """Get current snapshot of all sensor data."""
        with self.lock:
            return {
                "sensors": dict(self.sensor_data),
                "timestamp": self.timestamp,
                "connection_status": self.connection_status,
                "buffer_warning": self.buffer_warning,
                "last_cloud_sync": self.last_cloud_sync,
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
        
        num_channels = global_config.config_hardware["NUM_CHANNELS"]
        row = {"timestamp": timestamp}
        for ch_idx in range(num_channels):
            if ch_idx in processed_data:
                ch_data = processed_data[ch_idx]
                if ch_data["is_open"]:
                    row[f"Ch{ch_idx}"] = "Open"
                else:
                    row[f"Ch{ch_idx}"] = ch_data["value"]
        
        self.shared_mem.add_to_csv_buffer(row)
    
    def _flush_csv_buffer(self):
        """Step 4: Attempt CSV Write (if CSV enabled). If locked, keep in buffer."""
        config_logging = global_config.get_config("config_logging")
        
        buffer = self.shared_mem.flush_csv_buffer()
        
        if not buffer or not config_logging.get("ENABLE_CSV_LOGGING"):
            return
        
        try:
            # Check if file exists
            file_exists = Path(CSV_FILE).exists()
            
            num_channels = global_config.config_hardware["NUM_CHANNELS"]
            with open(CSV_FILE, 'a', newline='', encoding='utf-8') as csvfile:
                fieldnames = ["timestamp"] + [f"Ch{i}" for i in range(num_channels)]
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                
                if not file_exists:
                    writer.writeheader()
                
                for row in buffer:
                    writer.writerow(row)
            
            logger.info(f"Wrote {len(buffer)} rows to CSV")
        
        except PermissionError:
            # File is locked, put data back in buffer
            logger.warning("CSV file locked, buffering data")
            with shared_memory.lock:
                shared_memory.csv_buffer = buffer + shared_memory.csv_buffer
        
        except Exception as e:
            logger.error(f"CSV write error: {e}")
            self.shared_mem.log_error(f"CSV write failed: {e}")
    
    def _upload_to_cloud(self):
        """Step 5: Attempt Cloud Upload (if Sheets enabled). If fail, set worksheet=None."""
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
                # Try to open existing worksheet
                spreadsheet = self.gspread_client.open("Thermocouple Logger")
                self.worksheet = spreadsheet.get_worksheet(0)
            
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
        """Main DAQ loop (7-step workflow)."""
        self.running = True
        self._open_nidaqmx_task()
        
        try:
            while self.running:
                # FIX: Check for Dynamic Reconfiguration
                if global_config.restart_required.is_set():
                    print("🔄 Configuration changed. Restarting DAQ Task...")
                    self._close_task()
                    global_config.restart_required.clear()
                    self._open_nidaqmx_task()
                    
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


@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    """Settings view for configuration updates."""
    if request.method == "POST":
        # Parse Form Data (CONFIG-01 through CONFIG-04)
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
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin-bottom: 40px;
        }
        
        .sensor-card {
            background: white;
            border-radius: 8px;
            padding: 20px;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
            transition: box-shadow 0.3s, transform 0.3s;
        }
        
        .sensor-card:hover {
            box-shadow: 0 4px 16px rgba(0, 0, 0, 0.15);
            transform: translateY(-2px);
        }
        
        .sensor-card h3 {
            font-size: 14px;
            color: #7f8c8d;
            margin-bottom: 10px;
            font-weight: 500;
            text-transform: uppercase;
        }
        
        .sensor-value {
            font-size: 36px;
            font-weight: 700;
            color: #2c3e50;
            margin-bottom: 10px;
        }
        
        .sensor-unit {
            font-size: 14px;
            color: #95a5a6;
        }
        
        .sensor-status {
            display: inline-block;
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 12px;
            font-weight: 600;
            margin-top: 10px;
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
        
        /* Footer */
        footer {
            text-align: center;
            padding: 20px;
            color: #7f8c8d;
            font-size: 12px;
            margin-top: 40px;
        }
        
        /* Responsive */
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
    
    <div class="container">
        <div class="sensor-grid" id="sensorGrid">
            <!-- Sensor cards will be inserted here by JavaScript -->
        </div>
    </div>
    
    <footer>
        <p>Data updates every 2 seconds | NI Thermocouple Logger v2.1 (Configurable)</p>
    </footer>
    
    <script>
        // FIX: Use dynamic channel count from backend
        const SENSOR_CHANNELS = {{ num_thermocouples }};
        const UPDATE_INTERVAL = 2000;  // 2 seconds
        
        function initializeSensorGrid() {
            const grid = document.getElementById('sensorGrid');
            grid.innerHTML = '';
            
            for (let i = 0; i < SENSOR_CHANNELS; i++) {
                const card = document.createElement('div');
                card.className = 'sensor-card';
                card.id = `sensor-ch${i}`;
                card.innerHTML = `
                    <h3>Channel ${i}</h3>
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
                    // Update sensor values
                    for (let i = 0; i < SENSOR_CHANNELS; i++) {
                        const chKey = `Ch${i}`;
                        const value = data.sensors[chKey];
                        const valueElem = document.getElementById(`value-ch${i}`);
                        const statusElem = document.getElementById(`status-ch${i}`);
                        
                        if (value === 'Open') {
                            valueElem.textContent = 'Open';
                            statusElem.textContent = 'Circuit Open';
                            statusElem.className = 'sensor-status open';
                        } else if (value === null || value === undefined || value === 'Error') {
                            valueElem.textContent = '--';
                            statusElem.textContent = 'Error';
                            statusElem.className = 'sensor-status error';
                        } else {
                            valueElem.textContent = typeof value === 'number' ? value.toFixed(2) : value;
                            statusElem.textContent = 'OK';
                            statusElem.className = 'sensor-status ok';
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
        }
        
        // Initialize on page load
        document.addEventListener('DOMContentLoaded', function() {
            initializeSensorGrid();
            updateDashboard();
            
            // Set up auto-refresh every 2 seconds
            setInterval(updateDashboard, UPDATE_INTERVAL);
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
                
                <!-- Buttons -->
                <div class="button-group">
                    <button type="submit" class="btn btn-success">Save & Apply</button>
                    <a href="/dashboard" class="btn btn-secondary">Back to Dashboard</a>
                </div>
            </form>
        </div>
    </div>
</body>
</html>
"""

# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

def main():
    """Start the DAQ engine and Flask app (Version 2.1)."""
    logger.info("Starting Production Logger System v2.1 (Configurable UI)")
    
    # Create and start DAQ engine in daemon thread
    daq_engine = DAQEngine(shared_memory)
    daq_thread = threading.Thread(target=daq_engine.run, daemon=True)
    daq_thread.start()
    logger.info("DAQ engine thread started")
    
    # Give DAQ time to initialize
    time.sleep(1)
    
    # Start Flask app
    try:
        logger.info("Starting Flask web server on http://127.0.0.1:5000")
        app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
    except KeyboardInterrupt:
        logger.info("Shutdown signal received")
    except Exception as e:
        logger.error(f"Flask server error: {e}")
    finally:
        daq_engine.stop()
        logger.info("Production Logger System stopped")


if __name__ == "__main__":
    main()

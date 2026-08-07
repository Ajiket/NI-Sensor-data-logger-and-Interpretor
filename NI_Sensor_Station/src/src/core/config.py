import threading
import json
import os
from typing import Dict, Any

class GlobalConfig:
    """Mutable configuration container supporting runtime updates."""
    
    def __init__(self, config_file: str = "config.json"):
        self.lock = threading.RLock()
        self.CONFIG_FILE = config_file
        self.restart_required = threading.Event()
        
        # config_hardware: Device and channel specifications
        self.config_hardware = {
            "DEVICE_NAME": "cDAQ1Mod1",
            "CHANNELS_STR": "ai0:2",
            "NUM_CHANNELS": 3,
            "TC_TYPE": "K",  # K, J, T, or E
        }
        
        # config_logging: Data persistence settings
        self.config_logging = {
            "ENABLE_CSV_LOGGING": True,
            "ENABLE_GOOGLE_SHEETS": True,
            "CSV_FOLDER": "./Data",
            "CSV_FILENAME": "thermocouple_data.csv",
            "GOOGLE_SHEETS_LINK": "",
            "TEST_SESSION_NAME": "",
        }
        
        # config_timing: Sampling and precision settings
        self.config_timing = {
            "SAMPLING_INTERVAL": 2.0,
            "DECIMAL_PLACES": 3,
            "ENABLE_HIGH_SPEED": False,
            "CLOUD_RECONNECT_INTERVAL": 60.0
        }
        
        # config_ui: UI customization
        self.config_ui = {
            "sensor_labels": {},
            "sensor_ranges": {}
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
                        self.config_ui.update(data.get("config_ui", {}))
                print(f"✅ Configuration loaded from {self.CONFIG_FILE}")
            except Exception as e:
                print(f"⚠️ Failed to load {self.CONFIG_FILE}: {e}")
        
        self._ensure_sensor_ranges()
    
    def _ensure_sensor_ranges(self):
        """Ensure sensor_ranges exists with defaults for all channels."""
        num_channels = self.config_hardware["NUM_CHANNELS"]
        if "sensor_ranges" not in self.config_ui:
            self.config_ui["sensor_ranges"] = {}
        
        for i in range(num_channels):
            ch_key = f"Ch{i}"
            if ch_key not in self.config_ui["sensor_ranges"]:
                self.config_ui["sensor_ranges"][ch_key] = {
                    "min": -50,
                    "max": 100
                }

    def save_to_disk(self):
        """Save current configuration to JSON file."""
        data = {
            "config_hardware": self.config_hardware,
            "config_logging": self.config_logging,
            "config_ui": self.config_ui,
            "config_timing": self.config_timing
        }
        try:
            # Ensure directory exists if CONFIG_FILE is in a subdir
            os.makedirs(os.path.dirname(self.CONFIG_FILE) or ".", exist_ok=True)
            with open(self.CONFIG_FILE, 'w') as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            print(f"⚠️ Failed to save config: {e}")
    
    def update_config(self, section: str, updates: Dict[str, Any]):
        """Thread-safe configuration update."""
        with self.lock:
            if section in ["config_hardware", "config_logging", "config_timing", "config_ui", "security"]:
                getattr(self, section).update(updates)
        
        self.save_to_disk()
        
        if section == "config_hardware":
            self.restart_required.set()
    
    def get_config(self, section: str) -> Dict[str, Any]:
        """Thread-safe configuration read."""
        with self.lock:
            if section in ["config_hardware", "config_logging", "config_timing", "config_ui", "security"]:
                return dict(getattr(self, section))
        return {}
    
    def get_all_config(self) -> Dict[str, Any]:
        """Get all configuration sections."""
        with self.lock:
            return {
                "config_hardware": dict(self.config_hardware),
                "config_logging": dict(self.config_logging),
                "config_ui": dict(self.config_ui),
                "config_timing": dict(self.config_timing),
                "security": dict(self.security),
            }

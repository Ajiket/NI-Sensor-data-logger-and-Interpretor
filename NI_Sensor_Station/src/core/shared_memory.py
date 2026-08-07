import threading
from datetime import datetime
from typing import List, Dict, Any, Optional

class SharedMemory:
    """Thread-safe container for shared DAQ data."""
    
    def __init__(self, num_channels: int, tc_type: str = "K"):
        self.lock = threading.RLock()
        self.reinitialize_sensors(num_channels, tc_type)
        self.timestamp = None
        self.csv_buffer = []
        self.buffer_warning = False
        self.connection_status = "Disconnected"
        self.last_cloud_sync = None
        self.error_log = []
    
    def reinitialize_sensors(self, num_channels: int, tc_type: str = "K"):
        """Reinitialize sensor data for new channel count."""
        with self.lock:
            self.sensor_data = {f"Ch{i}": None for i in range(num_channels)}
            self.sensor_labels = {f"Ch{i}": f"TC{i+1}" for i in range(num_channels)}
            self.sensor_type_map = {f"Ch{i}": tc_type for i in range(num_channels)}
            self.sensor_history = {f"Ch{i}": [] for i in range(num_channels)}
    
    def update_sensor_data(self, channel_idx: int, value: float, is_open: bool = False):
        """Update sensor data for a specific channel. Enforces 3 decimal places."""
        with self.lock:
            ch_key = f"Ch{channel_idx}"
            if is_open:
                self.sensor_data[ch_key] = "Open"
            else:
                self.sensor_data[ch_key] = round(value, 3) if value is not None else None
            
            # Add to trend history (keep last 100 entries)
            if not is_open and value is not None:
                timestamp = self.timestamp if self.timestamp else datetime.now().isoformat()
                self.sensor_history[ch_key].append({
                    "timestamp": timestamp,
                    "value": round(value, 3)
                })
                if len(self.sensor_history[ch_key]) > 100:
                    self.sensor_history[ch_key] = self.sensor_history[ch_key][-100:]
    
    def update_timestamp(self):
        """Update timestamp."""
        with self.lock:
            self.timestamp = datetime.now().isoformat()
    
    def get_snapshot(self) -> Dict[str, Any]:
        """Get current snapshot of all sensor data."""
        with self.lock:
            temp_values = [v for k, v in self.sensor_data.items() if isinstance(v, (int, float))]
            avg_temperature = sum(temp_values) / len(temp_values) if temp_values else None
            
            return {
                "sensors": dict(self.sensor_data),
                "labels": dict(self.sensor_labels),
                "timestamp": self.timestamp,
                "connection_status": self.connection_status,
                "buffer_warning": self.buffer_warning,
                "last_cloud_sync": self.last_cloud_sync,
                "avg_temperature": round(avg_temperature, 3) if avg_temperature else None,
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
            if len(self.error_log) > 50:
                self.error_log = self.error_log[-50:]
    
    def set_sensor_label(self, channel_key: str, label: str):
        """Set custom label for a sensor."""
        with self.lock:
            if channel_key in self.sensor_labels:
                self.sensor_labels[channel_key] = label
    
    def get_sensor_label(self, channel_key: str) -> str:
        """Get custom label for a sensor."""
        with self.lock:
            return self.sensor_labels.get(channel_key, f"TC{channel_key}")
    
    def get_trend_data(self, channel_key: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Get trend history for a sensor."""
        with self.lock:
            if channel_key in self.sensor_history:
                return self.sensor_history[channel_key][-limit:]
            return []

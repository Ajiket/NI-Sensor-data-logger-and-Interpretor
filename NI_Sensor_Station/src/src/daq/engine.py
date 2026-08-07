import threading
import time
import csv
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Any

try:
    import nidaqmx
    NIDAQMX_AVAILABLE = True
except ImportError:
    NIDAQMX_AVAILABLE = False

import gspread
from google.oauth2.service_account import Credentials

logger = logging.getLogger(__name__)

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
        with self.lock:
            return self.running
    
    def get_status(self) -> Dict[str, Any]:
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

class DAQEngine:
    """Data Acquisition Engine implementing 7-step workflow."""
    
    def __init__(self, shared_mem, global_config, credentials_file="credentials.json"):
        self.shared_mem = shared_mem
        self.global_config = global_config
        self.credentials_file = credentials_file
        self.task = None
        self.running = False
        self.gspread_client = None
        self.worksheet = None
        self.last_cloud_error = 0
        self.tc_type_map = {}
        self._initialize_tc_type_map()
        self._initialize_gspread()
    
    def _initialize_tc_type_map(self):
        if NIDAQMX_AVAILABLE:
            self.tc_type_map = {
                "K": nidaqmx.constants.ThermocoupleType.K,
                "J": nidaqmx.constants.ThermocoupleType.J,
                "T": nidaqmx.constants.ThermocoupleType.T,
                "E": nidaqmx.constants.ThermocoupleType.E,
            }
        else:
            self.tc_type_map = {k: k for k in ["K", "J", "T", "E"]}

    def _initialize_gspread(self):
        config_logging = self.global_config.get_config("config_logging")
        if not config_logging.get("ENABLE_GOOGLE_SHEETS"):
            return
        
        try:
            creds = Credentials.from_service_account_file(
                self.credentials_file,
                scopes=["https://www.googleapis.com/auth/spreadsheets"]
            )
            self.gspread_client = gspread.authorize(creds)
            logger.info("Google Sheets authentication successful")
        except Exception as e:
            logger.error(f"Failed to authenticate with Google Sheets: {e}")
            self.gspread_client = None
    
    def _open_nidaqmx_task(self):
        if not NIDAQMX_AVAILABLE:
            logger.warning("Hardware acquisition disabled. Demo mode.")
            return False
        
        try:
            config_hardware = self.global_config.get_config("config_hardware")
            config_timing = self.global_config.get_config("config_timing")

            self.task = nidaqmx.Task()
            tc_type = self.tc_type_map.get(config_hardware["TC_TYPE"], nidaqmx.constants.ThermocoupleType.K)

            # Robust Channel Handling: Ensure each channel has the device name prefix
            device_name = config_hardware['DEVICE_NAME']
            raw_channels = config_hardware['CHANNELS_STR'].split(',')
            formatted_channels = []
            for ch in raw_channels:
                ch = ch.strip()
                if '/' not in ch:
                    formatted_channels.append(f"{device_name}/{ch}")
                else:
                    formatted_channels.append(ch)

            channel_str = ",".join(formatted_channels)

            self.task.ai_channels.add_ai_thrmcpl_chan(
                channel_str,
                thermocouple_type=tc_type,
                units=nidaqmx.constants.TemperatureUnits.DEG_C
            )
            self.task.timing.cfg_samp_clk_timing(
                rate=1.0 / config_timing["SAMPLING_INTERVAL"],
                sample_mode=nidaqmx.constants.AcquisitionType.CONTINUOUS
            )
            
            if config_timing.get("ENABLE_HIGH_SPEED", False):
                self.task.ai_channels.all.ai_adc_timing_mode = nidaqmx.constants.ADCTimingMode.HIGH_SPEED
                
            self.task.start()
            self.shared_mem.connection_status = "Connected"
            logger.info(f"✅ DAQ Task Started: {config_hardware['NUM_CHANNELS']} channels")
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
        try:
            if self.task is None:
                num_channels = self.global_config.config_hardware["NUM_CHANNELS"]
                return [20.0 + i*5 for i in range(num_channels)]
            
            values = self.task.read()
            if not isinstance(values, list):
                values = [values]
            
            num_channels = self.global_config.config_hardware["NUM_CHANNELS"]
            while len(values) < num_channels:
                values.append(None)
            
            return values[:num_channels]
        except Exception as e:
            logger.error(f"❌ Hardware read error: {e}")
            self.shared_mem.log_error(f"Hardware read failed: {e}")
            return [None] * self.global_config.config_hardware["NUM_CHANNELS"]
    
    def _process_data(self, raw_values: List[float]) -> Dict[str, Any]:
        processed = {}
        for idx, value in enumerate(raw_values):
            if value is None:
                processed[idx] = {"value": None, "is_open": True, "label": "Error"}
            elif value > 2000:
                processed[idx] = {"value": value, "is_open": True, "label": "Open"}
            else:
                processed[idx] = {"value": value, "is_open": False, "label": "OK"}
        return processed
    
    def _push_to_csv_buffer(self, processed_data: Dict[str, Any]):
        config_logging = self.global_config.get_config("config_logging")
        if not config_logging.get("ENABLE_CSV_LOGGING"):
            return
        
        self.shared_mem.update_timestamp()
        dt = datetime.fromisoformat(self.shared_mem.timestamp)
        row = {"date": dt.strftime("%d/%m/%Y"), "time": dt.strftime("%H:%M:%S")}
        
        num_channels = self.global_config.config_hardware["NUM_CHANNELS"]
        for ch_idx in range(num_channels):
            if ch_idx in processed_data:
                ch_data = processed_data[ch_idx]
                row[f"Ch{ch_idx}"] = "Open" if ch_data["is_open"] else round(ch_data["value"], 3)
            else:
                row[f"Ch{ch_idx}"] = "Error"
        
        self.shared_mem.add_to_csv_buffer(row)
    
    def _flush_csv_buffer(self):
        config_logging = self.global_config.get_config("config_logging")
        buffer = self.shared_mem.flush_csv_buffer()
        if not buffer or not config_logging.get("ENABLE_CSV_LOGGING"):
            return
        
        try:
            csv_path = Path(config_logging.get("CSV_FOLDER", "./Data")) / config_logging.get("CSV_FILENAME", "data.csv")
            csv_path.parent.mkdir(parents=True, exist_ok=True)
            
            file_exists = csv_path.exists()
            num_channels = self.global_config.config_hardware["NUM_CHANNELS"]
            fieldnames = ["date", "time"] + [f"Ch{i}" for i in range(num_channels)]
            
            with open(csv_path, 'a', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                if not file_exists: writer.writeheader()
                writer.writerows(buffer)
            logger.info(f"Wrote {len(buffer)} rows to CSV at {csv_path}")
        except PermissionError:
            logger.warning("CSV file locked, buffering data")
            with self.shared_mem.lock:
                self.shared_mem.csv_buffer = buffer + self.shared_mem.csv_buffer
        except Exception as e:
            logger.error(f"CSV write error: {e}")
            self.shared_mem.log_error(f"CSV write failed: {e}")

    def save_test_config_file(self, user="unknown"):
        config_logging = self.global_config.get_config("config_logging")
        test_name = config_logging.get("TEST_SESSION_NAME", "").strip()
        if not test_name: return True
        
        try:
            config_file_path = Path(config_logging.get("CSV_FOLDER", "./Data")) / f"{test_name}.config"
            config_snapshot = {
                "test_metadata": {"session_name": test_name, "created_at": datetime.now().isoformat(), "created_by": user, "version": "2.6"},
                "config_hardware": self.global_config.config_hardware.copy(),
                "config_logging": self.global_config.config_logging.copy(),
                "config_timing": self.global_config.config_timing.copy(),
                "sensor_labels": self.global_config.config_ui.get("sensor_labels", {}).copy()
            }
            with open(config_file_path, 'w', encoding='utf-8') as f:
                json.dump(config_snapshot, f, indent=2, default=str)
            return True
        except Exception as e:
            logger.error(f"Failed to save test config file: {e}")
            return False

    def _upload_to_cloud(self):
        config_logging = self.global_config.get_config("config_logging")
        if not config_logging.get("ENABLE_GOOGLE_SHEETS") or not self.gspread_client:
            return
        
        retry_interval = self.global_config.config_timing.get("CLOUD_RECONNECT_INTERVAL", 60)
        if self.worksheet is None and (time.time() - self.last_cloud_error) < retry_interval:
            return
        
        try:
            if self.worksheet is None:
                link = config_logging.get("GOOGLE_SHEETS_LINK", "").strip()
                if link:
                    match = re.search(r'/spreadsheets/d/([a-zA-Z0-9-_]+)', link)
                    if match:
                        self.worksheet = self.gspread_client.open_by_key(match.group(1)).get_worksheet(0)
                if self.worksheet is None:
                    self.worksheet = self.gspread_client.open("Thermocouple Logger").get_worksheet(0)
            
            snapshot = self.shared_mem.get_snapshot()
            row = [snapshot["timestamp"]] + [snapshot["sensors"].get(f"Ch{i}", "") for i in range(self.global_config.config_hardware["NUM_CHANNELS"])]
            self.worksheet.append_row(row)
            self.shared_mem.last_cloud_sync = datetime.now().isoformat()
            self.last_cloud_error = 0
        except Exception as e:
            logger.warning(f"Cloud upload failed: {e}")
            self.worksheet = None
            self.last_cloud_error = time.time()
            self.shared_mem.log_error(f"Cloud upload failed: {e}")

    def _update_shared_memory(self, processed_data: Dict[str, Any]):
        for ch_idx, ch_data in processed_data.items():
            self.shared_mem.update_sensor_data(ch_idx, ch_data["value"], ch_data["is_open"])

    def run(self):
        self.running = True
        try:
            self._open_nidaqmx_task()
        except Exception as e:
            logger.error(f"Hardware initialization failed, falling back to simulated data: {e}")
            self.task = None # Forces hardware read to return simulated data
            
        try:
            while self.running:
                loop_start = time.time()
                processed = self._process_data(self._read_hardware())
                self._push_to_csv_buffer(processed)
                self._flush_csv_buffer()
                self._upload_to_cloud()
                self._update_shared_memory(processed)
                time.sleep(max(0, self.global_config.config_timing["SAMPLING_INTERVAL"] - (time.time() - loop_start)))
        except Exception as e:
            logger.error(f"DAQ fatal error: {e}")
            self.shared_mem.log_error(f"DAQ error: {e}")
        finally:
            self.stop()

    def stop(self):
        self.running = False
        if self.task:
            try: self.task.stop(); self.task.close()
            except: pass
        self.shared_mem.connection_status = "Disconnected"

import logging
import os
from src.core.config import GlobalConfig
from src.core.shared_memory import SharedMemory
from src.daq.engine import DAQControlState, DAQEngine
from src.web.routes import create_app

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
# INITIALIZATION
# ============================================================================

# Initialize global configuration (loads from config.json by default)
# If running in station mode, the launcher can set the CONFIG_FILE env var or path
config_path = os.environ.get("NI_LOGGER_CONFIG", "config.json")
global_config = GlobalConfig(config_file=config_path)

# Initialize shared memory with current channel count
shared_memory = SharedMemory(
    num_channels=global_config.config_hardware["NUM_CHANNELS"],
    tc_type=global_config.config_hardware.get("TC_TYPE", "K")
)

# Initialize DAQ control state
daq_control_state = DAQControlState()

# Create Flask application
app = create_app(
    shared_memory=shared_memory,
    global_config=global_config,
    daq_control_state=daq_control_state,
    daq_engine_class=DAQEngine
)

def main():
    """Start Flask web server. DAQ engine starts on-demand via UI."""
    logger.info("Starting Modular Production Logger System")
    logger.info("DAQ engine will start on-demand when user clicks 'Start Logger'")
    
    try:
        logger.info("Starting Flask web server on http://127.0.0.1:5000")
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
        logger.info("System stopped")

if __name__ == "__main__":
    main()

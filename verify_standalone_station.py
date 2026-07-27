import os
import json
import sys
import unittest
from pathlib import Path

class TestStandaloneStation(unittest.TestCase):
    def setUp(self):
        self.base_dir = Path("NI_Sensor_Station")
        self.config_dir = self.base_dir / "config"
        self.data_dir = self.base_dir / "data"
        self.logs_dir = self.base_dir / "logs"
        self.script_path = self.base_dir / "production_logger.py"

    def test_folder_structure(self):
        """Verify all essential folders and files exist."""
        self.assertTrue(self.config_dir.exists(), "Config folder missing")
        self.assertTrue(self.data_dir.exists(), "Data folder missing")
        self.assertTrue(self.logs_dir.exists(), "Logs folder missing")
        self.assertTrue(self.script_path.exists(), "Main script missing")
        self.assertTrue((self.base_dir / "SETUP_PREREQUISITES.bat").exists(), "Setup script missing")
        self.assertTrue((self.base_dir / "START_SYSTEM.bat").exists(), "Launcher script missing")

    def test_config_load(self):
        """Verify config.json is valid and loadable."""
        config_file = self.config_dir / "config.json"
        self.assertTrue(config_file.exists(), "config.json missing")
        
        with open(config_file, 'r') as f:
            data = json.load(f)
        
        self.assertIn("config_hardware", data)
        self.assertEqual(data["config_logging"]["CSV_FOLDER"], "data")

    def test_path_logic_in_script(self):
        """Verify the script contains the correct relative paths."""
        with open(self.script_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        self.assertIn('self.CONFIG_FILE = "config/config.json"', content)
        self.assertIn('CREDENTIALS_FILE = "config/credentials.json"', content)
        self.assertIn('"CSV_FOLDER": "data"', content)
        self.assertIn('logging.FileHandler(\'logs/production_logger.log\')', content)

if __name__ == "__main__":
    unittest.main()

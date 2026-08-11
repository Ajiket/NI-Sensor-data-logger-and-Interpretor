import logging
import time
from datetime import datetime
from typing import List, Dict, Any, Optional
from decouple import config

try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

logger = logging.getLogger(__name__)

class InferenceEngine:
    """Processes sensor data to generate AI-driven insights and alerts."""
    
    def __init__(self, global_config):
        self.global_config = global_config
        self.last_analysis_time = None
        self.last_gemini_call = 0
        self.gemini_interval = 60  # Call Gemini at most once per minute
        
        self.alert_thresholds = {
            "thermal_runaway_rate": 2.0,  # °C per second
            "drift_threshold": 10.0,      # °C deviation from average
        }
        
        # Initialize Gemini
        self.api_key = config('GEMINI_API_KEY', default=None)
        if GEMINI_AVAILABLE and self.api_key:
            try:
                genai.configure(api_key=self.api_key)
                self.model = genai.GenerativeModel('gemini-1.5-flash')
                logger.info("Gemini LLM initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize Gemini: {e}")
                self.model = None
        else:
            self.model = None
            if not self.api_key:
                logger.warning("GEMINI_API_KEY not found in environment. AI insights will be limited.")

    def analyze(self, shared_memory) -> List[Dict[str, Any]]:
        """Analyzes current snapshot and history to generate inferences."""
        inferences = []
        snapshot = shared_memory.get_snapshot()
        sensors = snapshot.get("sensors", {})
        avg_temp = snapshot.get("avg_temperature")
        
        # 1. Trend Direction Analysis
        trend_direction = self._calculate_overall_trend(shared_memory)
        inferences.append({
            "type": "trend",
            "label": "Overall Trend",
            "value": trend_direction,
            "severity": "info"
        })
        
        # 2. Thermal Runaway Detection (Rate of Change)
        runaway_alerts = self._detect_thermal_runaway(shared_memory)
        inferences.extend(runaway_alerts)
        
        # 3. Sensor Drift Detection
        drift_alerts = self._detect_sensor_drift(sensors, avg_temp)
        inferences.extend(drift_alerts)
        
        # 4. Gemini LLM Analysis (Throttled)
        if self.model and (time.time() - self.last_gemini_call) > self.gemini_interval:
            gemini_insight = self._call_gemini_ai(snapshot, shared_memory)
            if gemini_insight:
                inferences.append(gemini_insight)
                self.last_gemini_call = time.time()
        elif not self.model:
            # Add a fallback or status message
            pass
            
        return inferences

    def _calculate_overall_trend(self, shared_memory) -> str:
        """Calculates the overall temperature trend across all sensors."""
        all_recent_diffs = []
        for ch_key in shared_memory.sensor_history:
            history = shared_memory.get_trend_data(ch_key, limit=10)
            if len(history) >= 2:
                diff = history[-1]["value"] - history[0]["value"]
                all_recent_diffs.append(diff)
        
        if not all_recent_diffs:
            return "Stable"
            
        avg_diff = sum(all_recent_diffs) / len(all_recent_diffs)
        if avg_diff > 0.5: return "Increasing"
        if avg_diff < -0.5: return "Decreasing"
        return "Stable"

    def _detect_thermal_runaway(self, shared_memory) -> List[Dict[str, Any]]:
        alerts = []
        for ch_key in shared_memory.sensor_history:
            history = shared_memory.get_trend_data(ch_key, limit=5)
            if len(history) >= 2:
                val_diff = history[-1]["value"] - history[0]["value"]
                t_end = datetime.fromisoformat(history[-1]["timestamp"])
                t_start = datetime.fromisoformat(history[0]["timestamp"])
                time_diff = (t_end - t_start).total_seconds()
                
                if time_diff > 0:
                    rate = val_diff / time_diff
                    if rate > self.alert_thresholds["thermal_runaway_rate"]:
                        alerts.append({
                            "type": "safety",
                            "label": "Thermal Runaway",
                            "value": f"Critical rise on {ch_key} ({rate:.2f}°C/s)",
                            "severity": "critical"
                        })
        return alerts

    def _detect_sensor_drift(self, sensors, avg_temp) -> List[Dict[str, Any]]:
        alerts = []
        if avg_temp is None: return alerts
        
        for ch_key, val in sensors.items():
            if isinstance(val, (int, float)):
                deviation = abs(val - avg_temp)
                if deviation > self.alert_thresholds["drift_threshold"]:
                    alerts.append({
                        "type": "maintenance",
                        "label": "Sensor Drift",
                        "value": f"{ch_key} deviates by {deviation:.1f}°C",
                        "severity": "warning"
                    })
        return alerts

    def _call_gemini_ai(self, snapshot, shared_memory) -> Optional[Dict[str, Any]]:
        """Calls Gemini LLM for high-level interpretation of sensor data."""
        try:
            # Prepare data context for Gemini
            sensor_data = snapshot.get("sensors", {})
            avg_temp = snapshot.get("avg_temperature")
            
            history_summary = {}
            for ch in sensor_data:
                hist = shared_memory.get_trend_data(ch, limit=20)
                if hist:
                    history_summary[ch] = [h["value"] for h in hist]
            
            prompt = f"""
            You are an industrial safety AI monitoring a National Instruments thermocouple DAQ system.
            Current Average Temperature: {avg_temp}°C
            Current Sensor Values: {sensor_data}
            Recent History (last 20 samples): {history_summary}
            
            Analyze this data for any subtle anomalies, predictive maintenance needs, or safety risks.
            Respond with a single concise sentence (max 15 words) providing a 'Gemini Insight'.
            Focus on things a simple threshold check might miss.
            """
            
            response = self.model.generate_content(prompt)
            insight_text = response.text.strip()
            
            return {
                "type": "ai_insight",
                "label": "Gemini Insight",
                "value": insight_text,
                "severity": "info"
            }
        except Exception as e:
            logger.error(f"Gemini AI call failed: {e}")
            return None

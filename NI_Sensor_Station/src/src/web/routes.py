import logging
import threading
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash
from werkzeug.security import check_password_hash, generate_password_hash

logger = logging.getLogger(__name__)

def create_app(shared_memory, global_config, daq_control_state, daq_engine_class):
    app = Flask(__name__, template_folder='templates')
    app.secret_key = "production_logger_secret_key_2024"
    
    # In production, use proper authentication
    USER_PASSWORDS = {
        "admin@company.com": generate_password_hash("admin123"),
        "engineer@lab.com": generate_password_hash("engineer123"),
    }
    
    def login_required(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if "user" not in session:
                return redirect(url_for("login"))
            return f(*args, **kwargs)
        return decorated_function
    
    @app.route("/", methods=["GET"])
    def index():
        if "user" in session:
            return redirect(url_for("dashboard"))
        return redirect(url_for("login"))
    
    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            email = request.form.get("email", "").lower()
            password = request.form.get("password", "")
            if email in global_config.security["ALLOWED_USERS"] and email in USER_PASSWORDS:
                if check_password_hash(USER_PASSWORDS[email], password):
                    session["user"] = email
                    logger.info(f"User logged in: {email}")
                    return redirect(url_for("dashboard"))
            return render_template("login.html", error="Invalid credentials")
        return render_template("login.html")
    
    @app.route("/dashboard", methods=["GET"])
    @login_required
    def dashboard():
        num_channels = global_config.config_hardware["NUM_CHANNELS"]
        return render_template("dashboard.html", user=session["user"], num_thermocouples=num_channels)
    
    @app.route("/settings", methods=["GET", "POST"])
    @login_required
    def settings():
        if request.method == "POST":
            try:
                num_tc = int(request.form.get("num_thermocouples"))
                tc_type = request.form.get("tc_type")
                channels_str = request.form.get("channels_str", f"ai0:{num_tc-1}")
                sampling_freq = float(request.form.get("sampling_freq"))
                enable_csv = "enable_csv" in request.form
                enable_sheets = "enable_sheets" in request.form
                csv_folder = request.form.get("csv_folder", "./Data")
                csv_filename = request.form.get("csv_filename", "data.csv")
                sheets_link = request.form.get("google_sheets_link", "")
                test_name = request.form.get("test_name", "").strip()
                
                # Update Labels and Ranges
                labels = request.form.getlist("labels")
                min_temps = request.form.getlist("min_temps")
                max_temps = request.form.getlist("max_temps")
                
                # Step 1: Stop DAQ if running
                was_running = False
                if daq_control_state.is_running():
                    was_running = True
                    with daq_control_state.lock:
                        if daq_control_state.daq_engine:
                            daq_control_state.daq_engine.stop()
                        daq_control_state.running = False
                        if daq_control_state.daq_thread:
                            daq_control_state.daq_thread.join(timeout=3.0)
                
                # Step 2: Apply Settings
                with global_config.lock:
                    global_config.config_hardware.update({
                        "NUM_CHANNELS": num_tc, 
                        "TC_TYPE": tc_type, 
                        "CHANNELS_STR": channels_str
                    })
                    global_config.config_timing.update({"SAMPLING_INTERVAL": 1.0/sampling_freq})
                    global_config.config_logging.update({
                        "ENABLE_CSV_LOGGING": enable_csv,
                        "ENABLE_GOOGLE_SHEETS": enable_sheets,
                        "CSV_FOLDER": csv_folder,
                        "CSV_FILENAME": csv_filename,
                        "GOOGLE_SHEETS_LINK": sheets_link,
                        "TEST_SESSION_NAME": test_name
                    })
                    
                    for i in range(num_tc):
                        ch = f"Ch{i}"
                        if i < len(labels): global_config.config_ui["sensor_labels"][ch] = labels[i]
                        if i < len(min_temps) and i < len(max_temps):
                            global_config.config_ui["sensor_ranges"][ch] = {"min": float(min_temps[i]), "max": float(max_temps[i])}
                
                global_config.save_to_disk()
                shared_memory.reinitialize_sensors(num_tc, tc_type)
                
                # Save config snapshot if test name provided
                if test_name:
                    temp_engine = daq_engine_class(shared_memory, global_config)
                    temp_engine.save_test_config_file(user=session["user"])
                
                # Step 3: Auto-restart DAQ if it was running
                if was_running:
                    with daq_control_state.lock:
                        daq_control_state.daq_engine = daq_engine_class(shared_memory, global_config)
                        daq_control_state.daq_thread = threading.Thread(target=daq_control_state.daq_engine.run)
                        daq_control_state.daq_thread.start()
                        daq_control_state.running = True
                        daq_control_state.start_time = datetime.now().isoformat()
                
                flash("Settings Saved Successfully", "success")
                return redirect(url_for("dashboard"))
            except Exception as e:
                logger.error(f"Settings error: {e}")
                flash(f"Error: {e}", "error")
        
        config = global_config.get_all_config()
        return render_template("settings.html", 
                             user=session["user"],
                             config_hardware=config["config_hardware"],
                             num_thermocouples=config["config_hardware"]["NUM_CHANNELS"],
                             tc_type=config["config_hardware"]["TC_TYPE"],
                             sampling_freq=1.0/config["config_timing"]["SAMPLING_INTERVAL"],
                             enable_csv=config["config_logging"]["ENABLE_CSV_LOGGING"],
                             enable_sheets=config["config_logging"]["ENABLE_GOOGLE_SHEETS"],
                             csv_folder=config["config_logging"].get("CSV_FOLDER", "./Data"),
                             csv_filename=config["config_logging"].get("CSV_FILENAME", "data.csv"),
                             google_sheets_link=config["config_logging"].get("GOOGLE_SHEETS_LINK", ""),
                             test_session_name=config["config_logging"].get("TEST_SESSION_NAME", ""),
                             daq_running=daq_control_state.is_running())

    @app.route("/logout")
    def logout():
        session.pop("user", None)
        return redirect(url_for("login"))

    @app.route("/api/data")
    @login_required
    def api_data():
        return jsonify(shared_memory.get_snapshot())

    @app.route("/api/status")
    @login_required
    def api_status():
        return jsonify(daq_control_state.get_status())

    @app.route("/api/ranges")
    @login_required
    def api_ranges():
        return jsonify({
            "sensor_labels": global_config.config_ui.get("sensor_labels", {}),
            "sensor_ranges": global_config.config_ui.get("sensor_ranges", {})
        })

    @app.route("/api/trends/<channel>")
    @login_required
    def api_trends(channel):
        ch_key = f"Ch{channel}" if not channel.startswith("Ch") else channel
        return jsonify({
            "channel": ch_key,
            "label": shared_memory.get_sensor_label(ch_key),
            "data": shared_memory.get_trend_data(ch_key)
        })

    @app.route("/api/hardware/detect")
    @login_required
    def api_detect_hardware():
        """Robustly detect all connected NI Thermocouple modules and channels."""
        try:
            import nidaqmx
            from nidaqmx.system import System
            system = nidaqmx.system.System.local()
            devices = []
            for device in system.devices:
                # Check for Thermocouple capability (AI channels)
                ai_channels = [ch.name for ch in device.ai_physical_chans]
                devices.append({
                    "name": device.name,
                    "product_type": device.product_type,
                    "ai_channels": ai_channels
                })
            return jsonify({"status": "success", "devices": devices})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    @app.route("/api/start", methods=["POST"])
    @login_required
    def api_start():
        if daq_control_state.is_running():
            return jsonify({"error": "Already running"}), 409
        
        with daq_control_state.lock:
            daq_control_state.daq_engine = daq_engine_class(shared_memory, global_config)
            daq_control_state.daq_thread = threading.Thread(target=daq_control_state.daq_engine.run)
            daq_control_state.daq_thread.start()
            daq_control_state.running = True
            daq_control_state.start_time = datetime.now().isoformat()
        return jsonify({"status": "started"})

    @app.route("/api/stop", methods=["POST"])
    @login_required
    def api_stop():
        if not daq_control_state.is_running():
            return jsonify({"error": "Not running"}), 409
        
        with daq_control_state.lock:
            if daq_control_state.daq_engine:
                daq_control_state.daq_engine.stop()
            daq_control_state.running = False
        return jsonify({"status": "stopped"})

    return app

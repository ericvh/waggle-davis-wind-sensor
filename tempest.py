#!/usr/bin/env python3
"""
Tempest Weather Station UDP Receiver with Davis Wind Sensor Calibration

This utility receives UDP broadcasts from a local Tempest weather station
and provides calibration capabilities for Davis wind sensors.

Usage:
    python3 tempest.py                    # Start web server with UDP listener
    python3 tempest.py --calibrate        # Interactive calibration mode
"""

import socket
import json
import threading
import argparse
import math
import subprocess
import sys
import platform
import signal
import atexit
import serial
import re
from time import time
from datetime import datetime, timedelta
from flask import Flask, jsonify, request

UDP_PORT = 50222

# Store the latest packet per message type
latest_raw_by_type = {}
latest_parsed_by_type = {}
lock = threading.Lock()

# Calibration data storage
calibration_readings = {
    'davis': [],
    'tempest': [],
    'timestamps': []
}
calibration_lock = threading.Lock()

app = Flask(__name__)

# ---------------- Converters ----------------
def c_to_f(c): return None if c is None else (c * 9/5) + 32
def mps_to_kt(m): return None if m is None else m * 1.943844
def hpa_to_inhg(h): return None if h is None else h * 0.0295299830714
def mm_to_in(mm): return None if mm is None else mm / 25.4

PRECIP_TYPES = {
    0: "none",
    1: "rain",
    2: "hail",
    3: "snow",
}

# ------------- Parsers for message types -------------
def parse_obs_st(msg):
    """
    Parses 'obs_st' (Tempest device) to a readable structure.
    Leaves nothing out, just presents common units alongside raw values.
    """
    obs = msg.get("obs", [[]])[0] if msg.get("obs") else []
    if not obs:
        return {"type": "obs_st", "error": "empty obs"}

    # Indexes per Tempest docs (kept here for clarity)
    # 0 time_epoch, 1 lull m/s, 2 avg m/s, 3 gust m/s, 4 dir deg, 5 sample s,
    # 6 pressure hPa, 7 temp C, 8 RH %, 9 lux, 10 UV, 11 solar W/m^2,
    # 12 rain mm, 13 precip type, 14 lightning dist km, 15 lightning count,
    # 16 battery V, 17 report interval min, 18 local day rain mm,
    # (19–21 may exist for nc rain analysis on newer payloads)
    d = {
        "timestamp": obs[0],
        "wind": {
            "lull_mps": obs[1], "lull_kt": mps_to_kt(obs[1]),
            "avg_mps": obs[2],  "avg_kt": mps_to_kt(obs[2]),
            "gust_mps": obs[3], "gust_kt": mps_to_kt(obs[3]),
            "direction_deg": obs[4],
            "sample_interval_s": obs[5],
        },
        "pressure": {
            "hpa": obs[6],
            "inHg": hpa_to_inhg(obs[6]),
        },
        "temperature": {
            "c": obs[7],
            "f": c_to_f(obs[7]),
        },
        "humidity_percent": obs[8],
        "light": {
            "illuminance_lux": obs[9],
            "uv_index": obs[10],
            "solar_radiation_wm2": obs[11],
        },
        "rain": {
            "since_report_mm": obs[12],
            "since_report_in": mm_to_in(obs[12]),
            "precipitation_type": PRECIP_TYPES.get(obs[13], "unknown"),
            "local_day_mm": obs[18] if len(obs) > 18 else None,
            "local_day_in": mm_to_in(obs[18]) if len(obs) > 18 else None,
        },
        "lightning": {
            "avg_distance_km": obs[14],
            "strike_count": obs[15],
        },
        "battery_v": obs[16],
        "report_interval_min": obs[17],
        "meta": {
            "device_sn": msg.get("serial_number"),
            "hub_sn": msg.get("hub_sn"),
            "received_at": int(time()),
        },
    }
    return d

def parse_rapid_wind(msg):
    """Parses 'rapid_wind' to show instant wind in m/s + knots."""
    ob = msg.get("ob", [])
    if len(ob) < 3:
        return {"type": "rapid_wind", "error": "bad ob"}
    return {
        "timestamp": ob[0],
        "wind": {
            "instant_mps": ob[1],
            "instant_kt": mps_to_kt(ob[1]),
            "direction_deg": ob[2],
        },
        "meta": {
            "device_sn": msg.get("serial_number"),
            "hub_sn": msg.get("hub_sn"),
            "received_at": int(time()),
        },
    }

def parse_hub_status(msg):
    """Parses 'hub_status' for quick readability."""
    return {
        "firmware": msg.get("firmware_revision"),
        "uptime_s": msg.get("uptime"),
        "rssi": msg.get("rssi"),
        "timestamp": msg.get("time"),
        "meta": {
            "hub_sn": msg.get("serial_number"),
            "received_at": int(time()),
        },
    }

# More parsers can be added as you encounter new types:
# def parse_device_status(msg): ...
# def parse_evt_precip(msg): ...
# def parse_evt_strike(msg): ...
# etc.

PARSERS = {
    "obs_st": parse_obs_st,
    "rapid_wind": parse_rapid_wind,
    "hub_status": parse_hub_status,
}

# ---------------- Firewall Management ----------------
class FirewallManager:
    """Manages iptables rules for UDP broadcast reception"""
    
    def __init__(self, port=UDP_PORT):
        self.port = port
        self.rule_added = False
        self.is_linux = platform.system().lower() == 'linux'
        self.rule_comment = f"tempest-calibration-{port}"
        self.skip_setup = False
        
        # Register cleanup on exit
        atexit.register(self.cleanup)
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """Handle interrupt signals to ensure cleanup"""
        print(f"\nReceived signal {signum}, cleaning up firewall rules...")
        self.cleanup()
        sys.exit(0)
    
    def _run_command(self, cmd, check_output=False):
        """Run a shell command with error handling"""
        try:
            if check_output:
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
                return result.returncode == 0, result.stdout.strip(), result.stderr.strip()
            else:
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
                return result.returncode == 0, "", result.stderr.strip()
        except subprocess.TimeoutExpired:
            return False, "", "Command timed out"
        except Exception as e:
            return False, "", str(e)
    
    def _check_root_or_sudo(self):
        """Check if we're running as root or have sudo privileges"""
        import os
        
        # Check if running as root
        if os.geteuid() == 0:
            return True, True  # (has_privileges, is_root)
        
        # Not root, check sudo
        success, _, _ = self._run_command("sudo -n true")
        return success, False  # (has_privileges, is_root)
    
    def _rule_exists(self):
        """Check if our iptables rule already exists"""
        if not self.is_linux:
            return False
        
        # Check if we're root or need sudo
        has_privileges, is_root = self._check_root_or_sudo()
        if not has_privileges:
            return False
        
        sudo_prefix = "" if is_root else "sudo "
        cmd = f"{sudo_prefix}iptables -C INPUT -p udp --dport {self.port} -j ACCEPT -m comment --comment {self.rule_comment} 2>/dev/null"
        success, _, _ = self._run_command(cmd)
        return success
    
    def add_rule(self):
        """Add iptables rule to allow UDP broadcasts"""
        if not self.is_linux:
            print("Firewall management only supported on Linux systems")
            return True
        
        if self._rule_exists():
            print(f"Firewall rule for UDP port {self.port} already exists")
            return True
        
        # Check privileges and determine command prefix
        has_privileges, is_root = self._check_root_or_sudo()
        if not has_privileges:
            print("Warning: No root/sudo privileges. You may need to manually allow UDP port 50222:")
            print(f"iptables -I INPUT -p udp --dport {self.port} -j ACCEPT")
            return False
        
        sudo_prefix = "" if is_root else "sudo "
        privilege_type = "root" if is_root else "sudo"
        
        print(f"Adding iptables rule to allow UDP broadcasts on port {self.port} (using {privilege_type})...")
        cmd = f"{sudo_prefix}iptables -I INPUT -p udp --dport {self.port} -j ACCEPT -m comment --comment {self.rule_comment}"
        success, _, error = self._run_command(cmd)
        
        if success:
            self.rule_added = True
            print(f"✓ Firewall rule added successfully")
            return True
        else:
            print(f"✗ Failed to add firewall rule: {error}")
            print(f"Manual command: sudo iptables -I INPUT -p udp --dport {self.port} -j ACCEPT")
            return False
    
    def remove_rule(self):
        """Remove the iptables rule we added"""
        if not self.is_linux or not self.rule_added:
            return True
        
        if not self._rule_exists():
            print(f"Firewall rule for UDP port {self.port} not found")
            self.rule_added = False
            return True
        
        # Check privileges and determine command prefix
        has_privileges, is_root = self._check_root_or_sudo()
        if not has_privileges:
            print(f"Warning: No root/sudo privileges to remove firewall rule")
            return False
        
        sudo_prefix = "" if is_root else "sudo "
        privilege_type = "root" if is_root else "sudo"
        
        print(f"Removing iptables rule for UDP port {self.port} (using {privilege_type})...")
        cmd = f"{sudo_prefix}iptables -D INPUT -p udp --dport {self.port} -j ACCEPT -m comment --comment {self.rule_comment}"
        success, _, error = self._run_command(cmd)
        
        if success:
            self.rule_added = False
            print(f"✓ Firewall rule removed successfully")
            return True
        else:
            print(f"✗ Failed to remove firewall rule: {error}")
            manual_cmd = f"iptables -D INPUT -p udp --dport {self.port} -j ACCEPT"
            print(f"Manual cleanup: {manual_cmd}")
            return False
    
    def cleanup(self):
        """Clean up firewall rules on exit"""
        if self.rule_added:
            self.remove_rule()
    
    def check_port_status(self):
        """Check if the UDP port is accessible"""
        print(f"Checking UDP port {self.port} accessibility...")
        
        # Try to bind to the port to see if it's available
        try:
            test_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            test_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            test_sock.bind(("0.0.0.0", self.port))
            test_sock.close()
            print(f"✓ UDP port {self.port} is accessible")
            return True
        except Exception as e:
            print(f"✗ UDP port {self.port} binding failed: {e}")
            return False
    
    def setup_firewall(self):
        """Setup firewall rules and check port accessibility"""
        print("Setting up firewall for Tempest UDP broadcasts...")
        
        # Check if we're on Linux
        if not self.is_linux:
            print(f"Running on {platform.system()}, skipping iptables configuration")
            return self.check_port_status()
        
        # Check current firewall status
        if self._rule_exists():
            print(f"✓ Firewall rule for UDP port {self.port} already exists")
        else:
            # Try to add the rule
            if not self.add_rule():
                print("⚠️  Could not configure firewall automatically")
                print("If you experience connectivity issues, manually run:")
                print(f"iptables -I INPUT -p udp --dport {self.port} -j ACCEPT")
        
        # Test port accessibility
        return self.check_port_status()

# Create global firewall manager instance
firewall_manager = FirewallManager()

# ---------------- Calibration Functions ----------------
def get_current_tempest_wind():
    """Get current wind data from latest Tempest readings"""
    with lock:
        # Try rapid_wind first (most recent), fallback to obs_st
        if "rapid_wind" in latest_parsed_by_type:
            data = latest_parsed_by_type["rapid_wind"]["data"]
            if "error" not in data:
                return {
                    'wind_speed_knots': data["wind"]["instant_kt"],
                    'wind_direction_deg': data["wind"]["direction_deg"],
                    'timestamp': data["timestamp"],
                    'source': 'rapid_wind'
                }
        
        if "obs_st" in latest_parsed_by_type:
            data = latest_parsed_by_type["obs_st"]["data"]
            if "error" not in data:
                return {
                    'wind_speed_knots': data["wind"]["avg_kt"],
                    'wind_direction_deg': data["wind"]["direction_deg"],
                    'timestamp': data["timestamp"],
                    'source': 'obs_st'
                }
    
    return None

def calculate_calibration_factors(davis_readings, tempest_readings):
    """Calculate calibration factors based on paired readings"""
    if not davis_readings or not tempest_readings or len(davis_readings) != len(tempest_readings):
        return None
    
    speed_ratios = []
    direction_diffs = []
    
    for davis, tempest in zip(davis_readings, tempest_readings):
        # Speed calibration (only use non-zero wind speeds)
        if davis['wind_speed_knots'] > 0.1 and tempest['wind_speed_knots'] > 0.1:
            ratio = tempest['wind_speed_knots'] / davis['wind_speed_knots']
            speed_ratios.append(ratio)
        
        # Direction offset calculation (handle wrap-around)
        davis_dir = davis['wind_direction_deg']
        tempest_dir = tempest['wind_direction_deg']
        
        diff = tempest_dir - davis_dir
        if diff > 180:
            diff -= 360
        elif diff < -180:
            diff += 360
        direction_diffs.append(diff)
    
    if not speed_ratios:
        return None
    
    # Calculate averages
    avg_speed_ratio = sum(speed_ratios) / len(speed_ratios)
    avg_direction_offset = sum(direction_diffs) / len(direction_diffs)
    
    # Calculate confidence (inverse of standard deviation)
    if len(speed_ratios) > 1:
        speed_std = (sum((r - avg_speed_ratio) ** 2 for r in speed_ratios) / len(speed_ratios)) ** 0.5
        speed_confidence = 1.0 / (1.0 + speed_std)
    else:
        speed_confidence = 0.5
    
    if len(direction_diffs) > 1:
        dir_std = (sum((d - avg_direction_offset) ** 2 for d in direction_diffs) / len(direction_diffs)) ** 0.5
        dir_confidence = 1.0 / (1.0 + dir_std / 10.0)
    else:
        dir_confidence = 0.5
    
    return {
        'speed_calibration_factor': avg_speed_ratio,
        'direction_offset': avg_direction_offset,
        'speed_confidence': speed_confidence,
        'direction_confidence': dir_confidence,
        'sample_count': len(speed_ratios),
        'speed_ratios': speed_ratios,
        'direction_diffs': direction_diffs
    }

# ---------------- UDP listener ----------------
def udp_listener():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", UDP_PORT))
    print(f"Listening for TempestWX broadcasts on UDP {UDP_PORT}...")

    while True:
        data, addr = sock.recvfrom(65535)
        try:
            msg = json.loads(data.decode("utf-8"))
        except Exception:
            # Skip non-JSON packets
            continue

        msg_type = msg.get("type", "unknown")

        # Always store the raw message by type
        with lock:
            latest_raw_by_type[msg_type] = msg

            # If we have a parser for this type, also store parsed
            parser = PARSERS.get(msg_type)
            if parser:
                latest_parsed_by_type[msg_type] = {
                    "type": msg_type,
                    "data": parser(msg)
                }
            else:
                # If no parser, remove any stale parsed entry to avoid confusion
                if msg_type in latest_parsed_by_type:
                    del latest_parsed_by_type[msg_type]

# ---------------- HTTP endpoints ----------------
@app.route("/weather")
def weather_all():
    """Full view: for every seen message type, return raw and parsed (if available)."""
    with lock:
        if not latest_raw_by_type:
            return jsonify({"error": "No data received yet"}), 503

        bundle = {}
        for msg_type, raw in latest_raw_by_type.items():
            entry = {"raw": raw}
            parsed_entry = latest_parsed_by_type.get(msg_type)
            if parsed_entry:
                entry["parsed"] = parsed_entry["data"]
            bundle[msg_type] = entry

        return jsonify({
            "updated_at": int(time()),
            "types": bundle
        })

@app.route("/weather/raw")
def weather_raw():
    with lock:
        if not latest_raw_by_type:
            return jsonify({"error": "No data received yet"}), 503
        return jsonify({
            "updated_at": int(time()),
            "types": latest_raw_by_type
        })

@app.route("/weather/parsed")
def weather_parsed():
    with lock:
        if not latest_parsed_by_type:
            # Still return an empty map (maybe you've only received unknown types)
            return jsonify({
                "updated_at": int(time()),
                "types": {}
            })
        # Flatten to {type: parsed_data}
        flattened = {
            t: v["data"] for t, v in latest_parsed_by_type.items()
        }
        return jsonify({
            "updated_at": int(time()),
            "types": flattened
        })

# ---------------- Calibration HTTP endpoints ----------------
@app.route("/calibration/current-wind")
def current_wind():
    """Get current wind data from Tempest for calibration comparison"""
    tempest_wind = get_current_tempest_wind()
    if tempest_wind:
        return jsonify({
            "success": True,
            "tempest_wind": tempest_wind,
            "timestamp": int(time())
        })
    else:
        return jsonify({
            "success": False,
            "error": "No current wind data available",
            "timestamp": int(time())
        }), 503

@app.route("/calibration/add-reading", methods=["POST"])
def add_calibration_reading():
    """Add a Davis reading paired with current Tempest data"""
    try:
        data = request.get_json()
        davis_speed = float(data.get('wind_speed_knots', 0))
        davis_direction = float(data.get('wind_direction_deg', 0))
        
        # Get current Tempest data
        tempest_wind = get_current_tempest_wind()
        if not tempest_wind:
            return jsonify({
                "success": False,
                "error": "No current Tempest data available"
            }), 503
        
        # Store the reading pair
        with calibration_lock:
            calibration_readings['davis'].append({
                'wind_speed_knots': davis_speed,
                'wind_direction_deg': davis_direction
            })
            calibration_readings['tempest'].append(tempest_wind)
            calibration_readings['timestamps'].append(datetime.now().isoformat())
        
        return jsonify({
            "success": True,
            "davis_reading": {
                'wind_speed_knots': davis_speed,
                'wind_direction_deg': davis_direction
            },
            "tempest_reading": tempest_wind,
            "total_readings": len(calibration_readings['davis'])
        })
        
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 400

@app.route("/calibration/readings")
def get_calibration_readings():
    """Get all calibration readings"""
    with calibration_lock:
        return jsonify({
            "success": True,
            "reading_count": len(calibration_readings['davis']),
            "readings": {
                "davis": calibration_readings['davis'],
                "tempest": calibration_readings['tempest'],
                "timestamps": calibration_readings['timestamps']
            }
        })

@app.route("/calibration/calculate")
def calculate_calibration():
    """Calculate calibration factors from all collected readings"""
    with calibration_lock:
        if len(calibration_readings['davis']) < 2:
            return jsonify({
                "success": False,
                "error": "Need at least 2 readings for calibration"
            }), 400
        
        calibration = calculate_calibration_factors(
            calibration_readings['davis'], 
            calibration_readings['tempest']
        )
        
        if not calibration:
            return jsonify({
                "success": False,
                "error": "Could not calculate calibration factors"
            }), 400
        
        return jsonify({
            "success": True,
            "calibration": calibration,
            "command_line": f"python3 main.py --calibration-factor {calibration['speed_calibration_factor']:.4f} --direction-offset {calibration['direction_offset']:.2f}",
            "reading_count": len(calibration_readings['davis'])
        })

@app.route("/calibration/clear", methods=["POST"])
def clear_calibration_readings():
    """Clear all calibration readings"""
    with calibration_lock:
        calibration_readings['davis'].clear()
        calibration_readings['tempest'].clear()
        calibration_readings['timestamps'].clear()
    
    return jsonify({
        "success": True,
        "message": "All calibration readings cleared"
    })

@app.route("/calibration/firewall-status")
def firewall_status():
    """Get current firewall status"""
    return jsonify({
        "success": True,
        "firewall": {
            "platform": platform.system(),
            "is_linux": firewall_manager.is_linux,
            "rule_added": firewall_manager.rule_added,
            "rule_exists": firewall_manager._rule_exists() if firewall_manager.is_linux else False,
            "port": firewall_manager.port,
            "sudo_available": firewall_manager._check_sudo() if firewall_manager.is_linux else False
        }
    })

@app.route("/calibration/setup-firewall", methods=["POST"])  
def setup_firewall_endpoint():
    """Setup firewall rules via web interface"""
    success = firewall_manager.setup_firewall()
    
    return jsonify({
        "success": success,
        "message": "Firewall setup completed" if success else "Firewall setup had issues",
        "firewall": {
            "rule_added": firewall_manager.rule_added,
            "rule_exists": firewall_manager._rule_exists() if firewall_manager.is_linux else False
        }
    })

@app.route("/calibration")
def calibration_dashboard():
    """Simple HTML dashboard for calibration"""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Davis Wind Sensor Calibration</title>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body { font-family: Arial, sans-serif; margin: 20px; }
            .container { max-width: 800px; margin: 0 auto; }
            .section { margin: 20px 0; padding: 15px; border: 1px solid #ddd; border-radius: 5px; }
            .current-data { background: #f0f8ff; }
            .calibration-form { background: #f8f8f0; }
            .results { background: #f0f8f0; }
            input, button { padding: 8px; margin: 5px; }
            button { background: #007cba; color: white; border: none; border-radius: 3px; cursor: pointer; }
            button:hover { background: #005a87; }
            .error { color: red; }
            .success { color: green; }
            table { width: 100%; border-collapse: collapse; }
            th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
            th { background-color: #f2f2f2; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Davis Wind Sensor Calibration</h1>
            
            <div class="section current-data">
                <h2>Current Tempest Data</h2>
                <div id="tempest-data">Loading...</div>
                <button onclick="refreshTempest()">Refresh</button>
                
                <h3>Network Status</h3>
                <div id="firewall-status">Checking firewall...</div>
                <button onclick="setupFirewall()">Setup Firewall</button>
            </div>
            
            <div class="section calibration-form">
                <h2>Add Davis Reading</h2>
                <p>Enter your Davis sensor reading to compare with current Tempest data:</p>
                <form id="davis-form">
                    <label>Wind Speed (knots): <input type="number" step="0.1" id="davis-speed" required></label><br>
                    <label>Wind Direction (degrees): <input type="number" step="1" id="davis-direction" min="0" max="360" required></label><br>
                    <button type="submit">Add Reading</button>
                </form>
                <div id="add-result"></div>
            </div>
            
            <div class="section results">
                <h2>Calibration Results</h2>
                <div id="readings-count">No readings yet</div>
                <button onclick="calculateCalibration()">Calculate Calibration</button>
                <button onclick="clearReadings()">Clear All Readings</button>
                <div id="calibration-results"></div>
            </div>
            
            <div class="section">
                <h2>Reading History</h2>
                <div id="reading-history"></div>
            </div>
        </div>
        
        <script>
            function refreshTempest() {
                fetch('/calibration/current-wind')
                    .then(response => response.json())
                    .then(data => {
                        if (data.success) {
                            const wind = data.tempest_wind;
                            document.getElementById('tempest-data').innerHTML = 
                                `Speed: ${wind.wind_speed_knots.toFixed(1)} knots, Direction: ${wind.wind_direction_deg.toFixed(0)}° (Source: ${wind.source})`;
                        } else {
                            document.getElementById('tempest-data').innerHTML = 
                                `<span class="error">Error: ${data.error}</span>`;
                        }
                    })
                    .catch(error => {
                        document.getElementById('tempest-data').innerHTML = 
                            `<span class="error">Error: ${error}</span>`;
                    });
            }
            
            document.getElementById('davis-form').addEventListener('submit', function(e) {
                e.preventDefault();
                const speed = document.getElementById('davis-speed').value;
                const direction = document.getElementById('davis-direction').value;
                
                fetch('/calibration/add-reading', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        wind_speed_knots: parseFloat(speed),
                        wind_direction_deg: parseFloat(direction)
                    })
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        document.getElementById('add-result').innerHTML = 
                            `<span class="success">Reading added! Total: ${data.total_readings}</span>`;
                        document.getElementById('davis-speed').value = '';
                        document.getElementById('davis-direction').value = '';
                        updateReadingsCount();
                        loadReadingHistory();
                    } else {
                        document.getElementById('add-result').innerHTML = 
                            `<span class="error">Error: ${data.error}</span>`;
                    }
                });
            });
            
            function calculateCalibration() {
                fetch('/calibration/calculate')
                    .then(response => response.json())
                    .then(data => {
                        if (data.success) {
                            const cal = data.calibration;
                            document.getElementById('calibration-results').innerHTML = 
                                `<h3>Calibration Results (${data.reading_count} readings)</h3>
                                <p><strong>Speed calibration factor:</strong> ${cal.speed_calibration_factor.toFixed(4)}</p>
                                <p><strong>Direction offset:</strong> ${cal.direction_offset.toFixed(2)}°</p>
                                <p><strong>Speed confidence:</strong> ${cal.speed_confidence.toFixed(3)}</p>
                                <p><strong>Direction confidence:</strong> ${cal.direction_confidence.toFixed(3)}</p>
                                <p><strong>Command line:</strong></p>
                                <pre>${data.command_line}</pre>`;
                        } else {
                            document.getElementById('calibration-results').innerHTML = 
                                `<span class="error">Error: ${data.error}</span>`;
                        }
                    });
            }
            
            function clearReadings() {
                if (confirm('Clear all calibration readings?')) {
                    fetch('/calibration/clear', {method: 'POST'})
                        .then(response => response.json())
                        .then(data => {
                            if (data.success) {
                                updateReadingsCount();
                                loadReadingHistory();
                                document.getElementById('calibration-results').innerHTML = '';
                                document.getElementById('add-result').innerHTML = 
                                    `<span class="success">${data.message}</span>`;
                            }
                        });
                }
            }
            
            function updateReadingsCount() {
                fetch('/calibration/readings')
                    .then(response => response.json())
                    .then(data => {
                        if (data.success) {
                            document.getElementById('readings-count').innerHTML = 
                                `${data.reading_count} readings collected`;
                        }
                    });
            }
            
            function loadReadingHistory() {
                fetch('/calibration/readings')
                    .then(response => response.json())
                    .then(data => {
                        if (data.success && data.reading_count > 0) {
                            let html = '<table><tr><th>Time</th><th>Davis Speed</th><th>Davis Dir</th><th>Tempest Speed</th><th>Tempest Dir</th></tr>';
                            for (let i = 0; i < data.reading_count; i++) {
                                const timestamp = new Date(data.readings.timestamps[i]).toLocaleTimeString();
                                const davis = data.readings.davis[i];
                                const tempest = data.readings.tempest[i];
                                html += `<tr>
                                    <td>${timestamp}</td>
                                    <td>${davis.wind_speed_knots.toFixed(1)} kt</td>
                                    <td>${davis.wind_direction_deg.toFixed(0)}°</td>
                                    <td>${tempest.wind_speed_knots.toFixed(1)} kt</td>
                                    <td>${tempest.wind_direction_deg.toFixed(0)}°</td>
                                </tr>`;
                            }
                            html += '</table>';
                            document.getElementById('reading-history').innerHTML = html;
                        } else {
                            document.getElementById('reading-history').innerHTML = 'No readings yet';
                        }
                    });
            }
            
            function checkFirewallStatus() {
                fetch('/calibration/firewall-status')
                    .then(response => response.json())
                    .then(data => {
                        if (data.success) {
                            const fw = data.firewall;
                            let statusHtml = `Platform: ${fw.platform}<br>`;
                            
                            if (fw.is_linux) {
                                statusHtml += `Firewall rule: ${fw.rule_exists ? '✓ Active' : '✗ Not found'}<br>`;
                                statusHtml += `Auto-managed: ${fw.rule_added ? '✓ Yes' : '○ No'}<br>`;
                                statusHtml += `Sudo access: ${fw.sudo_available ? '✓ Available' : '✗ Limited'}`;
                            } else {
                                statusHtml += `Firewall: Not managed on ${fw.platform}`;
                            }
                            
                            document.getElementById('firewall-status').innerHTML = statusHtml;
                        } else {
                            document.getElementById('firewall-status').innerHTML = 
                                '<span class="error">Error checking firewall status</span>';
                        }
                    })
                    .catch(error => {
                        document.getElementById('firewall-status').innerHTML = 
                            `<span class="error">Error: ${error}</span>`;
                    });
            }
            
            function setupFirewall() {
                document.getElementById('firewall-status').innerHTML = 'Setting up firewall...';
                
                fetch('/calibration/setup-firewall', {method: 'POST'})
                    .then(response => response.json())
                    .then(data => {
                        if (data.success) {
                            document.getElementById('firewall-status').innerHTML = 
                                `<span class="success">${data.message}</span>`;
                            setTimeout(checkFirewallStatus, 1000); // Refresh status after setup
                        } else {
                            document.getElementById('firewall-status').innerHTML = 
                                `<span class="error">Setup failed: ${data.message}</span>`;
                        }
                    })
                    .catch(error => {
                        document.getElementById('firewall-status').innerHTML = 
                            `<span class="error">Error: ${error}</span>`;
                    });
            }
            
            // Initial load
            refreshTempest();
            updateReadingsCount();
            loadReadingHistory();
            checkFirewallStatus();
            
            // Auto-refresh Tempest data every 10 seconds
            setInterval(refreshTempest, 10000);
            // Check firewall status every 30 seconds
            setInterval(checkFirewallStatus, 30000);
        </script>
    </body>
    </html>
    """

# ---------------- Interactive Calibration Mode ----------------
def interactive_calibration():
    """Interactive console-based calibration mode"""
    print("Davis Wind Sensor Calibration using Local Tempest Station")
    print("=" * 60)
    print("Setting up network access for Tempest UDP broadcasts...")
    print()
    
    # Setup firewall rules for UDP reception
    if not firewall_manager.skip_setup:
        if not firewall_manager.setup_firewall():
            print("⚠️  Warning: Network setup may be incomplete")
            print("If you don't receive Tempest data, check your firewall settings")
            print()
    else:
        print("Firewall setup skipped")
        print()
    
    print("Make sure your Tempest station is broadcasting on UDP port 50222")
    print("Enter 'quit' to exit")
    print()
    
    readings_davis = []
    readings_tempest = []
    
    # Start UDP listener in background
    udp_thread = threading.Thread(target=udp_listener, daemon=True)
    udp_thread.start()
    
    # Wait a moment for initial data
    import time
    time.sleep(3)  # Give a bit more time for firewall setup and data reception
    
    while True:
        try:
            # Get current Tempest data
            tempest_wind = get_current_tempest_wind()
            if not tempest_wind:
                print("⚠️  No current Tempest data available. Waiting...")
                time.sleep(1)
                continue
            
            print(f"Current Tempest: {tempest_wind['wind_speed_knots']:.1f} knots, {tempest_wind['wind_direction_deg']:.0f}° ({tempest_wind['source']})")
            
            # Get Davis reading from user
            user_input = input("Enter Davis reading (speed,direction) or 'quit': ").strip()
            
            if user_input.lower() in ['quit', 'exit', 'q']:
                break
            
            if ',' not in user_input:
                print("Invalid format. Use: speed,direction (e.g., 8.5,145)")
                continue
            
            speed_str, direction_str = user_input.split(',')
            davis_speed = float(speed_str.strip())
            davis_direction = float(direction_str.strip())
            
            # Store readings
            davis_reading = {
                'wind_speed_knots': davis_speed,
                'wind_direction_deg': davis_direction
            }
            readings_davis.append(davis_reading)
            readings_tempest.append(tempest_wind)
            
            print(f"Davis:   {davis_speed:.1f} knots, {davis_direction:.0f}°")
            print(f"Stored reading pair #{len(readings_davis)}")
            
            # Calculate and show current calibration if we have enough readings
            if len(readings_davis) >= 2:
                calibration = calculate_calibration_factors(readings_davis, readings_tempest)
                if calibration:
                    print(f"\nCurrent calibration (based on {len(readings_davis)} samples):")
                    print(f"  Speed factor: {calibration['speed_calibration_factor']:.3f}")
                    print(f"  Direction offset: {calibration['direction_offset']:.1f}°")
                    print(f"  Confidence: Speed={calibration['speed_confidence']:.2f}, Direction={calibration['direction_confidence']:.2f}")
            
            print()
            
        except ValueError:
            print("Invalid input. Use numbers only (e.g., 8.5,145)")
        except KeyboardInterrupt:
            break
    
    # Final calibration results
    if len(readings_davis) >= 2:
        print("\n" + "=" * 60)
        print("FINAL CALIBRATION RESULTS")
        print("=" * 60)
        calibration = calculate_calibration_factors(readings_davis, readings_tempest)
        if calibration:
            print(f"Samples: {calibration['sample_count']}")
            print(f"Speed calibration factor: {calibration['speed_calibration_factor']:.4f}")
            print(f"Direction offset: {calibration['direction_offset']:.2f}°")
            print(f"Speed confidence: {calibration['speed_confidence']:.3f}")
            print(f"Direction confidence: {calibration['direction_confidence']:.3f}")
            print("=" * 60)
            print("Command line for Davis plugin:")
            print(f"python3 main.py --calibration-factor {calibration['speed_calibration_factor']:.4f} \\")
            print(f"                --direction-offset {calibration['direction_offset']:.2f}")
            print("=" * 60)
        else:
            print("Could not calculate calibration factors")
    else:
        print("\nNeed at least 2 readings for calibration")

# ---------------- Continuous Calibration Mode ----------------
def parse_davis_wind_data(data_line, calibration_factor=1.0, direction_offset=0.0, direction_scale=1.0):
    """
    Parse Davis wind sensor data from serial input
    Expected format from Arduino: "wind: iteration potvalue rpmtops rpmraw"
    """
    data_line = data_line.strip()
    
    # Pattern for Davis Arduino output: "wind: %d %d %d %d"
    pattern = r'wind:\s*(\d+)\s+(\d+)\s+(\d+)\s+(\d+)'
    
    match = re.search(pattern, data_line)
    if match:
        try:
            iteration = int(match.group(1))
            pot_value = int(match.group(2))
            rpm_tops = int(match.group(3))
            rpm_raw = int(match.group(4))
            
            # Calculate wind direction from potentiometer value with calibration
            direction_deg = (pot_value / 1024.0) * 360.0
            direction_deg = (direction_deg * direction_scale + direction_offset) % 360.0
            
            if direction_deg < 0:
                direction_deg += 360.0
            
            # Convert RPM to wind speed (Davis anemometer calibration)
            # Common formula: Wind Speed (m/s) = RPM * 0.098
            speed_mps = rpm_tops * 0.098 * calibration_factor
            speed_knots = speed_mps * 1.94384  # m/s to knots
            
            return {
                'wind_speed_knots': speed_knots,
                'wind_direction_deg': direction_deg,
                'iteration': iteration,
                'pot_value': pot_value,
                'rpm_tops': rpm_tops,
                'rpm_raw': rpm_raw
            }
                
        except (ValueError, IndexError):
            return None
    
    return None

def continuous_calibration(args):
    """Run continuous calibration comparing Davis and Tempest readings"""
    print("Davis Wind Sensor Continuous Calibration using Local Tempest Station")
    print("=" * 70)
    print(f"Calibration interval: {args.calibration_interval} seconds ({args.calibration_interval/60:.1f} minutes)")
    print(f"Samples per calibration: {args.sample_count}")
    print(f"Interval between samples: {args.sample_interval} seconds")
    print(f"Davis sensor port: {args.davis_port}")
    print()
    
    # Setup firewall rules for UDP reception
    if not firewall_manager.skip_setup:
        print("Setting up network access for Tempest UDP broadcasts...")
        if not firewall_manager.setup_firewall():
            print("⚠️  Warning: Network setup may be incomplete")
            print("If you don't receive Tempest data, check your firewall settings")
        print()
    else:
        print("Firewall setup skipped")
        print()
    
    # Start UDP listener in background
    print("🌐 Starting Tempest UDP listener...")
    udp_thread = threading.Thread(target=udp_listener, daemon=True)
    udp_thread.start()
    
    # Wait for initial Tempest data
    print("⏳ Waiting for Tempest UDP broadcasts...")
    import time
    time.sleep(5)
    
    tempest_wind = get_current_tempest_wind()
    if not tempest_wind:
        print("❌ No Tempest data received. Ensure your Tempest station is broadcasting.")
        print("💡 Troubleshooting:")
        print("   - Check that Tempest hub is on same network")
        print("   - Verify UDP port 50222 is accessible")
        print("   - Try: python3 tempest.py --test-connection")
        return
    
    print(f"✅ Tempest detected! Current reading: {tempest_wind['wind_speed_knots']:.1f} knots, {tempest_wind['wind_direction_deg']:.0f}° ({tempest_wind['source']})")
    print()
    
    # Current calibration factors
    current_calibration_factor = 1.0
    current_direction_offset = 0.0
    
    print("🔄 Starting continuous calibration mode...")
    print("Press Ctrl+C to stop")
    print()
    
    try:
        # Main continuous calibration loop
        while True:
            next_calibration_time = datetime.now() + timedelta(seconds=args.calibration_interval)
            
            print(f"📊 Starting calibration data collection at {datetime.now().strftime('%H:%M:%S')}")
            print(f"⏰ Next calibration scheduled for {next_calibration_time.strftime('%H:%M:%S')}")
            
            # Collect calibration samples
            davis_readings = []
            tempest_readings = []
            samples_collected = 0
            
            try:
                # Open serial connection to Davis sensor
                ser = serial.Serial(
                    port=args.davis_port,
                    baudrate=115200,
                    timeout=30.0,
                    bytesize=serial.EIGHTBITS,
                    parity=serial.PARITY_NONE,
                    stopbits=serial.STOPBITS_ONE
                )
                print(f"✅ Connected to Davis sensor on {args.davis_port}")
                
                # Collect samples
                start_time = time.time()
                timeout = args.sample_count * args.sample_interval * 2  # Generous timeout
                
                while samples_collected < args.sample_count:
                    if time.time() - start_time > timeout:
                        print(f"⚠️  Sample collection timeout after {timeout} seconds")
                        break
                    
                    try:
                        # Read from Davis sensor
                        line = ser.readline().decode('utf-8', errors='ignore').strip()
                        if not line:
                            continue
                            
                        davis_data = parse_davis_wind_data(
                            line, 
                            current_calibration_factor, 
                            current_direction_offset, 
                            1.0  # direction_scale
                        )
                        
                        if davis_data:
                            # Get corresponding Tempest reading
                            tempest_data = get_current_tempest_wind()
                            
                            if tempest_data:
                                davis_readings.append(davis_data)
                                tempest_readings.append(tempest_data)
                                samples_collected += 1
                                
                                print(f"   Sample {samples_collected}/{args.sample_count}: "
                                     f"Davis: {davis_data['wind_speed_knots']:.1f} knots, {davis_data['wind_direction_deg']:.0f}° | "
                                     f"Tempest: {tempest_data['wind_speed_knots']:.1f} knots, {tempest_data['wind_direction_deg']:.0f}°")
                                
                                # Wait before next sample (if not the last one)
                                if samples_collected < args.sample_count:
                                    time.sleep(args.sample_interval)
                            else:
                                time.sleep(1)  # Short wait if no Tempest data
                        else:
                            time.sleep(0.5)  # Short wait if no valid Davis data
                            
                    except serial.SerialTimeoutException:
                        continue
                    except Exception as e:
                        print(f"⚠️  Error reading Davis sensor: {e}")
                        time.sleep(1)
                        continue
                
                ser.close()
                
            except serial.SerialException as e:
                print(f"❌ Could not connect to Davis sensor: {e}")
                print("⏳ Will retry at next calibration interval...")
                
                # Wait until next calibration time
                sleep_time = (next_calibration_time - datetime.now()).total_seconds()
                if sleep_time > 0:
                    time.sleep(sleep_time)
                continue
            
            # Calculate new calibration if we have enough samples
            if samples_collected >= 3:
                print(f"\n🧮 Calculating calibration from {samples_collected} samples...")
                
                calibration_result = calculate_calibration_factors(davis_readings, tempest_readings)
                
                if calibration_result:
                    new_speed_factor = calibration_result['speed_calibration_factor']
                    new_direction_offset = calibration_result['direction_offset']
                    speed_confidence = calibration_result['speed_confidence']
                    direction_confidence = calibration_result['direction_confidence']
                    
                    print(f"📈 Calculated calibration:")
                    print(f"   Speed factor: {new_speed_factor:.4f} (confidence: {speed_confidence:.3f})")
                    print(f"   Direction offset: {new_direction_offset:.2f}° (confidence: {direction_confidence:.3f})")
                    
                    # Apply calibration if confidence is reasonable
                    min_confidence = 0.5  # Lower threshold for continuous mode
                    if speed_confidence >= min_confidence and direction_confidence >= min_confidence:
                        # Gradually adjust calibration to avoid sudden jumps
                        adjustment_weight = 0.3  # Apply 30% of the calculated adjustment each time
                        
                        current_calibration_factor = (
                            current_calibration_factor * (1 - adjustment_weight) + 
                            new_speed_factor * adjustment_weight
                        )
                        current_direction_offset = (
                            current_direction_offset * (1 - adjustment_weight) + 
                            new_direction_offset * adjustment_weight
                        )
                        
                        print(f"✅ Applied gradual calibration adjustment:")
                        print(f"   New speed factor: {current_calibration_factor:.4f}")
                        print(f"   New direction offset: {current_direction_offset:.2f}°")
                    else:
                        print(f"⚠️  Low confidence - keeping current calibration")
                        print(f"   Current speed factor: {current_calibration_factor:.4f}")
                        print(f"   Current direction offset: {current_direction_offset:.2f}°")
                else:
                    print("⚠️  Could not calculate calibration factors - keeping current calibration")
            else:
                print(f"⚠️  Insufficient samples ({samples_collected}) - need at least 3. Keeping current calibration.")
            
            print()
            
            # Wait until next calibration time
            sleep_time = (next_calibration_time - datetime.now()).total_seconds()
            if sleep_time > 0:
                print(f"⏳ Waiting {sleep_time:.0f} seconds until next calibration...")
                time.sleep(sleep_time)
    
    except KeyboardInterrupt:
        print("\n🛑 Continuous calibration stopped by user")
        print(f"📊 Final calibration factors:")
        print(f"   Speed factor: {current_calibration_factor:.4f}")
        print(f"   Direction offset: {current_direction_offset:.2f}°")
        print("💡 To use these values manually:")
        print(f"   python3 main.py --calibration-factor {current_calibration_factor:.4f} --direction-offset {current_direction_offset:.2f}")
    except Exception as e:
        print(f"❌ Unexpected error in continuous calibration: {e}")
        raise

def main():
    parser = argparse.ArgumentParser(
        description="Tempest Weather Station UDP Receiver with Davis Calibration"
    )
    parser.add_argument(
        "--calibrate", 
        action="store_true",
        help="Run interactive calibration mode (console-based)"
    )
    parser.add_argument(
        "--port", 
        type=int, 
        default=8080,
        help="HTTP server port (default: 8080)"
    )
    parser.add_argument(
        "--no-firewall", 
        action="store_true",
        help="Skip automatic firewall configuration"
    )
    parser.add_argument(
        "--test-connection", 
        action="store_true",
        help="Test UDP connection and firewall setup, then exit"
    )
    parser.add_argument(
        "--continuous", 
        action="store_true",
        help="Run continuous calibration mode - compares Davis and Tempest readings and auto-adjusts every 15 minutes"
    )
    parser.add_argument(
        "--davis-port", 
        default="/dev/ttyACM2",
        help="Davis sensor serial port (default: /dev/ttyACM2) - only used in continuous mode"
    )
    parser.add_argument(
        "--calibration-interval", 
        type=int, 
        default=900,  # 15 minutes in seconds
        help="Interval between calibration adjustments in seconds (default: 900 = 15 minutes)"
    )
    parser.add_argument(
        "--sample-count", 
        type=int, 
        default=20,
        help="Number of samples to collect for each calibration calculation (default: 20)"
    )
    parser.add_argument(
        "--sample-interval", 
        type=int, 
        default=5,
        help="Seconds between calibration samples (default: 5)"
    )
    
    args = parser.parse_args()
    
    if args.test_connection:
        print("Testing Tempest UDP connection and firewall setup...")
        print("=" * 50)
        
        if not args.no_firewall:
            firewall_manager.setup_firewall()
        else:
            print("Skipping firewall setup (--no-firewall specified)")
            firewall_manager.check_port_status()
        
        print("\nStarting UDP listener test (10 seconds)...")
        udp_thread = threading.Thread(target=udp_listener, daemon=True)
        udp_thread.start()
        
        import time
        time.sleep(10)
        
        with lock:
            if latest_raw_by_type:
                print(f"✓ SUCCESS: Received {len(latest_raw_by_type)} message types from Tempest:")
                for msg_type in latest_raw_by_type.keys():
                    print(f"  - {msg_type}")
                
                if "rapid_wind" in latest_parsed_by_type or "obs_st" in latest_parsed_by_type:
                    wind_data = get_current_tempest_wind()
                    if wind_data:
                        print(f"\nCurrent wind: {wind_data['wind_speed_knots']:.1f} knots, {wind_data['wind_direction_deg']:.0f}° ({wind_data['source']})")
                    else:
                        print("\n⚠️  Wind data received but could not parse current conditions")
                else:
                    print("\n⚠️  No wind data received yet")
            else:
                print("✗ FAILURE: No UDP data received from Tempest station")
                print("\nTroubleshooting:")
                print("1. Check that Tempest hub is on same network")
                print("2. Verify Tempest station is broadcasting (usually enabled by default)")
                print("3. Check firewall/router settings for UDP port 50222")
                print("4. Try running with sudo if permission issues persist")
        
        return
    
    if args.continuous:
        # Skip firewall setup if requested
        if args.no_firewall:
            print("Skipping automatic firewall configuration")
            firewall_manager.skip_setup = True
        
        continuous_calibration(args)
    elif args.calibrate:
        # Skip firewall setup if requested
        if args.no_firewall:
            print("Skipping automatic firewall configuration")
            # Set a flag to skip firewall in interactive mode
            firewall_manager.skip_setup = True
        
        interactive_calibration()
    else:
        # Setup firewall for web mode
        if not args.no_firewall:
            print("Setting up network access for Tempest UDP broadcasts...")
            if not firewall_manager.setup_firewall():
                print("⚠️  Warning: Network setup may be incomplete")
                print("If you don't receive Tempest data, check your firewall settings")
            print()
        
        # Start UDP listener and web server
        udp_thread = threading.Thread(target=udp_listener, daemon=True)
        udp_thread.start()
        
        print(f"Starting Tempest receiver with calibration web interface")
        print(f"UDP listener: port {UDP_PORT}")
        print(f"Web interface: http://localhost:{args.port}")
        print(f"Calibration dashboard: http://localhost:{args.port}/calibration")
        print()
        print("Note: Firewall rules will be automatically cleaned up on exit")
        
        try:
            app.run(host="0.0.0.0", port=args.port)
        except KeyboardInterrupt:
            print("\nShutting down...")

if __name__ == "__main__":
    main()

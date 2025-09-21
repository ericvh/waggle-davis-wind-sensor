#!/usr/bin/env python3

import argparse
import logging
import math
import time
import serial
import re
import json
import threading
import requests
import socket
import subprocess
import platform
import signal
import atexit
from datetime import datetime, timedelta, timezone
from contextlib import contextmanager
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from waggle.plugin import Plugin



# Tempest calibration functionality is now integrated directly
HAS_TEMPEST = True

# Tempest UDP broadcast port
UDP_PORT = 50222

# Global Tempest data storage for auto-calibration
tempest_data_lock = threading.Lock()
latest_tempest_raw_by_type = {}
latest_tempest_parsed_by_type = {}

# ---------------- Firewall Management for Auto-Calibration ----------------
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
            manual_cmd = f"iptables -I INPUT -p udp --dport {self.port} -j ACCEPT"
            print(f"Manual command: {manual_cmd}")
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


# ---------------- Tempest UDP Message Parsers for Auto-Calibration ----------------
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

def parse_obs_st(msg):
    """Parse Tempest device observation messages"""
    obs = msg.get("obs", [[]])[0] if msg.get("obs") else []
    if not obs:
        return {"type": "obs_st", "error": "empty obs"}

    return {
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
            "received_at": int(time.time()),
        },
    }

def parse_rapid_wind(msg):
    """Parse rapid wind messages for instant wind readings"""
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
            "received_at": int(time.time()),
        },
    }

def parse_hub_status(msg):
    """Parse hub status messages"""
    return {
        "firmware": msg.get("firmware_revision"),
        "uptime_s": msg.get("uptime"),
        "rssi": msg.get("rssi"),
        "timestamp": msg.get("time"),
        "meta": {
            "hub_sn": msg.get("serial_number"),
            "received_at": int(time.time()),
        },
    }

TEMPEST_PARSERS = {
    "obs_st": parse_obs_st,
    "rapid_wind": parse_rapid_wind,
    "hub_status": parse_hub_status,
}

def get_current_tempest_wind():
    """Get current wind data from latest Tempest readings"""
    with tempest_data_lock:
        # Try rapid_wind first (most recent), fallback to obs_st
        if "rapid_wind" in latest_tempest_parsed_by_type:
            data = latest_tempest_parsed_by_type["rapid_wind"]["data"]
            if "error" not in data:
                return {
                    'wind_speed_knots': data["wind"]["instant_kt"],
                    'wind_direction_deg': data["wind"]["direction_deg"],
                    'timestamp': data["timestamp"],
                    'source': 'rapid_wind'
                }
        
        if "obs_st" in latest_tempest_parsed_by_type:
            data = latest_tempest_parsed_by_type["obs_st"]["data"]
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

def tempest_udp_listener():
    """UDP listener thread for Tempest broadcasts"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", UDP_PORT))
        
        while True:
            try:
                data, addr = sock.recvfrom(65535)
                msg = json.loads(data.decode("utf-8"))
                
                msg_type = msg.get("type", "unknown")
                
                # Store the raw message by type
                with tempest_data_lock:
                    latest_tempest_raw_by_type[msg_type] = msg
                    
                    # If we have a parser for this type, also store parsed
                    parser = TEMPEST_PARSERS.get(msg_type)
                    if parser:
                        try:
                            parsed_data = parser(msg)
                            latest_tempest_parsed_by_type[msg_type] = {
                                "type": msg_type,
                                "data": parsed_data
                            }
                        except Exception as e:
                            # Skip parsing errors
                            pass
                    else:
                        # If no parser, remove any stale parsed entry
                        if msg_type in latest_tempest_parsed_by_type:
                            del latest_tempest_parsed_by_type[msg_type]
                            
            except json.JSONDecodeError:
                # Skip non-JSON packets
                continue
            except Exception as e:
                # Log UDP errors but continue listening
                logging.getLogger(__name__).debug(f"UDP listener error: {e}")
                continue
                
    except Exception as e:
        logging.getLogger(__name__).error(f"Failed to start Tempest UDP listener: {e}")
        

# Wind speed conversion constants
MPS_TO_KNOTS = 1.94384  # meters per second to knots conversion factor

# Davis anemometer calibration
# Default RPM to wind speed conversion: speed (m/s) = RPM * 0.098
# This factor may need adjustment based on your specific Davis anemometer model
# Common Davis anemometers use cup sizes that result in this conversion factor
DEFAULT_RPM_TO_MPS = 0.098

# Global data storage for web server
latest_data = {
    "timestamp": None,
    "wind_data": None,
    "raw_line": None,
    "status": "starting",
    "error_count": 0,
    "total_readings": 0,
    "last_mqtt_report": None,
    "readings_since_report": 0
}


def parse_args():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description="Wind sensor plugin for Waggle - reads wind data from USB serial port"
    )
    parser.add_argument(
        "--port", 
        default="/dev/ttyACM2", 
        help="Serial port device (default: /dev/ttyACM2)"
    )
    parser.add_argument(
        "--baudrate", 
        type=int, 
        default=115200, 
        help="Serial port baud rate (default: 115200)"
    )
    parser.add_argument(
        "--timeout", 
        type=float, 
        default=5.0, 
        help="Serial port timeout in seconds (default: 5.0)"
    )

    parser.add_argument(
        "--debug", 
        action="store_true", 
        help="Enable debug output"
    )
    parser.add_argument(
        "--calibration-factor", 
        type=float, 
        default=1.0, 
        help="Wind speed calibration factor (default: 1.0)"
    )
    parser.add_argument(
        "--direction-offset", 
        type=float, 
        default=0.0, 
        help="Wind direction offset in degrees (default: 0.0)"
    )
    parser.add_argument(
        "--direction-scale", 
        type=float, 
        default=1.0, 
        help="Wind direction scaling factor (default: 1.0)"
    )
    parser.add_argument(
        "--web-server", 
        action="store_true", 
        help="Enable mini web server for monitoring"
    )
    parser.add_argument(
        "--web-port", 
        type=int, 
        default=8080, 
        help="Web server port (default: 8080)"
    )
    parser.add_argument(
        "--reporting-interval", 
        type=int, 
        default=60, 
        help="MQTT reporting interval in seconds for averaged data (default: 60)"
    )
    # Auto-calibration with local Tempest UDP broadcasts
    parser.add_argument(
        "--auto-calibrate", 
        action="store_true", 
        help="Run automatic Tempest calibration at startup using UDP broadcasts"
    )
    parser.add_argument(
        "--calibration-samples", 
        type=int, 
        default=10, 
        help="Number of samples for auto-calibration (default: 10)"
    )
    parser.add_argument(
        "--calibration-interval", 
        type=int, 
        default=5, 
        help="Seconds between calibration samples (default: 5)"
    )
    parser.add_argument(
        "--calibration-timeout", 
        type=int, 
        default=300, 
        help="Maximum time for calibration in seconds (default: 300)"
    )
    parser.add_argument(
        "--min-calibration-confidence", 
        type=float, 
        default=0.7, 
        help="Minimum confidence required for auto-calibration (default: 0.7)"
    )
    parser.add_argument(
        "--no-firewall", 
        action="store_true", 
        help="Skip automatic firewall setup for calibration"
    )
    # Continuous calibration mode
    parser.add_argument(
        "--continuous-calibration", 
        action="store_true", 
        help="Enable continuous calibration mode - automatically adjusts calibration every 15 minutes"
    )
    parser.add_argument(
        "--continuous-interval", 
        type=int, 
        default=900,  # 15 minutes in seconds
        help="Interval between continuous calibration adjustments in seconds (default: 900 = 15 minutes)"
    )
    parser.add_argument(
        "--continuous-samples", 
        type=int, 
        default=20,
        help="Number of samples to collect for each continuous calibration calculation (default: 20)"
    )
    parser.add_argument(
        "--continuous-sample-interval", 
        type=int, 
        default=5,
        help="Seconds between continuous calibration samples (default: 5)"
    )
    parser.add_argument(
        "--continuous-confidence-threshold", 
        type=float, 
        default=0.5,
        help="Minimum confidence required for continuous calibration adjustments (default: 0.5)"
    )
    parser.add_argument(
        "--continuous-adjustment-rate", 
        type=float, 
        default=0.3,
        help="Rate of calibration adjustment per cycle (0.1-1.0, default: 0.3 = 30%% per cycle)"
    )
    return parser.parse_args()


class WindDataCollector:
    """Collects wind data over time intervals and calculates averages"""
    
    def __init__(self, interval_seconds=60):
        self.interval_seconds = interval_seconds
        self.reset_collection()
    
    def reset_collection(self):
        """Reset data collection for a new interval"""
        self.wind_speeds_mps = []
        self.wind_directions_deg = []
        self.wind_speeds_knots = []
        self.start_time = datetime.now()
        self.sample_count = 0
        self.min_speed_knots = float('inf')
        self.max_speed_knots = 0.0
        self.min_speed_mps = float('inf')
        self.max_speed_mps = 0.0
    
    def add_reading(self, wind_data):
        """Add a new wind reading to the collection"""
        self.wind_speeds_mps.append(wind_data['wind_speed_mps'])
        self.wind_speeds_knots.append(wind_data['wind_speed_knots'])
        self.wind_directions_deg.append(wind_data['wind_direction_deg'])
        
        # Track min/max wind speeds
        speed_knots = wind_data['wind_speed_knots']
        speed_mps = wind_data['wind_speed_mps']
        
        self.min_speed_knots = min(self.min_speed_knots, speed_knots)
        self.max_speed_knots = max(self.max_speed_knots, speed_knots)
        self.min_speed_mps = min(self.min_speed_mps, speed_mps)
        self.max_speed_mps = max(self.max_speed_mps, speed_mps)
        
        self.sample_count += 1
    
    def should_report(self):
        """Check if it's time to generate an averaged report"""
        elapsed = datetime.now() - self.start_time
        return elapsed.total_seconds() >= self.interval_seconds and self.sample_count > 0
    
    def get_averaged_data(self):
        """Calculate and return averaged wind data"""
        if self.sample_count == 0:
            return None
        
        # Calculate average wind speed (simple arithmetic mean)
        avg_speed_mps = sum(self.wind_speeds_mps) / len(self.wind_speeds_mps)
        avg_speed_knots = sum(self.wind_speeds_knots) / len(self.wind_speeds_knots)
        
        # Calculate average wind direction using vector averaging
        # This properly handles the circular nature of wind direction
        x_components = [math.cos(math.radians(d)) for d in self.wind_directions_deg]
        y_components = [math.sin(math.radians(d)) for d in self.wind_directions_deg]
        
        avg_x = sum(x_components) / len(x_components)
        avg_y = sum(y_components) / len(y_components)
        
        # Convert back to degrees
        avg_direction_rad = math.atan2(avg_y, avg_x)
        avg_direction_deg = math.degrees(avg_direction_rad)
        
        # Ensure direction is in 0-360 range
        if avg_direction_deg < 0:
            avg_direction_deg += 360
        
        # Calculate result magnitude for wind consistency indication
        result_magnitude = math.sqrt(avg_x * avg_x + avg_y * avg_y)
        wind_consistency = result_magnitude  # 1.0 = very consistent, 0.0 = highly variable
        
        # Handle edge case where no valid readings were collected
        if self.min_speed_knots == float('inf'):
            self.min_speed_knots = 0.0
            self.min_speed_mps = 0.0
        
        averaged_data = {
            'avg_wind_speed_mps': avg_speed_mps,
            'avg_wind_speed_knots': avg_speed_knots, 
            'avg_wind_direction_deg': avg_direction_deg,
            'wind_consistency': wind_consistency,
            'min_wind_speed_knots': self.min_speed_knots,
            'max_wind_speed_knots': self.max_speed_knots,
            'min_wind_speed_mps': self.min_speed_mps,
            'max_wind_speed_mps': self.max_speed_mps,
            'sample_count': self.sample_count,
            'interval_seconds': self.interval_seconds,
            'start_time': self.start_time,
            'end_time': datetime.now()
        }
        
        return averaged_data





class WebServerHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the monitoring web server"""
    
    def log_message(self, format, *args):
        """Override to suppress default logging"""
        pass
    
    def do_GET(self):
        """Handle GET requests"""
        parsed_path = urlparse(self.path)
        
        if parsed_path.path == '/':
            self.serve_dashboard()
        elif parsed_path.path == '/data.html' or parsed_path.path == '/simple':
            self.serve_simple_html()
        elif parsed_path.path == '/api/data':
            self.serve_json_data()
        elif parsed_path.path == '/api/status':
            self.serve_status()
        else:
            self.send_error(404, "Not Found")
    
    def serve_dashboard(self):
        """Serve the main HTML dashboard"""
        html_content = """
<!DOCTYPE html>
<html>
<head>
    <title>Davis Wind Sensor Monitor</title>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; background-color: #f5f5f5; }
        .container { max-width: 1200px; margin: 0 auto; }
        .header { background-color: #2c3e50; color: white; padding: 20px; border-radius: 5px; margin-bottom: 20px; }
        .card { background-color: white; padding: 20px; margin: 10px 0; border-radius: 5px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        .metric { display: inline-block; margin: 10px 20px 10px 0; }
        .metric-label { font-size: 14px; color: #666; }
        .metric-value { font-size: 24px; font-weight: bold; color: #2c3e50; }
        .debug-data { font-family: monospace; background-color: #f8f9fa; padding: 10px; border-radius: 3px; }
        .status-ok { color: #27ae60; }
        .status-error { color: #e74c3c; }
        .auto-refresh { margin: 10px 0; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; }
        @media (max-width: 768px) { .grid { grid-template-columns: 1fr; } }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🌪️ Davis Wind Sensor Monitor</h1>
            <p>Real-time wind measurements and debug information</p>
        </div>
        
        <div class="card">
            <div class="auto-refresh">
                <label><input type="checkbox" id="autoRefresh" checked> Auto-refresh (5s)</label>
                <button onclick="refreshData()">Refresh Now</button>
                <span id="lastUpdate"></span>
            </div>
        </div>
        
        <div class="grid">
            <div class="card">
                <h2>Environmental Measurements</h2>
                <div class="metric">
                    <div class="metric-label">Wind Speed</div>
                    <div class="metric-value" id="windSpeed">-- knots</div>
                </div>
                <div class="metric">
                    <div class="metric-label">Wind Direction</div>
                    <div class="metric-value" id="windDirection">-- °</div>
                </div>
                <div class="metric">
                    <div class="metric-label">Speed (m/s)</div>
                    <div class="metric-value" id="windSpeedMps">-- m/s</div>
                </div>
                <div class="metric">
                    <div class="metric-label">Min Speed (Lull)</div>
                    <div class="metric-value" id="windSpeedMin">-- knots</div>
                </div>
                <div class="metric">
                    <div class="metric-label">Max Speed (Gust)</div>
                    <div class="metric-value" id="windSpeedMax">-- knots</div>
                </div>
            </div>
            
            <div class="card">
                <h2>Debug Information</h2>
                <div class="metric">
                    <div class="metric-label">RPM (Debounced)</div>
                    <div class="metric-value" id="rpmTops">--</div>
                </div>
                <div class="metric">
                    <div class="metric-label">RPM (Raw)</div>
                    <div class="metric-value" id="rpmRaw">--</div>
                </div>
                <div class="metric">
                    <div class="metric-label">Rotations/Sec</div>
                    <div class="metric-value" id="rps">--</div>
                </div>
                <div class="metric">
                    <div class="metric-label">Pot Value</div>
                    <div class="metric-value" id="potValue">--</div>
                </div>
            </div>
            
            <div class="card">
                <h2>System Status</h2>
                <div class="metric">
                    <div class="metric-label">Status</div>
                    <div class="metric-value" id="status">--</div>
                </div>
                <div class="metric">
                    <div class="metric-label">Total Readings</div>
                    <div class="metric-value" id="totalReadings">--</div>
                </div>
                <div class="metric">
                    <div class="metric-label">Error Count</div>
                    <div class="metric-value" id="errorCount">--</div>
                </div>
                <div class="metric">
                    <div class="metric-label">Iteration</div>
                    <div class="metric-value" id="iteration">--</div>
                </div>
                <div class="metric">
                    <div class="metric-label">Last MQTT Report</div>
                    <div class="metric-value" id="lastMqttReport">--</div>
                </div>
                <div class="metric">
                    <div class="metric-label">Readings Since Report</div>
                    <div class="metric-value" id="readingsSinceReport">--</div>
                </div>
            </div>
        </div>
        
        <div class="card">
            <h2>Raw Serial Data</h2>
            <div class="debug-data" id="rawData">No data received yet...</div>
        </div>
    </div>

    <script>
        function refreshData() {
            fetch('/api/data')
                .then(response => response.json())
                .then(data => {
                    if (data.wind_data) {
                        document.getElementById('windSpeed').textContent = data.wind_data.wind_speed_knots.toFixed(2) + ' knots';
                        document.getElementById('windDirection').textContent = data.wind_data.wind_direction_deg.toFixed(1) + '°';
                        document.getElementById('windSpeedMps').textContent = data.wind_data.wind_speed_mps.toFixed(2) + ' m/s';
                        
                        // Update min/max values if available
                        if (data.wind_data.min_wind_speed_knots !== undefined) {
                            document.getElementById('windSpeedMin').textContent = data.wind_data.min_wind_speed_knots.toFixed(2) + ' knots';
                            document.getElementById('windSpeedMax').textContent = data.wind_data.max_wind_speed_knots.toFixed(2) + ' knots';
                        } else {
                            document.getElementById('windSpeedMin').textContent = '-- knots';
                            document.getElementById('windSpeedMax').textContent = '-- knots';
                        }
                        document.getElementById('rpmTops').textContent = data.wind_data.rpm_tops;
                        document.getElementById('rpmRaw').textContent = data.wind_data.rpm_raw;
                        document.getElementById('rps').textContent = data.wind_data.rotations_per_second.toFixed(3);
                        document.getElementById('potValue').textContent = data.wind_data.pot_value;
                        document.getElementById('iteration').textContent = data.wind_data.iteration;
                    }
                    
                    document.getElementById('status').textContent = data.status;
                    document.getElementById('status').className = 'metric-value ' + (data.status === 'running' ? 'status-ok' : 'status-error');
                    document.getElementById('totalReadings').textContent = data.total_readings;
                    document.getElementById('errorCount').textContent = data.error_count;
                    document.getElementById('lastMqttReport').textContent = data.last_mqtt_report ? new Date(data.last_mqtt_report).toLocaleString() : 'Never';
                    document.getElementById('readingsSinceReport').textContent = data.readings_since_report;
                    document.getElementById('rawData').textContent = data.raw_line || 'No data received yet...';
                    document.getElementById('lastUpdate').textContent = '(Updated: ' + new Date().toLocaleTimeString() + ')';
                })
                .catch(error => {
                    console.error('Error fetching data:', error);
                    document.getElementById('status').textContent = 'Connection Error';
                    document.getElementById('status').className = 'metric-value status-error';
                });
        }
        
        // Auto-refresh functionality
        let refreshInterval;
        function startAutoRefresh() {
            refreshInterval = setInterval(refreshData, 5000);
        }
        
        function stopAutoRefresh() {
            clearInterval(refreshInterval);
        }
        
        document.getElementById('autoRefresh').addEventListener('change', function() {
            if (this.checked) {
                startAutoRefresh();
            } else {
                stopAutoRefresh();
            }
        });
        
        // Initial load and start auto-refresh
        refreshData();
        startAutoRefresh();
    </script>
</body>
</html>
        """
        
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(html_content.encode('utf-8'))
    
    def serve_json_data(self):
        """Serve the current data as JSON"""
        global latest_data
        
        response_data = latest_data.copy()
        
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(response_data, default=str, indent=2).encode('utf-8'))
    
    def serve_status(self):
        """Serve just the status information"""
        global latest_data
        
        status_data = {
            "status": latest_data["status"],
            "timestamp": latest_data["timestamp"],
            "error_count": latest_data["error_count"],
            "total_readings": latest_data["total_readings"]
        }
        
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(status_data, default=str).encode('utf-8'))
    
    def serve_simple_html(self):
        """Serve a simple formatted HTML view of the current data"""
        global latest_data
        
        # Get current time for display
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Format the data timestamp if available
        data_time = "No data yet"
        if latest_data["timestamp"]:
            data_time = latest_data["timestamp"].strftime("%Y-%m-%d %H:%M:%S")
        
        # Build the HTML content
        html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Davis Wind Sensor Data</title>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="refresh" content="10">
    <style>
        body {{ 
            font-family: 'Courier New', monospace; 
            margin: 20px; 
            background-color: #f8f9fa;
            line-height: 1.4;
        }}
        .container {{ 
            max-width: 800px; 
            margin: 0 auto; 
            background-color: white;
            padding: 20px;
            border-radius: 5px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .header {{ 
            text-align: center; 
            margin-bottom: 20px; 
            border-bottom: 2px solid #dee2e6;
            padding-bottom: 10px;
        }}
        .data-section {{ 
            margin: 15px 0; 
            padding: 10px;
            background-color: #f8f9fa;
            border-left: 4px solid #007bff;
        }}
        .measurement {{ 
            display: flex; 
            justify-content: space-between; 
            margin: 5px 0;
            padding: 3px 0;
        }}
        .label {{ 
            font-weight: bold; 
            color: #495057;
        }}
        .value {{ 
            color: #212529; 
            font-weight: bold;
        }}
        .status-ok {{ color: #28a745; }}
        .status-error {{ color: #dc3545; }}
        .timestamp {{ 
            color: #6c757d; 
            font-size: 0.9em; 
            text-align: center;
            margin-top: 20px;
            border-top: 1px solid #dee2e6;
            padding-top: 10px;
        }}
        .raw-data {{ 
            background-color: #e9ecef; 
            padding: 10px; 
            border-radius: 3px; 
            font-family: monospace;
            word-break: break-all;
        }}
        @media (max-width: 600px) {{
            .measurement {{ flex-direction: column; }}
            .label {{ margin-bottom: 2px; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🌪️ Davis Wind Sensor</h1>
            <h2>Real-time Data View</h2>
        </div>
        
        <div class="data-section">
            <h3>Environmental Measurements</h3>"""
        
        if latest_data["wind_data"]:
            wind_data = latest_data["wind_data"]
            html_content += f"""
            <div class="measurement">
                <span class="label">Wind Speed:</span>
                <span class="value">{wind_data['wind_speed_knots']:.2f} knots ({wind_data['wind_speed_mps']:.2f} m/s)</span>
            </div>
            <div class="measurement">
                <span class="label">Wind Direction:</span>
                <span class="value">{wind_data['wind_direction_deg']:.1f}°</span>
            </div>
            <div class="measurement">
                <span class="label">Rotations per Second:</span>
                <span class="value">{wind_data['rotations_per_second']:.3f} RPS</span>
            </div>"""
            
            # Add min/max wind speeds if available
            if 'min_wind_speed_knots' in wind_data:
                html_content += f"""
            <div class="measurement">
                <span class="label">Min Speed (Lull):</span>
                <span class="value">{wind_data['min_wind_speed_knots']:.2f} knots</span>
            </div>
            <div class="measurement">
                <span class="label">Max Speed (Gust):</span>
                <span class="value">{wind_data['max_wind_speed_knots']:.2f} knots</span>
            </div>"""
        else:
            html_content += """
            <div class="measurement">
                <span class="label">Status:</span>
                <span class="value">No wind data available yet</span>
            </div>"""
        
        html_content += """
        </div>
        
        <div class="data-section">
            <h3>Debug Information</h3>"""
        
        if latest_data["wind_data"]:
            wind_data = latest_data["wind_data"]
            html_content += f"""
            <div class="measurement">
                <span class="label">Iteration Count:</span>
                <span class="value">{wind_data['iteration']}</span>
            </div>
            <div class="measurement">
                <span class="label">RPM (Debounced):</span>
                <span class="value">{wind_data['rpm_tops']}</span>
            </div>
            <div class="measurement">
                <span class="label">RPM (Raw):</span>
                <span class="value">{wind_data['rpm_raw']}</span>
            </div>
            <div class="measurement">
                <span class="label">Potentiometer Value:</span>
                <span class="value">{wind_data['pot_value']}</span>
            </div>"""
        else:
            html_content += """
            <div class="measurement">
                <span class="label">Debug Data:</span>
                <span class="value">Not available</span>
            </div>"""
        
        html_content += """
        </div>
        
        <div class="data-section">
            <h3>System Status</h3>"""
        
        status_class = "status-ok" if latest_data["status"] == "running" else "status-error"
        html_content += f"""
            <div class="measurement">
                <span class="label">Connection Status:</span>
                <span class="value {status_class}">{latest_data["status"].title()}</span>
            </div>
            <div class="measurement">
                <span class="label">Total Readings:</span>
                <span class="value">{latest_data["total_readings"]}</span>
            </div>
            <div class="measurement">
                <span class="label">Error Count:</span>
                <span class="value">{latest_data["error_count"]}</span>
            </div>
            <div class="measurement">
                <span class="label">Last Data Time:</span>
                <span class="value">{data_time}</span>
            </div>
            <div class="measurement">
                <span class="label">Last MQTT Report:</span>
                <span class="value">{"Never" if not latest_data["last_mqtt_report"] else latest_data["last_mqtt_report"].strftime("%Y-%m-%d %H:%M:%S")}</span>
            </div>
            <div class="measurement">
                <span class="label">Readings Since Report:</span>
                <span class="value">{latest_data["readings_since_report"]}</span>
            </div>
        </div>"""
        
        if latest_data["raw_line"]:
            html_content += f"""
        <div class="data-section">
            <h3>Raw Serial Data</h3>
            <div class="raw-data">{latest_data["raw_line"]}</div>
        </div>"""
        
        html_content += f"""
        <div class="timestamp">
            Page generated: {current_time}<br>
            Auto-refresh: Every 10 seconds
        </div>
    </div>
</body>
</html>"""
        
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        self.end_headers()
        self.wfile.write(html_content.encode('utf-8'))


def start_web_server(port, logger):
    """Start the monitoring web server in a separate thread"""
    try:
        server = HTTPServer(('', port), WebServerHandler)
        logger.info(f"Web server starting on http://0.0.0.0:{port}")
        logger.info(f"Dashboard available at: http://localhost:{port}")
        logger.info(f"Simple HTML view: http://localhost:{port}/data.html")
        logger.info(f"JSON API available at: http://localhost:{port}/api/data")
        server.serve_forever()
    except Exception as e:
        logger.error(f"Web server error: {e}")


class WindSensorReader:
    """Wind sensor data reader for USB serial devices"""
    
    def __init__(self, port, baudrate=115200, timeout=5.0, calibration_factor=1.0, 
                 direction_offset=0.0, direction_scale=1.0):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.calibration_factor = calibration_factor
        self.direction_offset = direction_offset
        self.direction_scale = direction_scale
        self.logger = logging.getLogger(__name__)
        
    @contextmanager
    def serial_connection(self):
        """Context manager for serial connection"""
        ser = None
        try:
            ser = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=self.timeout,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE
            )
            self.logger.info(f"Connected to serial port {self.port} at {self.baudrate} baud")
            yield ser
        except serial.SerialException as e:
            self.logger.error(f"Failed to connect to serial port {self.port}: {e}")
            raise
        finally:
            if ser and ser.is_open:
                ser.close()
                self.logger.info(f"Closed serial port {self.port}")
    
    def parse_wind_data(self, data_line):
        """
        Parse Davis wind sensor data from serial input
        Expected format from Arduino: "wind: iteration potvalue rpmtops rpmraw"
        Where:
        - iteration: counter (ignored)
        - potvalue: raw potentiometer value (0-1024) for direction
        - rpmtops: debounced RPM count for wind speed
        - rpmraw: raw RPM count (debug)
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
                # Base calculation: (0-1024 maps to 0-360 degrees)
                direction_deg = (pot_value / 1024.0) * 360.0
                
                # Apply direction scaling and offset calibration
                direction_deg = (direction_deg * self.direction_scale + self.direction_offset) % 360.0
                
                # Ensure direction is in 0-360 range
                if direction_deg < 0:
                    direction_deg += 360.0
                
                # Convert RPM to wind speed using Davis anemometer calibration
                # This conversion depends on your specific anemometer calibration
                # Common formula: Wind Speed (m/s) = (RPM * circumference) / 60
                # For Davis anemometer, typical calibration is: speed = RPM * 0.098 (m/s)
                speed_mps = rpm_tops * DEFAULT_RPM_TO_MPS * self.calibration_factor
                
                # Convert speed from m/s to knots
                speed_knots = speed_mps * MPS_TO_KNOTS
                
                # Calculate rotations per second for debug
                rps = rpm_tops / 60.0 if rpm_tops > 0 else 0.0
                
                return {
                    'iteration': iteration,
                    'wind_speed_mps': speed_mps,
                    'wind_speed_knots': speed_knots,
                    'wind_direction_deg': direction_deg,
                    'rotations_per_second': rps,
                    'rpm_tops': rpm_tops,
                    'rpm_raw': rpm_raw,
                    'pot_value': pot_value
                }
                    
            except (ValueError, IndexError) as e:
                self.logger.debug(f"Failed to parse Davis data: {e}")
                return None
        
        self.logger.debug(f"Could not parse Davis data line: {data_line}")
        return None
    



def run_auto_calibration(args, logger):
    """Run automatic Tempest calibration and return calibration factors"""
    logger.info("🎯 Starting automatic Tempest calibration...")
    logger.info("=" * 50)
    
    # Setup firewall if not disabled
    firewall_manager = None
    if not args.no_firewall:
        try:
            firewall_manager = FirewallManager()
            logger.info("Setting up firewall for Tempest UDP broadcasts...")
            if not firewall_manager.setup_firewall():
                logger.warning("⚠️  Firewall setup may be incomplete")
            else:
                logger.info("✅ Firewall setup completed successfully")
        except Exception as e:
            logger.warning(f"Could not setup firewall: {e}")
    else:
        logger.info("Firewall setup skipped (--no-firewall specified)")
    
    logger.info("")
    
    # Start UDP listener thread
    logger.info("🌐 Starting Tempest UDP listener...")
    udp_thread = threading.Thread(target=tempest_udp_listener, daemon=True)
    udp_thread.start()
    
    # Wait for initial Tempest data
    logger.info("⏳ Waiting for Tempest UDP broadcasts...")
    tempest_found = False
    wait_start = time.time()
    wait_timeout = 30  # 30 seconds to detect Tempest
    
    while time.time() - wait_start < wait_timeout:
        tempest_wind = get_current_tempest_wind()
        if tempest_wind:
            tempest_found = True
            logger.info(f"✅ Tempest detected! Current reading: {tempest_wind['wind_speed_knots']:.1f} knots, {tempest_wind['wind_direction_deg']:.0f}° ({tempest_wind['source']})")
            break
        time.sleep(1)
    
    if not tempest_found:
        logger.warning("⚠️  No Tempest data received within 30 seconds")
        logger.info("💡 Make sure:")
        logger.info("   - Tempest weather station is powered on and broadcasting")
        logger.info("   - You're on the same network as the Tempest station")
        logger.info("   - Firewall allows UDP traffic on port 50222")
        logger.info("   - Try running: python3 tempest.py --test-connection")
        return None, None
    
    # Initialize wind sensor reader for data collection
    logger.info("🌪️  Initializing Davis wind sensor for calibration data collection...")
    wind_reader = WindSensorReader(
        port=args.port,
        baudrate=args.baudrate,
        timeout=args.timeout,
        calibration_factor=1.0,  # Use uncalibrated values for comparison
        direction_offset=0.0,
        direction_scale=args.direction_scale
    )
    
    # Collect calibration data
    davis_readings = []
    tempest_readings = []
    samples_collected = 0
    start_time = time.time()
    
    logger.info(f"📊 Collecting {args.calibration_samples} comparison samples...")
    logger.info(f"⏱️  Taking one sample every {args.calibration_interval} seconds")
    logger.info(f"⏰ Maximum calibration time: {args.calibration_timeout} seconds")
    logger.info("")
    
    try:
        with wind_reader.serial_connection() as ser:
            while samples_collected < args.calibration_samples:
                # Check timeout
                if time.time() - start_time > args.calibration_timeout:
                    logger.error(f"❌ Calibration timeout after {args.calibration_timeout} seconds")
                    break
                
                # Get Davis reading
                logger.debug("📡 Reading data from Davis sensor...")
                line = ser.readline().decode('utf-8', errors='ignore')
                davis_data = wind_reader.parse_wind_data(line.strip()) if line.strip() else None
                
                if davis_data:
                    # Get corresponding Tempest reading
                    tempest_data = get_current_tempest_wind()
                    
                    if tempest_data:
                        davis_readings.append(davis_data)
                        tempest_readings.append(tempest_data)
                        samples_collected += 1
                        
                        logger.info(f"📝 Sample {samples_collected}/{args.calibration_samples}: "
                                   f"Davis: {davis_data['wind_speed_knots']:.2f} knots, {davis_data['wind_direction_deg']:.1f}° | "
                                   f"Tempest: {tempest_data['wind_speed_knots']:.2f} knots, {tempest_data['wind_direction_deg']:.1f}°")
                        
                        # Wait before next sample
                        if samples_collected < args.calibration_samples:
                            time.sleep(args.calibration_interval)
                    else:
                        logger.debug("⚠️  No Tempest data available, retrying...")
                        time.sleep(1)
                else:
                    logger.debug("⚠️  Invalid Davis reading, retrying...")
    
    except Exception as e:
        logger.error(f"❌ Error during data collection: {e}")
        return None, None
    
    # Calculate calibration factors
    if samples_collected < 3:
        logger.warning(f"⚠️  Insufficient samples collected ({samples_collected}), need at least 3 for reliable calibration")
        return None, None
    
    logger.info("")
    logger.info(f"🧮 Calculating calibration factors from {samples_collected} samples...")
    
    calibration_result = calculate_calibration_factors(davis_readings, tempest_readings)
    
    if not calibration_result:
        logger.error("❌ Could not calculate calibration factors")
        return None, None
    
    # Check calibration confidence
    speed_confidence = calibration_result['speed_confidence']
    direction_confidence = calibration_result['direction_confidence']
    min_confidence = args.min_calibration_confidence
    
    logger.info("")
    logger.info("=" * 60)
    logger.info("🎯 AUTOMATIC TEMPEST CALIBRATION RESULTS")
    logger.info("=" * 60)
    logger.info(f"Speed calibration factor: {calibration_result['speed_calibration_factor']:.4f}")
    logger.info(f"Direction offset: {calibration_result['direction_offset']:.2f}°")
    logger.info(f"Speed confidence: {speed_confidence:.3f}")
    logger.info(f"Direction confidence: {direction_confidence:.3f}")
    logger.info(f"Sample count: {calibration_result['sample_count']}")
    logger.info("=" * 60)
    
    # Check if calibration meets confidence requirements
    if speed_confidence >= min_confidence and direction_confidence >= min_confidence:
        logger.info("✅ Calibration confidence meets requirements - applying automatically!")
        logger.info(f"📈 Applied speed factor: {calibration_result['speed_calibration_factor']:.4f}")
        logger.info(f"🧭 Applied direction offset: {calibration_result['direction_offset']:.2f}°")
        return calibration_result['speed_calibration_factor'], calibration_result['direction_offset']
    else:
        logger.warning(f"⚠️  Calibration confidence below threshold ({min_confidence:.2f})")
        logger.info("💡 Recommendations:")
        if speed_confidence < min_confidence:
            logger.info(f"   - Speed confidence too low ({speed_confidence:.3f}): try with more steady wind conditions")
        if direction_confidence < min_confidence:
            logger.info(f"   - Direction confidence too low ({direction_confidence:.3f}): check wind vane alignment")
        logger.info("   - Use --min-calibration-confidence to adjust threshold")
        logger.info("   - Manually specify calibration: --calibration-factor X.XXX --direction-offset Y.Y")
        
        return None, None


# ---------------- Continuous Calibration for Main Plugin ----------------
class ContinuousCalibrator:
    """Manages continuous calibration in background while main plugin runs"""
    
    def __init__(self, wind_reader, args, logger):
        self.wind_reader = wind_reader
        self.args = args
        self.logger = logger
        self.running = False
        self.thread = None
        
        # Calibration state
        self.current_speed_factor = wind_reader.calibration_factor
        self.current_direction_offset = wind_reader.direction_offset
        
        # Thread synchronization
        self.calibration_lock = threading.Lock()
        self.stop_event = threading.Event()
        
    def start(self):
        """Start continuous calibration in background thread"""
        if self.running:
            return
            
        self.logger.info("🔄 Starting continuous calibration background thread...")
        self.logger.info(f"   Calibration interval: {self.args.continuous_interval} seconds ({self.args.continuous_interval/60:.1f} minutes)")
        self.logger.info(f"   Samples per calibration: {self.args.continuous_samples}")
        self.logger.info(f"   Sample interval: {self.args.continuous_sample_interval} seconds")
        self.logger.info(f"   Confidence threshold: {self.args.continuous_confidence_threshold}")
        self.logger.info(f"   Adjustment rate: {self.args.continuous_adjustment_rate * 100:.0f}% per cycle")
        
        self.running = True
        self.thread = threading.Thread(target=self._continuous_calibration_loop, daemon=True)
        self.thread.start()
        
    def stop(self):
        """Stop continuous calibration"""
        if not self.running:
            return
            
        self.logger.info("🛑 Stopping continuous calibration...")
        self.stop_event.set()
        self.running = False
        
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=5)
            
        self.logger.info("📊 Final continuous calibration factors:")
        self.logger.info(f"   Speed factor: {self.current_speed_factor:.4f}")
        self.logger.info(f"   Direction offset: {self.current_direction_offset:.2f}°")
        
    def get_current_calibration(self):
        """Get current calibration factors (thread-safe)"""
        with self.calibration_lock:
            return self.current_speed_factor, self.current_direction_offset
            
    def _update_calibration(self, new_speed_factor, new_direction_offset):
        """Update calibration factors in wind reader (thread-safe)"""
        with self.calibration_lock:
            self.current_speed_factor = new_speed_factor
            self.current_direction_offset = new_direction_offset
            
            # Update the wind reader's calibration factors
            self.wind_reader.calibration_factor = new_speed_factor
            self.wind_reader.direction_offset = new_direction_offset
            
    def _collect_calibration_samples(self):
        """Collect calibration samples by reading from both sensors"""
        davis_readings = []
        tempest_readings = []
        samples_collected = 0
        
        self.logger.debug(f"📊 Collecting {self.args.continuous_samples} calibration samples...")
        
        start_time = time.time()
        timeout = self.args.continuous_samples * self.args.continuous_sample_interval * 3  # Generous timeout
        
        try:
            with self.wind_reader.serial_connection() as ser:
                while samples_collected < self.args.continuous_samples and not self.stop_event.is_set():
                    if time.time() - start_time > timeout:
                        self.logger.warning(f"⚠️  Continuous calibration sample collection timeout after {timeout} seconds")
                        break
                    
                    try:
                        # Read from Davis sensor with short timeout
                        ser.timeout = 2.0  # Short timeout for continuous mode
                        line = ser.readline().decode('utf-8', errors='ignore').strip()
                        if not line:
                            continue
                            
                        # Parse with current calibration factors to get raw readings
                        davis_data = self.wind_reader.parse_wind_data(line)
                        
                        if davis_data:
                            # Get corresponding Tempest reading
                            tempest_data = get_current_tempest_wind()
                            
                            if tempest_data:
                                # Convert Davis data back to raw readings for calibration calculation
                                raw_davis_data = {
                                    'wind_speed_knots': davis_data['wind_speed_knots'] / self.current_speed_factor,
                                    'wind_direction_deg': (davis_data['wind_direction_deg'] - self.current_direction_offset) % 360.0
                                }
                                
                                davis_readings.append(raw_davis_data)
                                tempest_readings.append(tempest_data)
                                samples_collected += 1
                                
                                self.logger.debug(f"   Sample {samples_collected}/{self.args.continuous_samples}: "
                                                f"Davis: {raw_davis_data['wind_speed_knots']:.1f} knots, {raw_davis_data['wind_direction_deg']:.0f}° | "
                                                f"Tempest: {tempest_data['wind_speed_knots']:.1f} knots, {tempest_data['wind_direction_deg']:.0f}°")
                                
                                # Wait before next sample (if not the last one)
                                if samples_collected < self.args.continuous_samples:
                                    if self.stop_event.wait(self.args.continuous_sample_interval):
                                        break  # Stop event was set
                            else:
                                if self.stop_event.wait(1):  # Short wait if no Tempest data
                                    break
                        else:
                            if self.stop_event.wait(0.5):  # Short wait if no valid Davis data
                                break
                                
                    except serial.SerialTimeoutException:
                        continue
                    except Exception as e:
                        self.logger.debug(f"⚠️  Error reading Davis sensor during continuous calibration: {e}")
                        if self.stop_event.wait(1):
                            break
                        continue
                        
        except Exception as e:
            self.logger.warning(f"⚠️  Error during continuous calibration sample collection: {e}")
            return [], []
            
        return davis_readings, tempest_readings
        
    def _continuous_calibration_loop(self):
        """Main continuous calibration loop running in background"""
        self.logger.info("🔄 Continuous calibration background thread started")
        
        # Wait for initial Tempest data
        tempest_ready = False
        for _ in range(30):  # Wait up to 30 seconds
            if self.stop_event.is_set():
                return
            tempest_data = get_current_tempest_wind()
            if tempest_data:
                tempest_ready = True
                self.logger.info(f"✅ Tempest detected for continuous calibration: {tempest_data['wind_speed_knots']:.1f} knots, {tempest_data['wind_direction_deg']:.0f}°")
                break
            time.sleep(1)
            
        if not tempest_ready:
            self.logger.warning("⚠️  No Tempest data available for continuous calibration - disabling continuous mode")
            return
            
        # Main continuous calibration loop
        while not self.stop_event.is_set():
            try:
                next_calibration_time = datetime.now() + timedelta(seconds=self.args.continuous_interval)
                
                self.logger.info(f"📊 Starting continuous calibration at {datetime.now().strftime('%H:%M:%S')}")
                self.logger.info(f"⏰ Next calibration scheduled for {next_calibration_time.strftime('%H:%M:%S')}")
                
                # Collect calibration samples
                davis_readings, tempest_readings = self._collect_calibration_samples()
                
                # Calculate new calibration if we have enough samples
                if len(davis_readings) >= 3:
                    self.logger.info(f"🧮 Calculating continuous calibration from {len(davis_readings)} samples...")
                    
                    calibration_result = calculate_calibration_factors(davis_readings, tempest_readings)
                    
                    if calibration_result:
                        new_speed_factor = calibration_result['speed_calibration_factor']
                        new_direction_offset = calibration_result['direction_offset']
                        speed_confidence = calibration_result['speed_confidence']
                        direction_confidence = calibration_result['direction_confidence']
                        
                        self.logger.info(f"📈 Calculated continuous calibration:")
                        self.logger.info(f"   Speed factor: {new_speed_factor:.4f} (confidence: {speed_confidence:.3f})")
                        self.logger.info(f"   Direction offset: {new_direction_offset:.2f}° (confidence: {direction_confidence:.3f})")
                        
                        # Apply calibration if confidence meets threshold
                        if (speed_confidence >= self.args.continuous_confidence_threshold and 
                            direction_confidence >= self.args.continuous_confidence_threshold):
                            
                            # Gradually adjust calibration to avoid sudden jumps
                            adjustment_rate = self.args.continuous_adjustment_rate
                            
                            adjusted_speed_factor = (
                                self.current_speed_factor * (1 - adjustment_rate) + 
                                new_speed_factor * adjustment_rate
                            )
                            adjusted_direction_offset = (
                                self.current_direction_offset * (1 - adjustment_rate) + 
                                new_direction_offset * adjustment_rate
                            )
                            
                            self._update_calibration(adjusted_speed_factor, adjusted_direction_offset)
                            
                            self.logger.info(f"✅ Applied continuous calibration adjustment:")
                            self.logger.info(f"   New speed factor: {adjusted_speed_factor:.4f}")
                            self.logger.info(f"   New direction offset: {adjusted_direction_offset:.2f}°")
                        else:
                            self.logger.info(f"⚠️  Low confidence - keeping current calibration")
                            self.logger.info(f"   Current speed factor: {self.current_speed_factor:.4f}")
                            self.logger.info(f"   Current direction offset: {self.current_direction_offset:.2f}°")
                    else:
                        self.logger.warning("⚠️  Could not calculate continuous calibration factors - keeping current calibration")
                else:
                    self.logger.warning(f"⚠️  Insufficient samples ({len(davis_readings)}) for continuous calibration - need at least 3")
                
                # Wait until next calibration time
                sleep_time = (next_calibration_time - datetime.now()).total_seconds()
                if sleep_time > 0:
                    self.logger.debug(f"⏳ Continuous calibration waiting {sleep_time:.0f} seconds until next cycle...")
                    if self.stop_event.wait(sleep_time):
                        break  # Stop event was set
                        
            except Exception as e:
                self.logger.error(f"❌ Error in continuous calibration loop: {e}")
                # Wait a bit before retrying
                if self.stop_event.wait(60):  # Wait 1 minute before retry
                    break
                    
        self.logger.info("🔄 Continuous calibration background thread stopped")


def main():
    args = parse_args()
    
    # Configure logging
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    logger = logging.getLogger(__name__)
    
    # Initialize Waggle plugin
    plugin = Plugin()
    
    # Auto-calibration with Tempest if requested
    calibration_factor = args.calibration_factor
    direction_offset = args.direction_offset
    
    if args.auto_calibrate:
        logger.info("🎯 Auto-calibration requested - starting Tempest calibration...")
        
        # Run auto-calibration
        auto_cal_factor, auto_direction_offset = run_auto_calibration(args, logger)
        
        if auto_cal_factor is not None and auto_direction_offset is not None:
            # Apply auto-calibration results
            calibration_factor = auto_cal_factor
            direction_offset = auto_direction_offset
            
            logger.info("✅ Auto-calibration successful!")
            logger.info(f"   Applied speed factor: {calibration_factor:.4f}")
            logger.info(f"   Applied direction offset: {direction_offset:.2f}°")
        else:
            logger.info("⚠️  Auto-calibration setup completed, using manual calibration values")
            logger.info("💡 Use standalone calibration utility for full calibration: python3 tempest.py --calibrate")
        
        logger.info("")
    
    # Initialize wind sensor reader
    wind_reader = WindSensorReader(
        port=args.port,
        baudrate=args.baudrate,
        timeout=args.timeout,
        calibration_factor=calibration_factor,
        direction_offset=direction_offset,
        direction_scale=args.direction_scale
    )
    
    logger.info(f"Starting wind sensor plugin on port {args.port}")
    logger.info(f"Wind speed calibration factor: {calibration_factor}")
    logger.info(f"Wind direction offset: {direction_offset}°")
    logger.info(f"Wind direction scale: {args.direction_scale}")
    logger.info(f"MQTT reporting interval: {args.reporting_interval} seconds")
    
    # Initialize data collector for averaged reporting
    data_collector = WindDataCollector(args.reporting_interval)
    
    # Initialize continuous calibration if requested
    continuous_calibrator = None
    if args.continuous_calibration:
        logger.info("🔄 Continuous calibration mode enabled")
        
        # Start Tempest UDP listener for continuous calibration
        if not args.no_firewall:
            firewall_manager_continuous = FirewallManager()
            logger.info("Setting up firewall for continuous calibration Tempest UDP broadcasts...")
            if not firewall_manager_continuous.setup_firewall():
                logger.warning("⚠️  Firewall setup may be incomplete for continuous calibration")
            else:
                logger.info("✅ Firewall setup completed for continuous calibration")
        
        # Start UDP listener thread for continuous calibration
        udp_thread_continuous = threading.Thread(target=tempest_udp_listener, daemon=True)
        udp_thread_continuous.start()
        logger.info("🌐 Started Tempest UDP listener for continuous calibration")
        
        # Initialize continuous calibrator
        continuous_calibrator = ContinuousCalibrator(wind_reader, args, logger)
        
        # Wait a moment for Tempest data, then start continuous calibration
        logger.info("⏳ Waiting briefly for Tempest data before starting continuous calibration...")
        time.sleep(5)
        continuous_calibrator.start()

    
    # Start web server if requested
    if args.web_server:
        web_thread = threading.Thread(
            target=start_web_server, 
            args=(args.web_port, logger),
            daemon=True
        )
        web_thread.start()
        logger.info(f"Web monitoring enabled on port {args.web_port}")
    
    logger.info("Waiting for data from Davis wind sensor...")
    logger.info(f"Environmental data will be averaged and published every {args.reporting_interval} seconds")
    
    try:
        # Update global status
        global latest_data
        latest_data["status"] = "connecting"
        

        
        # Main loop with automatic reconnection
        while True:
            try:
                # Continuously read and process data as it arrives
                with wind_reader.serial_connection() as ser:
                    logger.info("Connected to serial port, reading data continuously...")
                    latest_data["status"] = "running"
                    
                    while True:
                        try:
                            # Block waiting for a line of data
                            line = ser.readline().decode('utf-8', errors='ignore')
                            
                            if line.strip():  # Only process non-empty lines
                                logger.debug(f"Raw serial data: {line.strip()}")
                                
                                # Update global data for web server
                                latest_data["raw_line"] = line.strip()
                                latest_data["timestamp"] = datetime.now()
                                
                                wind_data = wind_reader.parse_wind_data(line)
                                
                                if wind_data:
                                    # Update global data for web server (immediate/real-time)
                                    latest_data["wind_data"] = wind_data
                                    latest_data["total_readings"] += 1
                                    latest_data["readings_since_report"] += 1
                                    
                                    # Add reading to data collector for averaging
                                    data_collector.add_reading(wind_data)
                                    

                                    
                                    # Immediate debug measurements - Davis-specific data (for web interface)
                                    plugin.publish("davis.wind.rps", wind_data['rotations_per_second'], 
                                                 meta={"units": "rps", "description": "Wind sensor rotations per second"})
                                    plugin.publish("davis.wind.rpm.tops", wind_data['rpm_tops'], 
                                                 meta={"units": "rpm", "description": "Debounced RPM count"})
                                    plugin.publish("davis.wind.rpm.raw", wind_data['rpm_raw'], 
                                                 meta={"units": "rpm", "description": "Raw RPM count"})
                                    plugin.publish("davis.wind.pot.value", wind_data['pot_value'], 
                                                 meta={"units": "counts", "description": "Raw potentiometer value for direction"})
                                    plugin.publish("davis.wind.iteration", wind_data['iteration'], 
                                                 meta={"units": "count", "description": "Arduino iteration counter"})
                                    
                                    # Publish immediate sensor status as OK
                                    plugin.publish("davis.wind.sensor_status", 1, 
                                                 meta={"description": "Davis wind sensor status (0=error, 1=ok)"})
                                    
                                    # Check if it's time to publish averaged environmental data
                                    if data_collector.should_report():
                                        averaged_data = data_collector.get_averaged_data()
                                        if averaged_data:
                                            # Publish averaged environmental measurements
                                            plugin.publish("env.wind.speed", averaged_data['avg_wind_speed_knots'], 
                                                         meta={"units": "knots", "description": "Average wind speed in knots", "interval_seconds": str(averaged_data['interval_seconds']), "sample_count": str(averaged_data['sample_count'])})
                                            plugin.publish("env.wind.direction", averaged_data['avg_wind_direction_deg'], 
                                                         meta={"units": "degrees", "description": "Average wind direction in degrees", "interval_seconds": str(averaged_data['interval_seconds']), "sample_count": str(averaged_data['sample_count'])})
                                            plugin.publish("env.wind.speed.mps", averaged_data['avg_wind_speed_mps'], 
                                                         meta={"units": "m/s", "description": "Average wind speed in meters per second", "interval_seconds": str(averaged_data['interval_seconds']), "sample_count": str(averaged_data['sample_count'])})
                                            
                                            # Wind speed min/max (lull and gust)
                                            plugin.publish("env.wind.speed.min", averaged_data['min_wind_speed_knots'], 
                                                         meta={"units": "knots", "description": "Minimum wind speed (lull) during interval", "interval_seconds": str(averaged_data['interval_seconds']), "sample_count": str(averaged_data['sample_count'])})
                                            plugin.publish("env.wind.speed.max", averaged_data['max_wind_speed_knots'], 
                                                         meta={"units": "knots", "description": "Maximum wind speed (gust) during interval", "interval_seconds": str(averaged_data['interval_seconds']), "sample_count": str(averaged_data['sample_count'])})
                                            plugin.publish("env.wind.speed.min.mps", averaged_data['min_wind_speed_mps'], 
                                                         meta={"units": "m/s", "description": "Minimum wind speed (lull) in m/s during interval", "interval_seconds": str(averaged_data['interval_seconds']), "sample_count": str(averaged_data['sample_count'])})
                                            plugin.publish("env.wind.speed.max.mps", averaged_data['max_wind_speed_mps'], 
                                                         meta={"units": "m/s", "description": "Maximum wind speed (gust) in m/s during interval", "interval_seconds": str(averaged_data['interval_seconds']), "sample_count": str(averaged_data['sample_count'])})
                                            
                                            # Additional averaged metrics
                                            plugin.publish("env.wind.consistency", averaged_data['wind_consistency'], 
                                                         meta={"units": "ratio", "description": "Wind direction consistency (1.0=steady, 0.0=highly variable)", "interval_seconds": str(averaged_data['interval_seconds']), "sample_count": str(averaged_data['sample_count'])})
                                            
                                            latest_data["last_mqtt_report"] = datetime.now()
                                            latest_data["readings_since_report"] = 0
                                            
                                            # Get current Tempest data for comparison logging
                                            current_tempest = get_current_tempest_wind()
                                            
                                            logger.info(f"Published averaged data: {averaged_data['avg_wind_speed_knots']:.2f} knots "
                                                       f"(min: {averaged_data['min_wind_speed_knots']:.2f}, max: {averaged_data['max_wind_speed_knots']:.2f}), "
                                                       f"{averaged_data['avg_wind_direction_deg']:.1f}° "
                                                       f"(samples: {averaged_data['sample_count']}, consistency: {averaged_data['wind_consistency']:.3f})")
                                            
                                            # Log Tempest comparison data if available
                                            if current_tempest:
                                                logger.info(f"Tempest comparison data: {current_tempest['wind_speed_knots']:.2f} knots, "
                                                           f"{current_tempest['wind_direction_deg']:.1f}° "
                                                           f"(source: {current_tempest['source']}, "
                                                           f"diff: speed={current_tempest['wind_speed_knots'] - averaged_data['avg_wind_speed_knots']:+.2f}kt, "
                                                           f"direction={((current_tempest['wind_direction_deg'] - averaged_data['avg_wind_direction_deg'] + 180) % 360) - 180:+.1f}°)")
                                            else:
                                                logger.info("Tempest comparison data: Not available")
                                            
                                            # Reset collector for next interval
                                            data_collector.reset_collection()
                                    
                                    # Log individual reading for debugging/monitoring
                                    logger.debug(f"Reading: {wind_data['wind_speed_knots']:.2f} knots, "
                                               f"{wind_data['wind_direction_deg']:.1f}° "
                                               f"(samples in interval: {data_collector.sample_count})")
                                    
                                    if args.debug:
                                        logger.debug(f"Debug - Iteration: {wind_data['iteration']}, "
                                                    f"PotValue: {wind_data['pot_value']}, "
                                                    f"RPM Tops: {wind_data['rpm_tops']}, "
                                                    f"RPM Raw: {wind_data['rpm_raw']}, "
                                                    f"RPS: {wind_data['rotations_per_second']:.3f}, "
                                                    f"Speed (m/s): {wind_data['wind_speed_mps']:.2f}")
                                else:
                                    logger.debug(f"Could not parse line: {line.strip()}")
                                    latest_data["error_count"] += 1
                                    
                        except serial.SerialTimeoutException:
                            logger.debug("Serial read timeout, continuing...")
                            continue
                        except serial.SerialException as e:
                            logger.error(f"Serial communication error: {e}")
                            raise  # Re-raise to trigger reconnection
                            
            except (serial.SerialException, OSError) as e:
                logger.error(f"Serial port error: {e}")
                latest_data["status"] = "error"
                latest_data["error_count"] += 1
                
                # Publish error status
                plugin.publish("davis.wind.sensor_status", 0, 
                             meta={"description": "Davis wind sensor status (0=error, 1=ok)"})
                logger.info("Attempting to reconnect in 5 seconds...")
                latest_data["status"] = "reconnecting"
                time.sleep(5.0)
                continue
                
    except KeyboardInterrupt:
        logger.info("Wind sensor plugin stopped by user")
        if continuous_calibrator:
            continuous_calibrator.stop()
    except Exception as e:
        logger.error(f"Unexpected error in wind sensor plugin: {e}")
        if continuous_calibrator:
            continuous_calibrator.stop()
        raise
    finally:
        # Ensure continuous calibration is stopped on any exit
        if continuous_calibrator:
            continuous_calibrator.stop()


if __name__ == "__main__":
    main() 
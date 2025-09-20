#!/usr/bin/env python3

import argparse
import logging
import math
import time
import serial
import re
import json
import threading
from datetime import datetime, timedelta
from contextlib import contextmanager
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from waggle.plugin import Plugin


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
    
    def add_reading(self, wind_data):
        """Add a new wind reading to the collection"""
        self.wind_speeds_mps.append(wind_data['wind_speed_mps'])
        self.wind_speeds_knots.append(wind_data['wind_speed_knots'])
        self.wind_directions_deg.append(wind_data['wind_direction_deg'])
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
        
        averaged_data = {
            'avg_wind_speed_mps': avg_speed_mps,
            'avg_wind_speed_knots': avg_speed_knots, 
            'avg_wind_direction_deg': avg_direction_deg,
            'wind_consistency': wind_consistency,
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
    
    # Initialize wind sensor reader
    wind_reader = WindSensorReader(
        port=args.port,
        baudrate=args.baudrate,
        timeout=args.timeout,
        calibration_factor=args.calibration_factor,
        direction_offset=args.direction_offset,
        direction_scale=args.direction_scale
    )
    
    logger.info(f"Starting wind sensor plugin on port {args.port}")
    logger.info(f"Wind speed calibration factor: {args.calibration_factor}")
    logger.info(f"Wind direction offset: {args.direction_offset}°")
    logger.info(f"Wind direction scale: {args.direction_scale}")
    logger.info(f"MQTT reporting interval: {args.reporting_interval} seconds")
    
    # Initialize data collector for averaged reporting
    data_collector = WindDataCollector(args.reporting_interval)
    
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
                                            
                                            # Additional averaged metrics
                                            plugin.publish("env.wind.consistency", averaged_data['wind_consistency'], 
                                                         meta={"units": "ratio", "description": "Wind direction consistency (1.0=steady, 0.0=highly variable)", "interval_seconds": str(averaged_data['interval_seconds']), "sample_count": str(averaged_data['sample_count'])})
                                            
                                            latest_data["last_mqtt_report"] = datetime.now()
                                            latest_data["readings_since_report"] = 0
                                            
                                            logger.info(f"Published averaged data: {averaged_data['avg_wind_speed_knots']:.2f} knots, "
                                                       f"{averaged_data['avg_wind_direction_deg']:.1f}° "
                                                       f"(samples: {averaged_data['sample_count']}, consistency: {averaged_data['wind_consistency']:.3f})")
                                            
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
    except Exception as e:
        logger.error(f"Unexpected error in wind sensor plugin: {e}")
        raise


if __name__ == "__main__":
    main() 
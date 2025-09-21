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

try:
    from bs4 import BeautifulSoup
    HAS_BEAUTIFULSOUP = True
except ImportError:
    HAS_BEAUTIFULSOUP = False

# Import Tempest calibration functionality
try:
    import tempest
    HAS_TEMPEST = True
except ImportError:
    HAS_TEMPEST = False


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


class TempestCalibrator:
    """Calibration helper using Tempest weather station data"""
    
    def __init__(self, station_id, logger):
        self.station_id = station_id
        self.logger = logger
        self.base_url = f"https://tempestwx.com/station/{station_id}"
        self.api_url = f"https://swd.weatherflow.com/swd/rest/observations/station/{station_id}"
        self.has_beautifulsoup = HAS_BEAUTIFULSOUP
        
    def fetch_tempest_data(self):
        """Fetch current wind data from Tempest station"""
        try:
            # Try the WeatherFlow API first
            headers = {'User-Agent': 'Davis-Wind-Sensor-Plugin/1.0'}
            response = requests.get(self.api_url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                if 'obs' in data and len(data['obs']) > 0:
                    latest_obs = data['obs'][0]  # Most recent observation
                    
                    # WeatherFlow API format: [timestamp, wind_lull, wind_avg, wind_gust, wind_direction, ...]
                    if len(latest_obs) >= 5:
                        wind_speed_mps = latest_obs[2]  # wind_avg in m/s
                        wind_direction = latest_obs[4]  # wind_direction in degrees
                        wind_gust_mps = latest_obs[3]   # wind_gust in m/s
                        
                        # Convert m/s to knots
                        wind_speed_knots = wind_speed_mps * 1.94384
                        wind_gust_knots = wind_gust_mps * 1.94384
                        
                        # WeatherFlow API returns UTC timestamps
                        utc_timestamp = datetime.fromtimestamp(latest_obs[0], tz=timezone.utc)
                        local_timestamp = utc_timestamp.astimezone()
                        
                        return {
                            'wind_speed_mps': wind_speed_mps,
                            'wind_speed_knots': wind_speed_knots,
                            'wind_direction_deg': wind_direction,
                            'wind_gust_knots': wind_gust_knots,
                            'timestamp_utc': utc_timestamp,
                            'timestamp_local': local_timestamp,
                            'timestamp': local_timestamp,  # For backward compatibility
                            'data_age_seconds': (datetime.now(timezone.utc) - utc_timestamp).total_seconds(),
                            'source': 'tempest_api'
                        }
            
            self.logger.debug(f"Could not fetch Tempest data via API (status: {response.status_code})")
            # Fallback to web scraping
            return self._scrape_tempest_webpage()
            
        except requests.RequestException as e:
            self.logger.debug(f"API request failed: {e}, trying web scraping")
            return self._scrape_tempest_webpage()
        except (KeyError, IndexError, ValueError) as e:
            self.logger.debug(f"Error parsing API data: {e}, trying web scraping")
            return self._scrape_tempest_webpage()
    
    def _scrape_tempest_webpage(self):
        """Scrape wind data from Tempest public webpage as fallback"""
        if not self.has_beautifulsoup:
            self.logger.error("BeautifulSoup4 not available for web scraping. Install with: pip install beautifulsoup4")
            return None
        
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            response = requests.get(self.base_url, headers=headers, timeout=15)
            
            if response.status_code != 200:
                self.logger.error(f"Could not fetch Tempest webpage (status: {response.status_code})")
                return None
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Look for wind data in the page
            wind_speed_mph = None
            wind_direction = None
            wind_gust_mph = None
            
            # Try to find wind speed and direction data
            # Tempest pages often have data in script tags or data attributes
            
            # Method 1: Look for wind data in text content
            page_text = soup.get_text()
            
            # Look for wind speed patterns (mph)
            wind_speed_match = re.search(r'Wind.*?(\d+(?:\.\d+)?)\s*mph', page_text, re.IGNORECASE)
            if wind_speed_match:
                wind_speed_mph = float(wind_speed_match.group(1))
            
            # Look for wind direction patterns
            wind_dir_match = re.search(r'(?:Wind.*?Direction.*?|Direction.*?)(\d+(?:\.\d+)?)\s*°?', page_text, re.IGNORECASE)
            if wind_dir_match:
                wind_direction = float(wind_dir_match.group(1))
            
            # Look for gust patterns
            gust_match = re.search(r'Gust.*?(\d+(?:\.\d+)?)\s*mph', page_text, re.IGNORECASE)
            if gust_match:
                wind_gust_mph = float(gust_match.group(1))
            
            # Method 2: Look in script tags for JSON data
            if wind_speed_mph is None or wind_direction is None:
                scripts = soup.find_all('script')
                for script in scripts:
                    if script.string and 'wind' in script.string.lower():
                        # Try to extract wind data from JavaScript variables
                        wind_speed_js = re.search(r'wind.*?speed.*?["\']?(\d+(?:\.\d+)?)', script.string, re.IGNORECASE)
                        wind_dir_js = re.search(r'wind.*?dir.*?["\']?(\d+(?:\.\d+)?)', script.string, re.IGNORECASE)
                        
                        if wind_speed_js and wind_speed_mph is None:
                            wind_speed_mph = float(wind_speed_js.group(1))
                        if wind_dir_js and wind_direction is None:
                            wind_direction = float(wind_dir_js.group(1))
            
            # Method 3: Look for data attributes and specific elements
            if wind_speed_mph is None or wind_direction is None:
                # Look for elements with wind-related classes or data attributes
                wind_elements = soup.find_all(attrs={'class': re.compile(r'wind', re.I)})
                wind_elements.extend(soup.find_all(attrs={'data-wind': True}))
                
                for element in wind_elements:
                    text = element.get_text()
                    if 'mph' in text.lower() and wind_speed_mph is None:
                        speed_match = re.search(r'(\d+(?:\.\d+)?)', text)
                        if speed_match:
                            wind_speed_mph = float(speed_match.group(1))
                    
                    if '°' in text and wind_direction is None:
                        dir_match = re.search(r'(\d+(?:\.\d+)?)', text)
                        if dir_match:
                            wind_direction = float(dir_match.group(1))
            
            if wind_speed_mph is not None and wind_direction is not None:
                # Convert mph to m/s and knots
                wind_speed_mps = wind_speed_mph * 0.44704  # mph to m/s
                wind_speed_knots = wind_speed_mph * 0.868976  # mph to knots
                
                wind_gust_knots = None
                if wind_gust_mph is not None:
                    wind_gust_knots = wind_gust_mph * 0.868976
                
                current_time = datetime.now(timezone.utc)
                
                self.logger.info(f"Successfully scraped Tempest data: {wind_speed_mph:.1f} mph ({wind_speed_knots:.1f} knots), {wind_direction:.0f}°")
                
                return {
                    'wind_speed_mps': wind_speed_mps,
                    'wind_speed_knots': wind_speed_knots,
                    'wind_direction_deg': wind_direction,
                    'wind_gust_knots': wind_gust_knots,
                    'timestamp_utc': current_time,
                    'timestamp_local': current_time.astimezone(),
                    'timestamp': current_time.astimezone(),
                    'data_age_seconds': 0.0,  # Assume current for scraped data
                    'source': 'tempest_webpage'
                }
            else:
                self.logger.warning(f"Could not extract wind data from Tempest webpage. Found speed: {wind_speed_mph}, direction: {wind_direction}")
                return None
                
        except requests.RequestException as e:
            self.logger.error(f"Error scraping Tempest webpage: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Error parsing Tempest webpage: {e}")
            return None
    
    def calculate_calibration(self, davis_readings, tempest_readings):
        """Calculate calibration factors based on Davis vs Tempest comparison"""
        if not davis_readings or not tempest_readings:
            return None
        
        # Calculate average differences
        speed_ratios = []
        direction_diffs = []
        
        for davis, tempest in zip(davis_readings, tempest_readings):
            if davis['wind_speed_knots'] > 0.1 and tempest['wind_speed_knots'] > 0.1:
                speed_ratio = tempest['wind_speed_knots'] / davis['wind_speed_knots']
                speed_ratios.append(speed_ratio)
            
            # Calculate direction difference (handle wrap-around)
            dir_diff = tempest['wind_direction_deg'] - davis['wind_direction_deg']
            if dir_diff > 180:
                dir_diff -= 360
            elif dir_diff < -180:
                dir_diff += 360
            direction_diffs.append(dir_diff)
        
        if not speed_ratios:
            return None
        
        # Calculate recommended calibration values
        avg_speed_ratio = sum(speed_ratios) / len(speed_ratios)
        avg_direction_offset = sum(direction_diffs) / len(direction_diffs)
        
        # Calculate confidence metrics
        speed_std = (sum((r - avg_speed_ratio) ** 2 for r in speed_ratios) / len(speed_ratios)) ** 0.5
        direction_std = (sum((d - avg_direction_offset) ** 2 for d in direction_diffs) / len(direction_diffs)) ** 0.5
        
        return {
            'speed_calibration_factor': avg_speed_ratio,
            'direction_offset': avg_direction_offset,
            'speed_confidence': 1.0 / (1.0 + speed_std),  # Higher is better
            'direction_confidence': 1.0 / (1.0 + direction_std / 10.0),  # Scale direction std
            'sample_count': len(speed_ratios),
            'speed_std_dev': speed_std,
            'direction_std_dev': direction_std
        }


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
    if not HAS_TEMPEST:
        logger.error("Tempest module not available for auto-calibration")
        return None, None
    
    logger.info("🎯 Starting automatic Tempest calibration...")
    logger.info("=" * 50)
    
    # Setup firewall if not disabled
    firewall_manager = None
    if not args.no_firewall:
        try:
            firewall_manager = tempest.FirewallManager()
            if not firewall_manager.setup_firewall():
                logger.warning("⚠️  Firewall setup may be incomplete")
        except Exception as e:
            logger.warning(f"Could not setup firewall: {e}")
    
    # Start UDP listener for Tempest data
    logger.info("Setting up UDP listener for Tempest broadcasts...")
    udp_thread = threading.Thread(target=tempest.udp_listener, daemon=True)
    udp_thread.start()
    
    # Wait for initial data
    time.sleep(3)
    
    # Collect calibration samples
    davis_readings = []
    tempest_readings = []
    start_time = time.time()
    
    logger.info(f"Collecting {args.calibration_samples} calibration samples...")
    logger.info("Make sure both Davis and Tempest sensors are experiencing the same wind conditions")
    logger.info("")
    
    for i in range(args.calibration_samples):
        # Check timeout
        if time.time() - start_time > args.calibration_timeout:
            logger.error(f"❌ Calibration timeout after {args.calibration_timeout} seconds")
            break
        
        logger.info(f"Collecting sample {i+1}/{args.calibration_samples}...")
        
        # Get current Tempest data
        tempest_wind = tempest.get_current_tempest_wind()
        if not tempest_wind:
            logger.warning("⚠️  No Tempest data available, retrying...")
            time.sleep(2)
            continue
        
        logger.info(f"Tempest: {tempest_wind['wind_speed_knots']:.1f} knots, {tempest_wind['wind_direction_deg']:.0f}° ({tempest_wind['source']})")
        
        # We need to get a Davis reading at this point
        # For auto-calibration, we'll collect the next available Davis reading
        logger.info("Waiting for Davis reading...")
        
        # Note: In a real implementation, you'd want to collect the Davis reading here
        # For now, we'll simulate it by prompting the user or collecting from the sensor
        # This is a placeholder - in practice you'd integrate this with the actual sensor reading
        logger.info("📝 Note: Auto-calibration requires manual Davis readings for comparison")
        logger.info(f"   Current Tempest: {tempest_wind['wind_speed_knots']:.1f} knots, {tempest_wind['wind_direction_deg']:.0f}°")
        logger.info(f"   Please note your Davis reading and use manual calibration for now")
        
        # For now, skip the automated collection and return None
        # This would need integration with the actual Davis sensor reading loop
        break
    
    # Cleanup firewall
    if firewall_manager:
        firewall_manager.cleanup()
    
    logger.warning("⚠️  Auto-calibration feature requires integration with live Davis readings")
    logger.info("💡 Alternative: Use the standalone Tempest calibration utility:")
    logger.info("   python3 tempest.py --calibrate")
    logger.info("")
    
    return None, None

def run_manual_tempest_calibration(args, logger, davis_speed, davis_direction):
    """Run Tempest calibration with manual Davis reading input"""
    if not HAS_TEMPEST:
        return None, None
    
    # Get current Tempest data
    tempest_wind = tempest.get_current_tempest_wind()
    if not tempest_wind:
        return None, None
    
    # Create reading pairs for calibration
    davis_readings = [{
        'wind_speed_knots': davis_speed,
        'wind_direction_deg': davis_direction
    }]
    tempest_readings = [tempest_wind]
    
    # Calculate calibration factors
    calibration = tempest.calculate_calibration_factors(davis_readings, tempest_readings)
    
    if calibration and calibration['sample_count'] > 0:
        logger.info(f"📊 Calibration calculated from comparison:")
        logger.info(f"   Davis: {davis_speed:.1f} knots, {davis_direction:.0f}°")
        logger.info(f"   Tempest: {tempest_wind['wind_speed_knots']:.1f} knots, {tempest_wind['wind_direction_deg']:.0f}°")
        logger.info(f"   Speed factor: {calibration['speed_calibration_factor']:.4f}")
        logger.info(f"   Direction offset: {calibration['direction_offset']:.2f}°")
        
        return calibration['speed_calibration_factor'], calibration['direction_offset']
    
    return None, None

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
        
        if not HAS_TEMPEST:
            logger.error("❌ Tempest module not available for auto-calibration")
            logger.info("💡 Install requirements: pip install flask")
            logger.info("💡 Alternative: Use standalone calibration: python3 tempest.py --calibrate")
        else:
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
                logger.warning("⚠️  Auto-calibration failed, using manual calibration values")
                logger.info("💡 Use standalone calibration utility: python3 tempest.py --calibrate")
        
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
    
    # Initialize Tempest calibrator if requested
    tempest_calibrator = None
    if args.tempest_station:
        tempest_calibrator = TempestCalibrator(args.tempest_station, logger)
        logger.info(f"Tempest calibration enabled using station {args.tempest_station}")
        logger.info(f"Tempest station URL: https://tempestwx.com/station/{args.tempest_station}")
        logger.info(f"System timezone: {datetime.now().astimezone().tzinfo}")
        logger.info(f"Tempest data timezone: UTC (converted to local for comparison)")
        if args.tempest_calibration:
            logger.info(f"Automatic calibration mode: will collect {args.calibration_samples} samples")
            logger.info("Note: Calibration compares real-time readings, timezone differences are handled automatically")
    
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
        
        # Tempest calibration data collection
        calibration_data = {
            'davis_readings': [],
            'tempest_readings': [],
            'samples_collected': 0,
            'calibration_active': args.tempest_calibration,
            'calibration_complete': False
        }
        
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
                                    
                                    # Tempest calibration data collection
                                    if (tempest_calibrator and calibration_data['calibration_active'] and 
                                        not calibration_data['calibration_complete']):
                                        
                                        # Fetch current Tempest data
                                        tempest_data = tempest_calibrator.fetch_tempest_data()
                                        if tempest_data:
                                            calibration_data['davis_readings'].append(wind_data)
                                            calibration_data['tempest_readings'].append(tempest_data)
                                            calibration_data['samples_collected'] += 1
                                            
                                            logger.info(f"Calibration sample {calibration_data['samples_collected']}/{args.calibration_samples}: "
                                                       f"Davis: {wind_data['wind_speed_knots']:.2f}kts {wind_data['wind_direction_deg']:.1f}°, "
                                                       f"Tempest: {tempest_data['wind_speed_knots']:.2f}kts {tempest_data['wind_direction_deg']:.1f}° "
                                                       f"(age: {tempest_data['data_age_seconds']:.1f}s)")
                                            
                                            # Check if we have enough samples for calibration
                                            if calibration_data['samples_collected'] >= args.calibration_samples:
                                                calibration_result = tempest_calibrator.calculate_calibration(
                                                    calibration_data['davis_readings'],
                                                    calibration_data['tempest_readings']
                                                )
                                                
                                                if calibration_result:
                                                    logger.info("=" * 60)
                                                    logger.info("TEMPEST CALIBRATION RESULTS")
                                                    logger.info("=" * 60)
                                                    logger.info(f"Recommended calibration factor: {calibration_result['speed_calibration_factor']:.4f}")
                                                    logger.info(f"Recommended direction offset: {calibration_result['direction_offset']:.2f}°")
                                                    logger.info(f"Speed confidence: {calibration_result['speed_confidence']:.3f}")
                                                    logger.info(f"Direction confidence: {calibration_result['direction_confidence']:.3f}")
                                                    logger.info(f"Sample count: {calibration_result['sample_count']}")
                                                    logger.info("=" * 60)
                                                    logger.info("To apply these calibrations, restart with:")
                                                    logger.info(f"--calibration-factor {calibration_result['speed_calibration_factor']:.4f} "
                                                               f"--direction-offset {calibration_result['direction_offset']:.2f}")
                                                    logger.info("=" * 60)
                                                    
                                                    # Publish calibration data
                                                    plugin.publish("davis.calibration.speed_factor", calibration_result['speed_calibration_factor'],
                                                                 meta={"description": "Recommended speed calibration factor from Tempest comparison", 
                                                                       "confidence": f"{calibration_result['speed_confidence']:.3f}",
                                                                       "samples": str(calibration_result['sample_count'])})
                                                    plugin.publish("davis.calibration.direction_offset", calibration_result['direction_offset'],
                                                                 meta={"description": "Recommended direction offset from Tempest comparison", 
                                                                       "confidence": f"{calibration_result['direction_confidence']:.3f}",
                                                                       "samples": str(calibration_result['sample_count'])})
                                                else:
                                                    logger.warning("Could not calculate calibration - insufficient valid data")
                                                
                                                calibration_data['calibration_complete'] = True
                                                logger.info("Calibration complete - continuing normal operation...")
                                        else:
                                            logger.debug("Could not fetch Tempest data for calibration sample")
                                        
                                        # Add delay between calibration samples to avoid rate limiting
                                        time.sleep(2.0)
                                    
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
                                            
                                            logger.info(f"Published averaged data: {averaged_data['avg_wind_speed_knots']:.2f} knots "
                                                       f"(min: {averaged_data['min_wind_speed_knots']:.2f}, max: {averaged_data['max_wind_speed_knots']:.2f}), "
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
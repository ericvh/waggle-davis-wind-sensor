# Davis Wind Sensor Plugin for Waggle

[![Build Multi-Arch Docker Image](https://github.com/ericvh/waggle-davis-wind-sensor/actions/workflows/docker-build.yml/badge.svg)](https://github.com/ericvh/waggle-davis-wind-sensor/actions/workflows/docker-build.yml)
[![Test](https://github.com/ericvh/waggle-davis-wind-sensor/actions/workflows/test.yml/badge.svg)](https://github.com/ericvh/waggle-davis-wind-sensor/actions/workflows/test.yml)

A Waggle plugin that reads Davis wind sensor data from Arduino via USB serial port and publishes wind speed in knots, wind direction in degrees, along with debug information including rotations per second (RPS) and raw sensor values.

## Features

- **Davis Wind Sensor Support**: Specifically designed for Davis anemometer with Arduino interface
- **Wind Speed**: Outputs wind speed in knots (converted from RPM measurements)
- **Wind Direction**: Calculates wind direction from potentiometer readings (0-360°)
- **WXT-Style Topic Naming**: Uses `env.wind.*` topics for compatibility with existing weather station formats
- **Debug Information**: 
  - Rotations per second (RPS) from the wind sensor
  - Raw and debounced RPM values
  - Raw potentiometer readings
  - Arduino iteration counter
- **Data Averaging**: Configurable interval averaging with proper circular statistics for wind direction
- **Min/Max Tracking**: Wind speed lull and gust measurements during each averaging interval
- **Tempest Calibration**: UDP-based calibration using local Tempest weather station broadcasts
- **Dual-Mode Reporting**: Real-time debug data + averaged environmental measurements
- **Continuous Data Processing**: Blocks waiting for new data instead of polling on intervals for maximum responsiveness
- **Web Monitoring Interface**: Optional built-in web server with real-time dashboard and JSON API
- **Robust Serial Communication**: Includes error handling, automatic reconnection, and buffer management
- **Configurable Parameters**: Serial port, baud rate, wind speed and direction calibration factors

## Data Outputs

The plugin publishes measurements with comprehensive metadata including scopes, timestamps, sensor identification, and missing value indicators. This aligns with standard Waggle plugin patterns for better data organization and quality.

### Publishing Scopes

- **Beehive Scope**: Environmental data sent to central Beehive server for analysis and archival
- **Node Scope**: Debug and diagnostic data kept local to the node for troubleshooting

### Primary Environmental Data (WXT-compatible)
**Scope: `beehive`** - Published to central Beehive for scientific analysis

| Measurement | Units | Sensor | Description | Missing Value |
|-------------|-------|--------|-------------|---------------|
| `env.wind.speed` | knots | davis-anemometer | Averaged wind speed in knots | -9999.0 |
| `env.wind.direction` | degrees | davis-wind-vane | Vector-averaged wind direction (0-360°) | -9999.0 |
| `env.wind.speed.mps` | m/s | davis-anemometer | Averaged wind speed in meters per second | -9999.0 |
| `env.wind.speed.min` | knots | davis-anemometer | Minimum wind speed (lull) during interval | -9999.0 |
| `env.wind.speed.max` | knots | davis-anemometer | Maximum wind speed (gust) during interval | -9999.0 |
| `env.wind.speed.min.mps` | m/s | davis-anemometer | Minimum wind speed (lull) in m/s during interval | -9999.0 |
| `env.wind.speed.max.mps` | m/s | davis-anemometer | Maximum wind speed (gust) in m/s during interval | -9999.0 |
| `env.wind.consistency` | ratio | davis-wind-vane | Wind direction consistency (1.0=steady, 0.0=highly variable) | -9999.0 |

All environmental measurements include UTC timestamps and metadata fields:
- `sensor`: Physical sensor identifier
- `units`: Measurement units
- `description`: Human-readable description
- `interval_seconds`: Averaging interval (for averaged data)
- `sample_count`: Number of samples in average
- `missing`: Missing value indicator

### Davis-Specific Debug Data
**Scope: `node`** - Published locally for debugging and troubleshooting

| Measurement | Units | Sensor | Description | Missing Value |
|-------------|-------|--------|-------------|---------------|
| `davis.wind.rps` | rps | davis-anemometer | Sensor rotations per second | -9999.0 |
| `davis.wind.rpm.tops` | rpm | davis-anemometer | Debounced RPM count | -9999.0 |
| `davis.wind.rpm.raw` | rpm | davis-anemometer | Raw RPM count | -9999.0 |
| `davis.wind.pot.value` | counts | davis-wind-vane | Raw potentiometer value (0-1024) | -9999 |
| `davis.wind.iteration` | count | davis-anemometer | Arduino iteration counter | -9999 |
| `davis.wind.sensor_status` | status | davis-anemometer | Sensor status (0=error, 1=ok) | -1 |

Debug measurements include UTC timestamps and sensor identification for diagnostic purposes.


## Expected Serial Data Format

The plugin is designed specifically for Davis wind sensor data from Arduino:

**Davis Arduino Format**: `wind: iteration potvalue rpmtops rpmraw`

Example: `wind: 123 512 45 48`

Where the values represent:
- **iteration**: Arduino loop counter (for debugging)
- **potvalue**: Raw potentiometer reading (0-1024) for wind direction
- **rpmtops**: Debounced RPM count (used for wind speed calculation)
- **rpmraw**: Raw RPM count (debug information)

### Wind Speed Calculation
- Wind speed (m/s) = RPM_tops × 0.098 × calibration_factor
- Wind speed (knots) = Wind speed (m/s) × 1.94384

### Wind Direction Calculation
- Base direction = (potvalue / 1024) × 360
- Calibrated direction = (base_direction × direction_scale + direction_offset) % 360

## Data Processing Method

The plugin uses **continuous blocking reads** instead of polling intervals:

- **Responsiveness**: Data is processed immediately as it arrives from the Arduino
- **Efficiency**: No CPU wasted on empty polling cycles  
- **Real-time**: Wind measurements are published as soon as they're received
- **Reliability**: Automatic reconnection on serial port errors

This approach ensures maximum responsiveness and efficient use of system resources.

## Data Averaging and Reporting

The plugin implements a **dual-mode data system** for optimal meteorological data quality:

### Environmental Data (MQTT) - Averaged Reports
- **Reporting Interval**: Configurable (default: 60 seconds)
- **Wind Speed**: Arithmetic average of all readings during interval
- **Wind Speed Min/Max**: Minimum (lull) and maximum (gust) wind speeds during interval
- **Wind Direction**: Vector-averaged using circular statistics to properly handle direction wrap-around
- **Wind Consistency**: Measures direction variability (1.0 = perfectly steady, 0.0 = completely variable)
- **Quality Metadata**: Each published value includes sample count and interval duration

### Debug Data (Real-time) - Individual Readings  
- **RPM Values**: Published immediately for each reading
- **Raw Sensor Data**: Potentiometer values, iteration counters
- **System Status**: Connection health, error tracking

### Vector Averaging for Wind Direction

Wind direction averaging uses proper circular statistics:

1. **Convert to Vectors**: Each direction becomes a unit vector (cos θ, sin θ)
2. **Average Vectors**: Calculate mean of x and y components
3. **Convert Back**: Use atan2 to get averaged direction
4. **Consistency Metric**: Vector magnitude indicates how consistent the wind direction was

**Example**: Directions 350° and 10° average to 0° (not 180° as with arithmetic mean)

### Benefits

- **Meteorological Accuracy**: Proper circular averaging for wind direction
- **Reduced Noise**: Averaged data filters out sensor fluctuations
- **Quality Indicators**: Consistency metrics help assess data reliability
- **Real-time Monitoring**: Web interface shows individual readings
- **Configurable Intervals**: Adjust averaging period for your application

### Usage Examples

**Default 60-second averaging:**
```bash
python3 main.py --web-server
```

**Custom 5-minute averaging:**
```bash
python3 main.py --reporting-interval 300
```

**High-frequency 10-second reports:**
```bash
python3 main.py --reporting-interval 10
```

## Tempest Weather Station Calibration

The plugin includes a specialized calibration utility (`tempest.py`) that uses local Tempest weather station UDP broadcasts to calibrate your Davis wind sensor. This provides highly accurate calibration using professional-grade meteorological instruments with sub-second latency.

### How It Works

1. **Local UDP Reception**: Receives real-time broadcasts from your local Tempest weather station
2. **Interactive Comparison**: Enter your Davis readings and compare with simultaneous Tempest data  
3. **Statistical Analysis**: Calculates optimal calibration factors with confidence metrics
4. **Web Dashboard**: Optional browser-based interface for easier calibration sessions

### Prerequisites

- **Local Tempest Station**: You need a Tempest weather station on your local network
- **UDP Broadcasts**: Tempest must be configured to broadcast on UDP port 50222
- **Network Access**: Calibration utility must be on same network as Tempest hub

### Usage Methods

#### Interactive Console Mode
```bash
# Run interactive calibration in terminal
python3 tempest.py --calibrate

# Test connection and firewall setup
python3 tempest.py --test-connection

# Skip automatic firewall setup
python3 tempest.py --calibrate --no-firewall
```

This launches an interactive session where you:
1. **Automatic Firewall Setup**: Configures iptables rules for UDP reception
2. See current Tempest wind data
3. Enter your Davis sensor readings
4. Get real-time calibration updates as you add more samples
5. Receive final calibration factors and command-line arguments

#### Web Dashboard Mode
```bash
# Start web server with calibration dashboard
python3 tempest.py

# Then open browser to:
# http://localhost:8080/calibration
```

The web dashboard provides:
- **Live Tempest Data**: Auto-refreshing current wind conditions
- **Network Status**: Real-time firewall and connection monitoring
- **Easy Data Entry**: Simple form for Davis readings
- **Visual History**: Table of all reading pairs
- **Real-time Calculations**: Instant calibration updates
- **Export Results**: Copy-paste command-line arguments

### Sample Interactive Session

```
Davis Wind Sensor Calibration using Local Tempest Station
============================================================
Make sure your Tempest station is broadcasting on UDP port 50222
Enter 'quit' to exit

Current Tempest: 8.3 knots, 142° (rapid_wind)
Enter Davis reading (speed,direction) or 'quit': 7.5,145
Davis:   7.5 knots, 145°
Stored reading pair #1

Current Tempest: 8.1 knots, 140° (rapid_wind)  
Enter Davis reading (speed,direction) or 'quit': 7.3,143
Davis:   7.3 knots, 143°
Stored reading pair #2

Current calibration (based on 2 samples):
  Speed factor: 1.103
  Direction offset: -2.5°
  Confidence: Speed=0.95, Direction=0.88
```

### Calibration Output

```
============================================================
FINAL CALIBRATION RESULTS  
============================================================
Samples: 8
Speed calibration factor: 1.0847
Direction offset: -2.73°
Speed confidence: 0.921
Direction confidence: 0.856
============================================================
Command line for Davis plugin:
python3 main.py --calibration-factor 1.0847 --direction-offset -2.73
============================================================
```

### Advantages of UDP Method

- **Real-Time Data**: Sub-second latency from local Tempest station
- **No Internet Required**: Works entirely on local network
- **High Precision**: Uses rapid_wind updates (3-second intervals) 
- **Professional Reference**: Tempest stations are factory-calibrated
- **Interactive Feedback**: See calibration improve with each sample
- **Simultaneous Readings**: Perfect time synchronization between sensors
- **Automatic Firewall Setup**: Manages iptables rules for UDP reception

### Firewall Management

The calibration utility automatically manages Linux firewall rules to ensure UDP broadcasts are received:

#### Automatic Setup
- **Rule Detection**: Checks if UDP port 50222 is already allowed
- **Smart Addition**: Only adds rules if needed
- **Commented Rules**: Uses identifiable comments for easy cleanup
- **Auto Cleanup**: Removes rules automatically on exit

#### Manual Control
```bash
# Skip firewall management entirely
python3 tempest.py --calibrate --no-firewall

# Test connection and firewall setup
python3 tempest.py --test-connection

# Check what iptables rules were added
sudo iptables -L INPUT | grep tempest-calibration
```

#### Rule Details
The utility automatically detects privileges and adds the appropriate iptables rule:

**When running as root (common in containers):**
```bash
iptables -I INPUT -p udp --dport 50222 -j ACCEPT -m comment --comment tempest-calibration-50222
```

**When running as non-root user with sudo:**
```bash
sudo iptables -I INPUT -p udp --dport 50222 -j ACCEPT -m comment --comment tempest-calibration-50222
```

#### Platform Support
- **Linux (root)**: Direct iptables commands for optimal container compatibility
- **Linux (non-root)**: sudo iptables commands with privilege detection
- **macOS/Windows**: Firewall management gracefully skipped
- **Docker/Container**: Optimized for root containers, supports `--privileged` mode

### API Endpoints (Web Mode)

#### Weather Data
- `GET /weather` - All Tempest data (raw and parsed)
- `GET /weather/raw` - Raw UDP message data
- `GET /weather/parsed` - Parsed and processed data

#### Calibration
- `GET /calibration/current-wind` - Current wind data for calibration
- `POST /calibration/add-reading` - Add Davis reading pair
- `GET /calibration/readings` - Get all calibration reading pairs
- `GET /calibration/calculate` - Get calibration factors
- `POST /calibration/clear` - Clear all readings
- `GET /calibration` - Calibration dashboard (HTML)

#### Network/Firewall
- `GET /calibration/firewall-status` - Check firewall rule status
- `POST /calibration/setup-firewall` - Setup firewall rules

### Integrated Auto-Calibration

The Davis plugin can now run Tempest calibration automatically at startup using the `--auto-calibrate` flag:

#### How It Works
1. **Firewall Setup**: Automatically configures iptables rules for UDP reception
2. **Tempest Detection**: Starts UDP listener and waits for Tempest broadcasts (30s timeout)
3. **Data Collection**: Collects paired Davis + Tempest readings over specified interval
4. **Calibration Calculation**: Computes speed factor and direction offset with confidence metrics
5. **Automatic Application**: Applies calibration factors if confidence meets threshold
6. **Fallback**: Uses manual values if auto-calibration fails or confidence too low

#### Full Implementation
The `--auto-calibrate` feature provides **complete automatic calibration**:
- ✅ **Integrated UDP listener** for Tempest broadcasts
- ✅ **Automatic firewall configuration** with root/sudo detection
- ✅ **Real-time data collection** from both Davis sensor and Tempest station
- ✅ **Calibration factor calculation** with confidence assessment
- ✅ **Automatic application** when confidence ≥ threshold (default: 0.7)
- ✅ **Comprehensive error handling** and user guidance

**Usage:**
```bash
# Full automatic calibration with defaults (10 samples, 5s intervals)
python3 main.py --auto-calibrate

# Custom parameters
python3 main.py --auto-calibrate \
  --calibration-samples 15 \
  --calibration-interval 3 \
  --min-calibration-confidence 0.8

# Skip firewall setup
python3 main.py --auto-calibrate --no-firewall
```

#### Standalone Utility
For manual calibration or when auto-calibration fails:
```bash
python3 tempest.py --calibrate  # Interactive mode
python3 tempest.py             # Web interface at :8080/calibration
```

### Continuous Calibration Mode

The plugin supports **continuous automatic calibration** that runs in the background during normal operation, comparing Davis readings with Tempest data and making gradual adjustments every 15 minutes.

#### How It Works

1. **Background Operation**: Runs in a separate thread alongside normal Davis sensor data collection
2. **Aggressive Bootstrap**: Retries initial calibration every 3 minutes until confident baseline established
3. **Periodic Comparison**: Every 15 minutes (configurable), collects comparison samples from both sensors
4. **Initial Bootstrap**: Uses lower confidence threshold (30%) and full adjustment rate for first calibration
5. **Gradual Adjustments**: Applies only 30% of calculated adjustments per cycle to prevent sudden jumps
6. **Speed-Only Confidence**: Direction confidence disabled by default (0.0) since direction is more variable
7. **Direction History**: Optional database of Tempest direction vs Davis pot values for non-linear calibration
8. **Live Updates**: Calibration factors are updated in real-time without interrupting data collection

#### Usage

**Enable continuous calibration with defaults:**
```bash
# 15-minute intervals, 20 samples per cycle, 30% adjustment rate
python3 main.py --continuous-calibration
```

**Custom intervals and parameters:**
```bash
# 10-minute intervals with more conservative adjustments
python3 main.py --continuous-calibration \
  --continuous-interval 600 \
  --continuous-samples 25 \
  --continuous-adjustment-rate 0.1

# Higher confidence thresholds for more selective adjustments
python3 main.py --continuous-calibration \
  --continuous-confidence-threshold 0.7 \
  --continuous-direction-confidence-threshold 0.5

# Lower initial confidence for easier bootstrap
python3 main.py --continuous-calibration \
  --initial-calibration-confidence 0.2 \
  --initial-direction-confidence 0.1 \
  --continuous-confidence-threshold 0.8

# Enable direction confidence for strict calibration
python3 main.py --continuous-calibration \
  --continuous-direction-confidence-threshold 0.4 \
  --initial-direction-confidence 0.2

# Enable direction history database for non-linear calibration
python3 main.py --continuous-calibration \
  --enable-direction-history \
  --direction-history-file /data/wind_direction_history.json

# Faster bootstrap retries for quicker initial calibration
python3 main.py --continuous-calibration \
  --initial-calibration-retry-interval 120
```

**With web monitoring:**
```bash
# Continuous calibration + web interface for monitoring
python3 main.py --continuous-calibration --web-server --web-port 8080
```

#### Configuration Options

- `--continuous-calibration`: Enable continuous calibration mode
- `--continuous-interval`: Time between calibration cycles in seconds (default: 900 = 15 minutes)
- `--continuous-samples`: Number of samples per calibration cycle (default: 20)
- `--continuous-sample-interval`: Seconds between samples during collection (default: 5)
- `--continuous-confidence-threshold`: Minimum confidence for applying adjustments (default: 0.5)
- `--continuous-adjustment-rate`: Percentage of adjustment to apply per cycle (default: 0.3 = 30%)

#### Sample Output

```
🔄 Continuous calibration mode enabled
🔄 Starting continuous calibration background thread...
   Ongoing calibration interval: 900 seconds (15.0 minutes)
   Initial calibration retry interval: 180 seconds (3.0 minutes)
   Samples per calibration: 20
   Speed confidence threshold: 0.5
   Direction confidence threshold: 0.0
   Initial speed confidence threshold: 0.3
   Initial direction confidence threshold: 0.0
   Adjustment rate: 30% per cycle
   Direction history: Enabled (file: direction_history.json)
   Direction history: Starting fresh database
✅ Tempest detected for continuous calibration: 8.2 knots, 145°

📊 Starting initial bootstrap calibration at 14:30:15
⏰ Next calibration scheduled for 14:33:15 (3.0 min interval)
🧮 Calculating continuous calibration from 20 samples...
📈 Calculated continuous calibration:
   Speed factor: 1.0284 (confidence: 0.423)
   Direction offset: -2.1° (confidence: 0.156)
   Using initial calibration confidence thresholds: speed≥0.30, direction≥0.00
   Using full adjustment rate for bootstrap: 100%
✅ Applied initial calibration (bootstrap):
   New speed factor: 1.0284
   New direction offset: -2.1°
```

#### Benefits

- **Automatic Drift Correction**: Compensates for sensor drift over time
- **Environmental Adaptation**: Adjusts to changing conditions automatically
- **Non-Disruptive**: Works alongside normal operation without interruption
- **Conservative**: Gradual adjustments prevent over-correction
- **Configurable**: All parameters tunable for different environments

#### Comparison with Auto-Calibration

| Feature | Auto-Calibration (`--auto-calibrate`) | Continuous Calibration (`--continuous-calibration`) |
|---------|---------------------------------------|---------------------------------------------------|
| **When** | Once at startup | Continuously every 15 minutes |
| **Purpose** | Initial calibration setup | Long-term drift correction |
| **Operation** | Blocks startup until complete | Runs in background during operation |
| **Adjustments** | Immediate full application | Gradual 30% per cycle |
| **Confidence** | High threshold (70%) required | Lower threshold (50%) acceptable |
| **Use Case** | First-time setup, major recalibration | Long-term deployments, maintenance |

### Troubleshooting

**No Tempest data received:**
- Run connection test: `python3 tempest.py --test-connection`
- Check Tempest hub is on same network
- Verify Tempest station is actively broadcasting
- Check firewall status in web dashboard
- Try manual firewall rule: `sudo iptables -I INPUT -p udp --dport 50222 -j ACCEPT`

**Permission errors:**
- **As root**: Direct iptables commands used automatically
- **As non-root**: Run with sudo: `sudo python3 tempest.py --calibrate`
- **Skip firewall**: Use `--no-firewall` flag
- **Check privileges**: `sudo -v` or verify root with `id`

**Poor calibration confidence:**
- Take readings during steady wind conditions  
- Collect more samples (8-15 recommended)
- Ensure both sensors are measuring same air mass
- Check for obstructions affecting either sensor

**Firewall cleanup issues:**
- **Manual cleanup**: `iptables -D INPUT -p udp --dport 50222 -j ACCEPT` (add `sudo` if not root)
- **List rules**: `iptables -L INPUT | grep tempest-calibration` (add `sudo` if not root)
- **Force cleanup**: `iptables -D INPUT -m comment --comment tempest-calibration-50222` (add `sudo` if not root)

## Web Monitoring Interface

The plugin includes an optional built-in web server that provides real-time monitoring of wind sensor data through a responsive web dashboard.

### Features

- **Real-time Dashboard**: Live updates of wind speed, direction, and debug data
- **Responsive Design**: Works on desktop, tablet, and mobile devices
- **Auto-refresh**: Automatic updates every 5 seconds (can be toggled)
- **JSON API**: RESTful endpoints for programmatic access
- **Status Monitoring**: System status, error counts, and connection health
- **Raw Data View**: See the actual serial data received from Arduino
- **Simple HTML View**: Clean, formatted data display suitable for embedding or simple monitoring

### Usage

**Enable web server:**
```bash
python3 main.py --web-server
```

**Custom port:**
```bash
python3 main.py --web-server --web-port 9090
```

**With Docker:**
```bash
docker run -p 8080:8080 --device=/dev/ttyACM2:/dev/ttyACM2 --privileged \
  ghcr.io/ericvh/waggle-davis-wind-sensor:latest \
  --web-server --web-port 8080
```

**Simple HTML View** - Perfect for embedding in other pages or basic monitoring:
```bash
# Visit http://localhost:8080/data.html for clean data display
# Auto-refreshes every 10 seconds
# No controls or interactive elements - just the data
```

### Web Endpoints

- **Dashboard**: `http://localhost:8080/` - Interactive web interface with controls
- **Simple HTML**: `http://localhost:8080/data.html` - Clean formatted data view (auto-refresh every 10s)
- **Simple HTML**: `http://localhost:8080/simple` - Same as above (alternate URL)
- **JSON Data**: `http://localhost:8080/api/data` - Complete data as JSON
- **Status Only**: `http://localhost:8080/api/status` - System status information

**Dashboard vs Simple View:**
- **Dashboard** (`/`): Full-featured interface with manual refresh, toggle controls, responsive grid layout
- **Simple View** (`/data.html`): Clean, minimal display optimized for embedding, kiosks, or basic monitoring

### API Response Format

```json
{
  "timestamp": "2024-01-15T10:30:45.123456",
  "status": "running",
  "total_readings": 1234,
  "error_count": 0,
  "raw_line": "wind: 156 512 45 48",
  "wind_data": {
    "iteration": 156,
    "wind_speed_knots": 8.76,
    "wind_direction_deg": 180.0,
    "wind_speed_mps": 4.51,
    "rotations_per_second": 0.75,
    "rpm_tops": 45,
    "rpm_raw": 48,
    "pot_value": 512
  }
}
```

## Automated Builds

The repository includes GitHub Actions that automatically:

- **Multi-Architecture Builds**: Creates Docker images for both AMD64 and ARM64 platforms
- **Code Quality Checks**: Runs linting, formatting, and syntax validation
- **Automated Publishing**: Pushes images to GitHub Container Registry on every commit to main
- **Version Tagging**: Creates versioned releases when tags are pushed (e.g., `v1.0.0`)
- **Pull Request Testing**: Validates builds and tests on every pull request

### Available Image Tags

- `latest` - Latest build from main branch
- `v1.0.0` - Specific version releases
- `main` - Latest commit from main branch

## Usage

### Command Line Arguments

```bash
python3 main.py [options]
```

**Options:**
- `--port` : Serial port device (default: `/dev/ttyACM2`)
- `--baudrate` : Serial port baud rate (default: `115200`)
- `--timeout` : Serial port read timeout in seconds (default: `30.0`)
- `--calibration-factor` : Wind speed calibration factor (default: `1.0`)
- `--direction-offset` : Wind direction offset in degrees (default: `0.0`)
- `--direction-scale` : Wind direction scaling factor (default: `1.0`)
- `--reporting-interval` : MQTT reporting interval in seconds for averaged data (default: `60`)

### Auto-Calibration Arguments
- `--auto-calibrate` : Run automatic Tempest calibration at startup using UDP broadcasts
- `--calibration-samples` : Number of samples for auto-calibration (default: `10`)
- `--calibration-interval` : Seconds between calibration samples (default: `5`)
- `--calibration-timeout` : Maximum time for calibration in seconds (default: `300`)
- `--min-calibration-confidence` : Minimum confidence required for auto-calibration (default: `0.7`)
- `--no-firewall` : Skip automatic firewall setup for calibration

### Continuous Calibration Arguments
- `--continuous-calibration` : Enable continuous calibration mode with 15-minute intervals
- `--continuous-interval` : Time between calibration cycles in seconds (default: `900`)
- `--continuous-samples` : Number of samples per calibration cycle (default: `20`)
- `--continuous-sample-interval` : Seconds between samples during collection (default: `5`)
- `--continuous-confidence-threshold` : Minimum speed confidence for applying adjustments (default: `0.5`)
- `--continuous-direction-confidence-threshold` : Minimum direction confidence for applying adjustments (default: `0.0` = disabled)
- `--continuous-adjustment-rate` : Percentage of adjustment to apply per cycle (default: `0.3`)
- `--initial-calibration-confidence` : Lower speed confidence threshold for initial calibration bootstrap (default: `0.3`)
- `--initial-direction-confidence` : Lower direction confidence threshold for initial calibration bootstrap (default: `0.0` = disabled)
- `--initial-calibration-retry-interval` : Retry interval in seconds for initial calibration when confidence is low (default: `180` = 3 minutes)
- `--enable-direction-history` : Enable building historical database of Tempest direction vs Davis pot values for non-linear calibration
- `--direction-history-file` : File to store direction history database (default: `direction_history.json`)

### Web Interface Arguments
- `--web-server` : Enable mini web server for monitoring
- `--web-port` : Web server port (default: `8080`)

### General Arguments
- `--debug` : Enable debug output
- `--help` : Show help message

### Examples

**Basic usage with default settings:**
```bash
python3 main.py
```

**Use a different serial port:**
```bash
python3 main.py --port /dev/ttyUSB1
```

**Change baud rate:**
```bash
python3 main.py --baudrate 115200
```

**Enable debug output and apply calibrations:**
```bash
python3 main.py --debug --calibration-factor 1.05 --direction-offset 15.0
```

**Correct wind vane alignment (if vane points 30° off when wind is from north):**
```bash
python3 main.py --direction-offset -30.0
```

**Run with automatic Tempest calibration:**
```bash
python3 main.py --auto-calibrate
```

**Run auto-calibration with custom settings:**
```bash
python3 main.py --auto-calibrate --calibration-samples 15 --calibration-timeout 600
```

**Auto-calibration without firewall management:**
```bash
python3 main.py --auto-calibrate --no-firewall
```

**Scale potentiometer range (if it only covers 270° instead of 360°):**
```bash
python3 main.py --direction-scale 1.333
```

**Enable web monitoring interface:**
```bash
python3 main.py --web-server --web-port 8080
```

**Enable continuous calibration:**
```bash
python3 main.py --continuous-calibration
```

**Continuous calibration with custom settings:**
```bash
python3 main.py --continuous-calibration \
  --continuous-interval 600 \
  --continuous-adjustment-rate 0.1 \
  --continuous-confidence-threshold 0.7
```

## Docker Deployment

### Multi-Mode Container Support

The Davis Wind Sensor Docker container supports multiple operation modes via environment variables:

- **`main`** (default): Run the Davis wind sensor plugin
- **`calibrate`**: Interactive Tempest calibration mode  
- **`web`**: Tempest calibration web interface
- **`continuous`**: Continuous auto-calibration mode (15-minute intervals)
- **`test`**: Test Tempest UDP connection

Multi-architecture Docker images are automatically built and published to GitHub Container Registry for both AMD64 and ARM64 platforms.

### Using Pre-built Images (Recommended)

**Pull the latest image:**
```bash
docker pull ghcr.io/ericvh/waggle-davis-wind-sensor:latest
```

#### Main Davis Wind Sensor Plugin

**Basic usage:**
```bash
docker run --device=/dev/ttyACM2:/dev/ttyACM2 --privileged \
  ghcr.io/ericvh/waggle-davis-wind-sensor:latest
```

**Custom configuration:**
```bash
docker run --device=/dev/ttyACM2:/dev/ttyACM2 --privileged \
  ghcr.io/ericvh/waggle-davis-wind-sensor:latest \
  --port /dev/ttyACM2 --baudrate 115200 --debug \
  --calibration-factor 1.05 --direction-offset -15.0
```

**With automatic Tempest calibration:**
```bash
docker run --device=/dev/ttyACM2:/dev/ttyACM2 --network host --privileged \
  ghcr.io/ericvh/waggle-davis-wind-sensor:latest \
  --auto-calibrate
```

#### Tempest Calibration Modes

**Interactive calibration (console-based):**
```bash
docker run -e DAVIS_MODE=calibrate -it --network host --privileged \
  ghcr.io/ericvh/waggle-davis-wind-sensor:latest
```

**Web-based calibration interface:**
```bash
docker run -e DAVIS_MODE=web -p 8080:8080 --network host --privileged \
  ghcr.io/ericvh/waggle-davis-wind-sensor:latest
```
Then open: http://localhost:8080/calibration

**Continuous auto-calibration mode:**
```bash
docker run -e DAVIS_MODE=continuous --device=/dev/ttyACM2 --network host --privileged \
  ghcr.io/ericvh/waggle-davis-wind-sensor:latest
```

**Test UDP connection:**
```bash
docker run -e DAVIS_MODE=test --network host --privileged \
  ghcr.io/ericvh/waggle-davis-wind-sensor:latest
```

#### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DAVIS_MODE` | `main` | Operation mode (`main`\|`calibrate`\|`web`\|`continuous`\|`test`) |
| `TEMPEST_PORT` | `8080` | Web server port for calibration interface |
| `NO_FIREWALL` | `false` | Skip automatic firewall setup (`true`\|`false`) |

#### Docker Network Requirements

**For Tempest calibration modes:**
- Use `--network host` to receive UDP broadcasts from Tempest station
- Use `--privileged` for automatic firewall management
- **Root containers**: Firewall rules applied directly (optimal)
- **Non-root containers**: May need sudo setup or `--privileged` mode
- Alternative: Use `-e NO_FIREWALL=true` and manage firewall manually

### Docker Compose (Recommended)

**Download the compose file:**
```bash
curl -O https://raw.githubusercontent.com/ericvh/waggle-davis-wind-sensor/main/docker-compose.yml
```

**Run main Davis plugin:**
```bash
docker-compose up davis-plugin
```

**Run calibration web interface:**
```bash
docker-compose --profile calibration up tempest-calibration-web
```

**Test Tempest connection:**
```bash
docker-compose --profile test up tempest-test
```

**Stop all services:**
```bash
docker-compose down
```

### Building Locally

**Build the Docker image:**
```bash
docker build -t davis-wind-sensor-plugin .
```

**Test all modes:**
```bash
# Main plugin
docker run --device=/dev/ttyACM2:/dev/ttyACM2 --privileged davis-wind-sensor-plugin

# Calibration test
docker run -e DAVIS_MODE=test --network host --privileged davis-wind-sensor-plugin

# Web calibration
docker run -e DAVIS_MODE=web -p 8080:8080 --network host --privileged davis-wind-sensor-plugin
```

### Container Help

**Get container usage help:**
```bash
docker run ghcr.io/ericvh/waggle-davis-wind-sensor:latest --help
```

This displays all available modes, environment variables, and Docker networking requirements.

## Hardware Requirements

- **Davis Wind Sensor**: Davis anemometer (cup-type) with wind vane
- **Arduino Board**: Arduino Uno, Nano, or compatible board
- **Connections**: 
  - Anemometer RPM sensor to Arduino digital pin D2 (interrupt-capable)
  - Wind vane potentiometer to Arduino analog pin A0
  - Optional calibration input on analog pin A1
- **Serial Interface**: USB connection from Arduino to Waggle node
- **Power**: 5V power supply for Arduino

### Required Arduino Code

The Arduino should be programmed with the Davis wind sensor code from `/Users/erivan01/Documents/PlatformIO/Projects/Davis` that outputs the format: `wind: iteration potvalue rpmtops rpmraw`

## Installation

### Dependencies

Install the required Python packages:
```bash
pip install -r requirements.txt
```

Required packages:
- `pywaggle>=0.50.0` - Waggle plugin framework
- `pyserial>=3.5` - Serial communication

### System Requirements

- Linux-based system (tested on Ubuntu, Debian)
- USB serial port access
- Python 3.7 or higher

## Configuration

### Serial Port Permissions

Ensure the user has access to the serial port:
```bash
sudo usermod -a -G dialout $USER
# Log out and log back in, or run:
sudo chmod 666 /dev/ttyACM2
```

### Environment Variables

All command-line arguments can be configured using environment variables with the `DAVIS_` prefix. This is especially useful for Docker deployments and automated configurations.

**Precedence:** Command-line arguments take precedence over environment variables.

#### Basic Configuration

| Environment Variable | CLI Argument | Type | Default | Description |
|---------------------|--------------|------|---------|-------------|
| `DAVIS_PORT` | `--port` | string | `/host/dev/serial/by-id/usb-Seeed_...` | Serial port device path |
| `DAVIS_BAUDRATE` | `--baudrate` | int | `115200` | Serial port baud rate |
| `DAVIS_TIMEOUT` | `--timeout` | float | `30.0` | Serial port timeout in seconds |
| `DAVIS_DEBUG` | `--debug` | bool | `false` | Enable debug output |
| `DAVIS_REPORTING_INTERVAL` | `--reporting-interval` | int | `60` | MQTT reporting interval in seconds |

#### Calibration Settings

| Environment Variable | CLI Argument | Type | Default | Description |
|---------------------|--------------|------|---------|-------------|
| `DAVIS_CALIBRATION_FACTOR` | `--calibration-factor` | float | `9.0` | Wind speed calibration factor |
| `DAVIS_DIRECTION_OFFSET` | `--direction-offset` | float | `-94.43` | Wind direction offset in degrees |
| `DAVIS_DIRECTION_SCALE` | `--direction-scale` | float | `1.0` | Wind direction scaling factor |

#### Web Interface Settings

| Environment Variable | CLI Argument | Type | Default | Description |
|---------------------|--------------|------|---------|-------------|
| `DAVIS_WEB_SERVER` | `--web-server` | bool | `false` | Enable web monitoring interface |
| `DAVIS_WEB_PORT` | `--web-port` | int | `8080` | Web server port |

#### Auto-Calibration Settings

| Environment Variable | CLI Argument | Type | Default | Description |
|---------------------|--------------|------|---------|-------------|
| `DAVIS_AUTO_CALIBRATE` | `--auto-calibrate` | bool | `false` | Run automatic Tempest calibration at startup |
| `DAVIS_CALIBRATION_SAMPLES` | `--calibration-samples` | int | `10` | Number of samples for auto-calibration |
| `DAVIS_CALIBRATION_INTERVAL` | `--calibration-interval` | int | `5` | Seconds between calibration samples |
| `DAVIS_CALIBRATION_TIMEOUT` | `--calibration-timeout` | int | `300` | Maximum calibration time in seconds |
| `DAVIS_MIN_CALIBRATION_CONFIDENCE` | `--min-calibration-confidence` | float | `0.7` | Minimum confidence for auto-calibration |
| `DAVIS_NO_FIREWALL` | `--no-firewall` | bool | `false` | Skip automatic firewall setup |

#### Continuous Calibration Settings

| Environment Variable | CLI Argument | Type | Default | Description |
|---------------------|--------------|------|---------|-------------|
| `DAVIS_CONTINUOUS_CALIBRATION` | `--continuous-calibration` | bool | `false` | Enable continuous calibration mode |
| `DAVIS_CONTINUOUS_INTERVAL` | `--continuous-interval` | int | `900` | Interval between adjustments (seconds) |
| `DAVIS_CONTINUOUS_SAMPLES` | `--continuous-samples` | int | `20` | Samples per calibration cycle |
| `DAVIS_CONTINUOUS_SAMPLE_INTERVAL` | `--continuous-sample-interval` | int | `5` | Seconds between samples |
| `DAVIS_CONTINUOUS_CONFIDENCE_THRESHOLD` | `--continuous-confidence-threshold` | float | `0.5` | Min speed confidence for adjustments |
| `DAVIS_CONTINUOUS_DIRECTION_CONFIDENCE_THRESHOLD` | `--continuous-direction-confidence-threshold` | float | `0.0` | Min direction confidence (0 = disabled) |
| `DAVIS_CONTINUOUS_ADJUSTMENT_RATE` | `--continuous-adjustment-rate` | float | `0.3` | Adjustment rate per cycle (0.1-1.0) |
| `DAVIS_INITIAL_CALIBRATION_CONFIDENCE` | `--initial-calibration-confidence` | float | `0.3` | Lower threshold for bootstrap |
| `DAVIS_INITIAL_DIRECTION_CONFIDENCE` | `--initial-direction-confidence` | float | `0.0` | Bootstrap direction threshold (0 = disabled) |
| `DAVIS_INITIAL_CALIBRATION_RETRY_INTERVAL` | `--initial-calibration-retry-interval` | int | `180` | Bootstrap retry interval (seconds) |

#### Direction History Settings

| Environment Variable | CLI Argument | Type | Default | Description |
|---------------------|--------------|------|---------|-------------|
| `DAVIS_ENABLE_DIRECTION_HISTORY` | `--enable-direction-history` | bool | `false` | Enable direction history database |
| `DAVIS_DIRECTION_HISTORY_FILE` | `--direction-history-file` | string | `direction_history.json` | History database file path |

#### Boolean Values

For boolean environment variables, use any of: `true`, `1`, `yes`, `on` (case-insensitive) for true, anything else for false.

#### Usage Examples

**Basic configuration with environment variables:**
```bash
export DAVIS_PORT=/dev/ttyUSB0
export DAVIS_BAUDRATE=9600
export DAVIS_DEBUG=true
python3 main.py
```

**Docker deployment with environment variables:**
```bash
docker run \
  -e DAVIS_PORT=/dev/ttyACM2 \
  -e DAVIS_CALIBRATION_FACTOR=9.5 \
  -e DAVIS_DIRECTION_OFFSET=-94.43 \
  -e DAVIS_WEB_SERVER=true \
  -e DAVIS_WEB_PORT=8080 \
  --device=/dev/ttyACM2:/dev/ttyACM2 \
  ghcr.io/ericvh/waggle-davis-wind-sensor:latest
```

**Continuous calibration via environment variables:**
```bash
docker run \
  -e DAVIS_CONTINUOUS_CALIBRATION=true \
  -e DAVIS_CONTINUOUS_INTERVAL=600 \
  -e DAVIS_CONTINUOUS_SAMPLES=30 \
  -e DAVIS_INITIAL_CALIBRATION_CONFIDENCE=0.3 \
  --device=/dev/ttyACM2:/dev/ttyACM2 \
  --network host \
  --privileged \
  ghcr.io/ericvh/waggle-davis-wind-sensor:latest
```

**Docker Compose example:**
```yaml
version: '3.8'
services:
  davis-sensor:
    image: ghcr.io/ericvh/waggle-davis-wind-sensor:latest
    devices:
      - /dev/ttyACM2:/dev/ttyACM2
    network_mode: host
    privileged: true
    environment:
      - DAVIS_PORT=/dev/ttyACM2
      - DAVIS_BAUDRATE=115200
      - DAVIS_CALIBRATION_FACTOR=9.0
      - DAVIS_DIRECTION_OFFSET=-94.43
      - DAVIS_WEB_SERVER=true
      - DAVIS_CONTINUOUS_CALIBRATION=true
      - DAVIS_REPORTING_INTERVAL=60
```

**Override environment variables with CLI arguments:**
```bash
# DAVIS_PORT is set in environment, but CLI overrides it
export DAVIS_PORT=/dev/ttyUSB0
python3 main.py --port /dev/ttyACM2  # Uses /dev/ttyACM2, not /dev/ttyUSB0
```

### Calibration

#### Wind Speed Calibration
Use the `--calibration-factor` parameter to adjust wind speed readings:
- Factor > 1.0: Increases reported wind speed
- Factor < 1.0: Decreases reported wind speed  
- Factor = 1.0: No adjustment (default)

#### Wind Direction Calibration
Use direction calibration parameters to correct wind vane alignment and scaling:

**Direction Offset (`--direction-offset`):**
- Corrects for wind vane misalignment relative to true north
- Positive values rotate clockwise, negative values rotate counterclockwise
- Example: If vane reads 30° when wind is actually from north (0°), use `--direction-offset -30.0`

**Direction Scale (`--direction-scale`):**
- Corrects for potentiometer range that doesn't cover full 360°
- Scale = 360 / actual_range
- Example: If potentiometer only covers 270°, use `--direction-scale 1.333` (360/270)
- Scale = 1.0: No scaling (default)

**Combined Calibration:**
```bash
# Wind vane is 15° clockwise off north and only covers 300°
python3 main.py --direction-offset -15.0 --direction-scale 1.2
```

## Troubleshooting

### Common Issues

**Serial port not found:**
- Check if the device is connected: `ls /dev/ttyACM*` or `ls /dev/ttyUSB*`
- Verify permissions: `ls -l /dev/ttyACM2`
- Check USB connection and driver installation

**No data received:**
- Verify baud rate matches sensor configuration
- Check serial cable wiring
- Enable debug mode: `--debug`
- Test with a serial terminal program first

**Parsing errors:**
- Check sensor data format
- Enable debug mode to see raw serial data
- Modify parsing patterns in `parse_wind_data()` if needed

### Debug Mode

Enable debug mode for detailed logging:
```bash
python3 main.py --debug
```

This will show:
- Raw serial data received
- Parsing attempts and results
- Detailed sensor readings

## Development

### Adding New Data Formats

To support additional data formats, modify the `parse_wind_data()` method in the `WindSensorReader` class. Add new regex patterns to the `patterns` list.

### Extending Measurements

Add new measurements by calling `plugin.publish()` with appropriate sensor names and metadata.

## License

This project is licensed under the MIT License.

## Contributing

Contributions are welcome! Please submit pull requests or open issues for bugs and feature requests.

## Support

For questions or support, please contact the Waggle team or open an issue in the repository. 
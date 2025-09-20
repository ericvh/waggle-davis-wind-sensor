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
- **Tempest Calibration**: Automatic calibration using public Tempest weather stations as reference
- **Dual-Mode Reporting**: Real-time debug data + averaged environmental measurements
- **Continuous Data Processing**: Blocks waiting for new data instead of polling on intervals for maximum responsiveness
- **Web Monitoring Interface**: Optional built-in web server with real-time dashboard and JSON API
- **Robust Serial Communication**: Includes error handling, automatic reconnection, and buffer management
- **Configurable Parameters**: Serial port, baud rate, wind speed and direction calibration factors

## Data Outputs

The plugin publishes the following measurements:

### Primary Environmental Data (WXT-compatible)
| Measurement | Units | Description |
|-------------|-------|-------------|
| `env.wind.speed` | knots | Averaged wind speed in knots |
| `env.wind.direction` | degrees | Vector-averaged wind direction (0-360°) |
| `env.wind.speed.mps` | m/s | Averaged wind speed in meters per second |
| `env.wind.speed.min` | knots | Minimum wind speed (lull) during interval |
| `env.wind.speed.max` | knots | Maximum wind speed (gust) during interval |
| `env.wind.speed.min.mps` | m/s | Minimum wind speed (lull) in m/s during interval |
| `env.wind.speed.max.mps` | m/s | Maximum wind speed (gust) in m/s during interval |
| `env.wind.consistency` | ratio | Wind direction consistency (1.0=steady, 0.0=highly variable) |

### Davis-Specific Debug Data
| Measurement | Units | Description |
|-------------|-------|-------------|
| `davis.wind.rps` | rps | Sensor rotations per second |
| `davis.wind.rpm.tops` | rpm | Debounced RPM count |
| `davis.wind.rpm.raw` | rpm | Raw RPM count |
| `davis.wind.pot.value` | counts | Raw potentiometer value (0-1024) |
| `davis.wind.iteration` | count | Arduino iteration counter |
| `davis.wind.sensor_status` | status | Sensor status (0=error, 1=ok) |
| `davis.calibration.speed_factor` | ratio | Recommended speed calibration factor from Tempest comparison |
| `davis.calibration.direction_offset` | degrees | Recommended direction offset from Tempest comparison |

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

The plugin includes an innovative calibration feature that uses public [Tempest weather stations](https://tempestwx.com/station/98272) as reference points to automatically calibrate your Davis wind sensor. This provides a way to ensure your measurements are accurate against professionally deployed meteorological instruments.

### How It Works

1. **Reference Station**: Specify a nearby Tempest weather station ID
2. **Data Collection**: Plugin fetches real-time data from the Tempest station via WeatherFlow API
3. **Comparison**: Compares your Davis sensor readings with Tempest measurements
4. **Calibration Calculation**: Calculates optimal calibration factors and direction offsets
5. **Confidence Metrics**: Provides statistical confidence measures for the calibration

### Usage Examples

**Basic calibration check against Lanai station:**
```bash
python3 main.py --tempest-station 98272
# Shows Tempest data in logs for manual comparison
```

**Automatic calibration mode:**
```bash
python3 main.py --tempest-station 98272 --tempest-calibration --calibration-samples 20
# Collects 20 comparison samples and calculates calibration factors
```

**Find your nearest Tempest station:**
Visit [tempestwx.com](https://tempestwx.com) and search for stations in your area. The station ID is in the URL (e.g., `tempestwx.com/station/98272` → station ID is `98272`).

### Calibration Process

1. **Start calibration mode** with sufficient wind activity (>1 knot recommended)
2. **Sample collection** - Plugin automatically collects comparison data
3. **Statistical analysis** - Calculates calibration factors with confidence metrics
4. **Results display** - Shows recommended calibration values and command line
5. **Application** - Restart plugin with suggested calibration parameters

### Example Calibration Output

```
==================================================
TEMPEST CALIBRATION RESULTS
==================================================
Recommended calibration factor: 1.2340
Recommended direction offset: -15.50°
Speed confidence: 0.892
Direction confidence: 0.934
Sample count: 20
==================================================
To apply these calibrations, restart with:
--calibration-factor 1.2340 --direction-offset -15.50
==================================================
```

### Benefits

- **Professional Reference**: Tempest stations are commercially calibrated
- **Real-time Accuracy**: Uses current atmospheric conditions for calibration
- **Statistical Confidence**: Provides confidence metrics for calibration quality
- **Automated Process**: No manual measurement or calculation required
- **Network Integration**: Leverages existing weather monitoring infrastructure

### Requirements

- **Internet Connection**: Required to fetch Tempest station data
- **Geographic Proximity**: Reference station should be reasonably close (same weather conditions)
- **Wind Activity**: Calibration works best with moderate wind speeds (1-20 knots)
- **Time Synchronization**: Ensure system time is accurate for proper data correlation

### Calibration Data Topics

The plugin publishes calibration results to MQTT:
- `davis.calibration.speed_factor` - Recommended speed calibration factor
- `davis.calibration.direction_offset` - Recommended direction offset in degrees

Both include confidence metrics and sample count in metadata.

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
- `--timeout` : Serial port read timeout in seconds (default: `5.0`)
- `--calibration-factor` : Wind speed calibration factor (default: `1.0`)
- `--direction-offset` : Wind direction offset in degrees (default: `0.0`)
- `--direction-scale` : Wind direction scaling factor (default: `1.0`)
- `--reporting-interval` : MQTT reporting interval in seconds for averaged data (default: `60`)
- `--tempest-station` : Tempest weather station ID for calibration reference (e.g., 98272)
- `--tempest-calibration` : Enable automatic calibration using Tempest station data
- `--calibration-samples` : Number of samples to collect for Tempest calibration (default: 10)
- `--web-server` : Enable mini web server for monitoring
- `--web-port` : Web server port (default: `8080`)
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

**Scale potentiometer range (if it only covers 270° instead of 360°):**
```bash
python3 main.py --direction-scale 1.333
```

**Enable web monitoring interface:**
```bash
python3 main.py --web-server --web-port 8080
```

## Docker Deployment

### Using Pre-built Images (Recommended)

Multi-architecture Docker images are automatically built and published to GitHub Container Registry for both AMD64 and ARM64 platforms.

**Pull the latest image:**
```bash
docker pull ghcr.io/ericvh/waggle-davis-wind-sensor:latest
```

**Run with pre-built image:**
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

**Using specific version:**
```bash
docker pull ghcr.io/ericvh/waggle-davis-wind-sensor:v1.0.0
```

### Building Locally

**Build the Docker image:**
```bash
docker build -t davis-wind-sensor-plugin .
```

**Run locally built image:**
```bash
docker run --device=/dev/ttyACM2:/dev/ttyACM2 --privileged davis-wind-sensor-plugin
```

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
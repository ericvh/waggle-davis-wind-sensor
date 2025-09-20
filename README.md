# Davis Wind Sensor Plugin for Waggle

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
- **Continuous Data Processing**: Blocks waiting for new data instead of polling on intervals for maximum responsiveness
- **Robust Serial Communication**: Includes error handling, automatic reconnection, and buffer management
- **Configurable Parameters**: Serial port, baud rate, wind speed and direction calibration factors

## Data Outputs

The plugin publishes the following measurements:

### Primary Environmental Data (WXT-compatible)
| Measurement | Units | Description |
|-------------|-------|-------------|
| `env.wind.speed` | knots | Wind speed in knots |
| `env.wind.direction` | degrees | Wind direction (0-360°) |
| `env.wind.speed.mps` | m/s | Wind speed in meters per second |

### Davis-Specific Debug Data
| Measurement | Units | Description |
|-------------|-------|-------------|
| `davis.wind.rps` | rps | Sensor rotations per second |
| `davis.wind.rpm.tops` | rpm | Debounced RPM count |
| `davis.wind.rpm.raw` | rpm | Raw RPM count |
| `davis.wind.pot.value` | counts | Raw potentiometer value (0-1024) |
| `davis.wind.iteration` | count | Arduino iteration counter |
| `davis.wind.sensor_status` | status | Sensor status (0=error, 1=ok) |

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

## Usage

### Command Line Arguments

```bash
python3 main.py [options]
```

**Options:**
- `--port` : Serial port device (default: `/dev/ttyUSB0`)
- `--baudrate` : Serial port baud rate (default: `9600`)
- `--timeout` : Serial port read timeout in seconds (default: `5.0`)
- `--calibration-factor` : Wind speed calibration factor (default: `1.0`)
- `--direction-offset` : Wind direction offset in degrees (default: `0.0`)
- `--direction-scale` : Wind direction scaling factor (default: `1.0`)
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

## Docker Deployment

### Build the Docker image:
```bash
docker build -t davis-wind-sensor-plugin .
```

### Run with Docker:
```bash
docker run --device=/dev/ttyUSB0:/dev/ttyUSB0 --privileged davis-wind-sensor-plugin
```

### Custom configuration:
```bash
docker run --device=/dev/ttyUSB0:/dev/ttyUSB0 --privileged \
  davis-wind-sensor-plugin --port /dev/ttyUSB0 --baudrate 9600 --debug \
  --calibration-factor 1.05 --direction-offset -15.0
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
sudo chmod 666 /dev/ttyUSB0
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
- Check if the device is connected: `ls /dev/ttyUSB*`
- Verify permissions: `ls -l /dev/ttyUSB0`
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
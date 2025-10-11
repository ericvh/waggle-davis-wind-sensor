# Tempest Weather Station Waggle Plugin

A standalone Waggle plugin that receives UDP broadcasts from a local Tempest weather station and publishes the data to the Waggle message stream.

## Overview

This plugin extracts the Tempest functionality from the main waggle-davis project and provides it as an independent service. It listens for UDP broadcasts from Tempest weather stations and publishes comprehensive weather data including wind, temperature, humidity, pressure, precipitation, and lightning information.

## Features

- **Real-time Data Publishing**: Publishes Tempest weather data to Waggle message stream
- **Comprehensive Weather Data**: Wind speed/direction, temperature, humidity, pressure, precipitation, lightning
- **Multiple Data Sources**: Supports both observation (`obs_st`) and rapid wind (`rapid_wind`) messages
- **Automatic Parsing**: Parses Tempest UDP message formats automatically
- **Robust Error Handling**: Continues operating even with intermittent data issues
- **Docker Support**: Containerized for easy deployment
- **Configurable**: Customizable UDP port, publish intervals, and debug modes

## Published Data Topics

### Wind Data
- `tempest.wind.speed.lull` - Wind lull speed (knots)
- `tempest.wind.speed.avg` - Average wind speed (knots)
- `tempest.wind.speed.gust` - Wind gust speed (knots)
- `tempest.wind.direction` - Wind direction (degrees)
- `tempest.wind.speed.instant` - Instant wind speed (knots, rapid updates)
- `tempest.wind.direction.instant` - Instant wind direction (degrees, rapid updates)

### Environmental Data
- `tempest.pressure` - Barometric pressure (hPa)
- `tempest.temperature` - Air temperature (°C)
- `tempest.humidity` - Relative humidity (%)

### Light Data
- `tempest.light.illuminance` - Illuminance (lux)
- `tempest.light.uv_index` - UV index
- `tempest.light.solar_radiation` - Solar radiation (W/m²)

### Precipitation Data
- `tempest.rain.since_report` - Rain since last report (mm)
- `tempest.rain.daily` - Daily rainfall (mm)

### Lightning Data
- `tempest.lightning.distance` - Lightning distance (km)
- `tempest.lightning.count` - Lightning strike count

### System Data
- `tempest.battery` - Battery voltage (V)
- `tempest.report_interval` - Report interval (minutes)
- `tempest.hub.firmware` - Hub firmware version
- `tempest.hub.uptime` - Hub uptime (seconds)
- `tempest.hub.rssi` - Signal strength (dBm)
- `tempest.status` - Plugin status (1=active, 0=error)

## Installation

### Docker (Recommended)

```bash
# Build the container
cd tempest-plugin
docker build -t tempest-weather-plugin .

# Run with host networking (required for UDP broadcasts)
docker run --network host tempest-weather-plugin
```

### Direct Python

```bash
# Install dependencies
pip install -r requirements.txt

# Run the plugin
python3 main.py
```

## Usage

### Basic Usage

```bash
# Run with default settings
python3 main.py

# Run with debug output
python3 main.py --debug

# Use custom UDP port
python3 main.py --udp-port 50223

# Set custom publish interval
python3 main.py --publish-interval 30
```

### Docker Usage

```bash
# Basic deployment
docker run --network host tempest-weather-plugin

# With environment variables
docker run --network host \
  -e TEMPEST_UDP_PORT=50222 \
  -e TEMPEST_PUBLISH_INTERVAL=60 \
  -e TEMPEST_DEBUG=true \
  tempest-weather-plugin

# With custom arguments
docker run --network host tempest-weather-plugin --debug --udp-port 50223
```

## Configuration

### Environment Variables

- `TEMPEST_UDP_PORT` - UDP port to listen for broadcasts (default: 50222)
- `TEMPEST_PUBLISH_INTERVAL` - Minimum publish interval in seconds (default: 60)
- `TEMPEST_DEBUG` - Enable debug output (default: false)

### Command Line Arguments

- `--udp-port PORT` - UDP port for Tempest broadcasts (default: 50222)
- `--debug` - Enable debug output
- `--publish-interval SECONDS` - Minimum publish interval (default: 60)
- `--no-firewall` - Skip firewall setup warnings

## Network Requirements

### UDP Port Access

The plugin requires access to UDP port 50222 (default) to receive Tempest broadcasts. This typically requires:

1. **Same Network**: Tempest station and plugin must be on the same network
2. **Firewall Configuration**: UDP port 50222 must be accessible
3. **Broadcasting Enabled**: Tempest station must have UDP broadcasting enabled

### Firewall Setup

If you encounter connectivity issues, you may need to configure firewall rules:

```bash
# Allow UDP port 50222
sudo iptables -I INPUT -p udp --dport 50222 -j ACCEPT

# Or use the firewall-opener container from the main project
docker run --privileged firewall-opener
```

## Integration with Main Project

This plugin can be used alongside the main waggle-davis project:

### Sidecar Deployment

```bash
# Start firewall opener
docker run --privileged --name firewall-opener -d firewall-opener

# Start Tempest plugin
docker run --network container:firewall-opener --name tempest-plugin -d tempest-weather-plugin

# Start Davis plugin (with --no-firewall since firewall is handled separately)
docker run --device=/dev/ttyACM2 --name davis-plugin -d waggle-davis --no-firewall
```

### Docker Compose

```yaml
version: '3.8'
services:
  firewall-opener:
    build: ../firewall-opener
    privileged: true
    restart: unless-stopped
    
  tempest-plugin:
    build: .
    network_mode: host
    depends_on:
      - firewall-opener
    restart: unless-stopped
    
  davis-plugin:
    build: ..
    devices:
      - /dev/ttyACM2:/dev/ttyACM2
    command: ["--no-firewall"]
    restart: unless-stopped
```

## Troubleshooting

### No Data Received

1. **Check Network**: Ensure Tempest station and plugin are on same network
2. **Verify Broadcasting**: Confirm Tempest station has UDP broadcasting enabled
3. **Firewall Issues**: Check if UDP port 50222 is accessible
4. **Port Conflicts**: Try different UDP port with `--udp-port`

### Debug Mode

Enable debug output to see detailed information:

```bash
python3 main.py --debug
```

This will show:
- UDP listener status
- Received message types
- Parsing errors
- Publication confirmations

### Testing Connection

Test UDP connectivity:

```bash
# Test port accessibility
netstat -uln | grep 50222

# Test with netcat (if Tempest is broadcasting)
nc -u -l 50222
```

## Data Flow

1. **UDP Reception**: Plugin listens for UDP broadcasts on port 50222
2. **Message Parsing**: JSON messages are parsed into structured data
3. **Data Publishing**: Parsed data is published to Waggle message stream
4. **Error Handling**: Invalid messages are logged but don't stop operation

## Message Types

### obs_st (Observation Station)
- Comprehensive weather observations
- Updated every few minutes
- Includes wind, temperature, humidity, pressure, precipitation, lightning

### rapid_wind
- High-frequency wind updates
- Updated every few seconds
- Includes instant wind speed and direction

### hub_status
- Hub system information
- Includes firmware, uptime, signal strength

## Development

### Building from Source

```bash
git clone <repository>
cd tempest-plugin
docker build -t tempest-weather-plugin .
```

### Testing

```bash
# Test with debug output
python3 main.py --debug

# Test with custom port
python3 main.py --udp-port 50223 --debug
```

## License

MIT License - see LICENSE file for details.

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## Support

For issues and questions:
- Check the troubleshooting section
- Review the main waggle-davis project documentation
- Open an issue on the project repository


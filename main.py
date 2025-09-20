#!/usr/bin/env python3

import argparse
import logging
import math
import time
import serial
import re
from contextlib import contextmanager
from waggle.plugin import Plugin


# Wind speed conversion constants
MPS_TO_KNOTS = 1.94384  # meters per second to knots conversion factor

# Davis anemometer calibration
# Default RPM to wind speed conversion: speed (m/s) = RPM * 0.098
# This factor may need adjustment based on your specific Davis anemometer model
# Common Davis anemometers use cup sizes that result in this conversion factor
DEFAULT_RPM_TO_MPS = 0.098


def parse_args():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description="Wind sensor plugin for Waggle - reads wind data from USB serial port"
    )
    parser.add_argument(
        "--port", 
        default="/dev/ttyUSB0", 
        help="Serial port device (default: /dev/ttyUSB0)"
    )
    parser.add_argument(
        "--baudrate", 
        type=int, 
        default=9600, 
        help="Serial port baud rate (default: 9600)"
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
    return parser.parse_args()


class WindSensorReader:
    """Wind sensor data reader for USB serial devices"""
    
    def __init__(self, port, baudrate=9600, timeout=5.0, calibration_factor=1.0, 
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
    logger.info("Waiting for data from Davis wind sensor...")
    
    try:
        # Main loop with automatic reconnection
        while True:
            try:
                # Continuously read and process data as it arrives
                with wind_reader.serial_connection() as ser:
                    logger.info("Connected to serial port, reading data continuously...")
                    
                    while True:
                        try:
                            # Block waiting for a line of data
                            line = ser.readline().decode('utf-8', errors='ignore')
                            
                            if line.strip():  # Only process non-empty lines
                                logger.debug(f"Raw serial data: {line.strip()}")
                                wind_data = wind_reader.parse_wind_data(line)
                                
                                if wind_data:
                                    # Primary measurements using WXT-style topic naming
                                    plugin.publish("env.wind.speed", wind_data['wind_speed_knots'], 
                                                 meta={"units": "knots", "description": "Wind speed in knots"})
                                    plugin.publish("env.wind.direction", wind_data['wind_direction_deg'], 
                                                 meta={"units": "degrees", "description": "Wind direction in degrees"})
                                    
                                    # Additional measurements 
                                    plugin.publish("env.wind.speed.mps", wind_data['wind_speed_mps'], 
                                                 meta={"units": "m/s", "description": "Wind speed in meters per second"})
                                    
                                    # Debug measurements - Davis-specific data
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
                                    
                                    # Publish sensor status as OK
                                    plugin.publish("davis.wind.sensor_status", 1, 
                                                 meta={"description": "Davis wind sensor status (0=error, 1=ok)"})
                                    
                                    logger.info(f"Wind: {wind_data['wind_speed_knots']:.2f} knots, "
                                               f"{wind_data['wind_direction_deg']:.1f}°")
                                    
                                    if args.debug:
                                        logger.debug(f"Debug - Iteration: {wind_data['iteration']}, "
                                                    f"PotValue: {wind_data['pot_value']}, "
                                                    f"RPM Tops: {wind_data['rpm_tops']}, "
                                                    f"RPM Raw: {wind_data['rpm_raw']}, "
                                                    f"RPS: {wind_data['rotations_per_second']:.3f}, "
                                                    f"Speed (m/s): {wind_data['wind_speed_mps']:.2f}")
                                else:
                                    logger.debug(f"Could not parse line: {line.strip()}")
                                    
                        except serial.SerialTimeoutException:
                            logger.debug("Serial read timeout, continuing...")
                            continue
                        except serial.SerialException as e:
                            logger.error(f"Serial communication error: {e}")
                            raise  # Re-raise to trigger reconnection
                            
            except (serial.SerialException, OSError) as e:
                logger.error(f"Serial port error: {e}")
                # Publish error status
                plugin.publish("davis.wind.sensor_status", 0, 
                             meta={"description": "Davis wind sensor status (0=error, 1=ok)"})
                logger.info("Attempting to reconnect in 5 seconds...")
                time.sleep(5.0)
                continue
                
    except KeyboardInterrupt:
        logger.info("Wind sensor plugin stopped by user")
    except Exception as e:
        logger.error(f"Unexpected error in wind sensor plugin: {e}")
        raise


if __name__ == "__main__":
    main() 
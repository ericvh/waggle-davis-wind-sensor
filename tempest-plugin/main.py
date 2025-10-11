#!/usr/bin/env python3

"""
Tempest Weather Station Waggle Plugin
=====================================

A Waggle plugin that receives UDP broadcasts from a local Tempest weather station
and publishes the data to the Waggle message stream.

This plugin extracts the Tempest functionality from the main waggle-davis project
and provides it as a standalone service for publishing Tempest weather data.
"""

import argparse
import logging
import json
import os
import socket
import threading
import time
from datetime import datetime, timezone
from waggle.plugin import Plugin


# Tempest UDP broadcast port
UDP_PORT = 50222

# Global Tempest data storage
tempest_data_lock = threading.Lock()
latest_tempest_raw_by_type = {}
latest_tempest_parsed_by_type = {}

# Global plugin instance
plugin = None


# ---------------- Unit Conversion Functions ----------------
def c_to_f(c): 
    return None if c is None else (c * 9/5) + 32

def mps_to_kt(m): 
    return None if m is None else m * 1.943844

def hpa_to_inhg(h): 
    return None if h is None else h * 0.0295299830714

def mm_to_in(mm): 
    return None if mm is None else mm / 25.4


# ---------------- Tempest Message Parsers ----------------
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

# Message type parsers
TEMPEST_PARSERS = {
    "obs_st": parse_obs_st,
    "rapid_wind": parse_rapid_wind,
    "hub_status": parse_hub_status,
}


# ---------------- Data Publishing Functions ----------------
def publish_tempest_data(parsed_data, msg_type, logger):
    """Publish Tempest data to Waggle message stream"""
    global plugin
    
    if not plugin:
        logger.error("Plugin not initialized")
        return
    
    try:
        if msg_type == "obs_st" and "error" not in parsed_data:
            # Publish comprehensive weather observations
            obs = parsed_data
            
            # Wind data
            plugin.publish("tempest.wind.speed.lull", obs["wind"]["lull_kt"], 
                         meta={"units": "knots", "description": "Tempest wind lull speed", "source": "obs_st"})
            plugin.publish("tempest.wind.speed.avg", obs["wind"]["avg_kt"], 
                         meta={"units": "knots", "description": "Tempest average wind speed", "source": "obs_st"})
            plugin.publish("tempest.wind.speed.gust", obs["wind"]["gust_kt"], 
                         meta={"units": "knots", "description": "Tempest wind gust speed", "source": "obs_st"})
            plugin.publish("tempest.wind.direction", obs["wind"]["direction_deg"], 
                         meta={"units": "degrees", "description": "Tempest wind direction", "source": "obs_st"})
            
            # Environmental data
            plugin.publish("tempest.pressure", obs["pressure"]["hpa"], 
                         meta={"units": "hPa", "description": "Tempest barometric pressure", "source": "obs_st"})
            plugin.publish("tempest.temperature", obs["temperature"]["c"], 
                         meta={"units": "celsius", "description": "Tempest air temperature", "source": "obs_st"})
            plugin.publish("tempest.humidity", obs["humidity_percent"], 
                         meta={"units": "percent", "description": "Tempest relative humidity", "source": "obs_st"})
            
            # Light data
            plugin.publish("tempest.light.illuminance", obs["light"]["illuminance_lux"], 
                         meta={"units": "lux", "description": "Tempest illuminance", "source": "obs_st"})
            plugin.publish("tempest.light.uv_index", obs["light"]["uv_index"], 
                         meta={"units": "index", "description": "Tempest UV index", "source": "obs_st"})
            plugin.publish("tempest.light.solar_radiation", obs["light"]["solar_radiation_wm2"], 
                         meta={"units": "W/m²", "description": "Tempest solar radiation", "source": "obs_st"})
            
            # Precipitation data
            plugin.publish("tempest.rain.since_report", obs["rain"]["since_report_mm"], 
                         meta={"units": "mm", "description": "Tempest rain since report", "source": "obs_st"})
            plugin.publish("tempest.rain.daily", obs["rain"]["local_day_mm"] or 0, 
                         meta={"units": "mm", "description": "Tempest daily rainfall", "source": "obs_st"})
            
            # Lightning data
            plugin.publish("tempest.lightning.distance", obs["lightning"]["avg_distance_km"], 
                         meta={"units": "km", "description": "Tempest lightning distance", "source": "obs_st"})
            plugin.publish("tempest.lightning.count", obs["lightning"]["strike_count"], 
                         meta={"units": "count", "description": "Tempest lightning strike count", "source": "obs_st"})
            
            # Battery and system data
            plugin.publish("tempest.battery", obs["battery_v"], 
                         meta={"units": "volts", "description": "Tempest battery voltage", "source": "obs_st"})
            plugin.publish("tempest.report_interval", obs["report_interval_min"], 
                         meta={"units": "minutes", "description": "Tempest report interval", "source": "obs_st"})
            
            logger.debug(f"Published obs_st data: {obs['wind']['avg_kt']:.1f} kt, {obs['wind']['direction_deg']:.0f}°")
            
        elif msg_type == "rapid_wind" and "error" not in parsed_data:
            # Publish rapid wind data (most recent wind readings)
            wind = parsed_data["wind"]
            
            plugin.publish("tempest.wind.speed.instant", wind["instant_kt"], 
                         meta={"units": "knots", "description": "Tempest instant wind speed", "source": "rapid_wind"})
            plugin.publish("tempest.wind.direction.instant", wind["direction_deg"], 
                         meta={"units": "degrees", "description": "Tempest instant wind direction", "source": "rapid_wind"})
            
            logger.debug(f"Published rapid_wind data: {wind['instant_kt']:.1f} kt, {wind['direction_deg']:.0f}°")
            
        elif msg_type == "hub_status" and "error" not in parsed_data:
            # Publish hub status data
            plugin.publish("tempest.hub.firmware", parsed_data["firmware"] or "unknown", 
                         meta={"description": "Tempest hub firmware version", "source": "hub_status"})
            plugin.publish("tempest.hub.uptime", parsed_data["uptime_s"] or 0, 
                         meta={"units": "seconds", "description": "Tempest hub uptime", "source": "hub_status"})
            plugin.publish("tempest.hub.rssi", parsed_data["rssi"] or 0, 
                         meta={"units": "dBm", "description": "Tempest hub signal strength", "source": "hub_status"})
            
            logger.debug(f"Published hub_status data: firmware={parsed_data['firmware']}, uptime={parsed_data['uptime_s']}s")
            
        # Always publish a heartbeat/status message
        plugin.publish("tempest.status", 1, 
                     meta={"description": "Tempest plugin status (1=active, 0=error)", "last_update": int(time.time())})
        
    except Exception as e:
        logger.error(f"Error publishing Tempest data: {e}")
        plugin.publish("tempest.status", 0, 
                     meta={"description": "Tempest plugin status (1=active, 0=error)", "error": str(e)})


# ---------------- UDP Listener ----------------
def tempest_udp_listener(logger):
    """UDP listener thread for Tempest broadcasts"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", UDP_PORT))
        
        logger.info(f"🌐 Tempest UDP listener started on port {UDP_PORT}")
        
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
                            
                            # Publish the data immediately
                            publish_tempest_data(parsed_data, msg_type, logger)
                            
                        except Exception as e:
                            logger.error(f"Error parsing {msg_type} message: {e}")
                            # Skip parsing errors but continue listening
                    else:
                        # If no parser, remove any stale parsed entry
                        if msg_type in latest_tempest_parsed_by_type:
                            del latest_tempest_parsed_by_type[msg_type]
                        logger.debug(f"Received unknown message type: {msg_type}")
                            
            except json.JSONDecodeError:
                # Skip non-JSON packets
                continue
            except Exception as e:
                # Log UDP errors but continue listening
                logger.error(f"UDP listener error: {e}")
                continue
                
    except Exception as e:
        logger.error(f"Failed to start Tempest UDP listener: {e}")
        # Publish error status
        global plugin
        if plugin:
            plugin.publish("tempest.status", 0, 
                         meta={"description": "Tempest plugin status (1=active, 0=error)", "error": str(e)})


# ---------------- Command Line Arguments ----------------
def parse_args():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description="Tempest Weather Station Waggle Plugin - publishes Tempest UDP data to Waggle stream"
    )
    parser.add_argument(
        "--udp-port", 
        type=int,
        default=UDP_PORT, 
        help=f"UDP port to listen for Tempest broadcasts (default: {UDP_PORT})"
    )
    parser.add_argument(
        "--debug", 
        action="store_true", 
        help="Enable debug output"
    )
    parser.add_argument(
        "--publish-interval", 
        type=int, 
        default=60, 
        help="Minimum interval between data publications in seconds (default: 60)"
    )
    parser.add_argument(
        "--no-firewall", 
        action="store_true", 
        help="Skip firewall setup warnings (assumes port is already accessible)"
    )
    return parser.parse_args()


# ---------------- Main Function ----------------
def main():
    """Main function"""
    global plugin
    
    args = parse_args()
    
    # Configure logging
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    logger = logging.getLogger(__name__)
    
    # Initialize Waggle plugin
    plugin = Plugin()
    
    logger.info("🌤️  Starting Tempest Weather Station Waggle Plugin")
    logger.info("=" * 60)
    logger.info(f"UDP Port: {args.udp_port}")
    logger.info(f"Publish Interval: {args.publish_interval} seconds")
    logger.info(f"Debug Mode: {args.debug}")
    logger.info("")
    
    # Check port accessibility
    if not args.no_firewall:
        logger.info("🔍 Checking UDP port accessibility...")
        try:
            test_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            test_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            test_sock.bind(("0.0.0.0", args.udp_port))
            test_sock.close()
            logger.info(f"✓ UDP port {args.udp_port} is accessible")
        except Exception as e:
            logger.warning(f"⚠️  UDP port {args.udp_port} binding failed: {e}")
            logger.warning("💡 You may need to configure firewall rules:")
            logger.warning(f"   sudo iptables -I INPUT -p udp --dport {args.udp_port} -j ACCEPT")
            logger.warning("   Or use the firewall-opener container from the main project")
    
    # Start UDP listener thread
    logger.info("🌐 Starting Tempest UDP listener thread...")
    udp_thread = threading.Thread(
        target=tempest_udp_listener, 
        args=(logger,),
        daemon=True
    )
    udp_thread.start()
    
    # Wait for initial data
    logger.info("⏳ Waiting for Tempest UDP broadcasts...")
    time.sleep(5)  # Give some time for initial data
    
    # Check if we received any data
    with tempest_data_lock:
        if latest_tempest_raw_by_type:
            logger.info(f"✅ Tempest station detected! Received {len(latest_tempest_raw_by_type)} message types:")
            for msg_type in latest_tempest_raw_by_type.keys():
                logger.info(f"   - {msg_type}")
        else:
            logger.warning("⚠️  No Tempest data received yet")
            logger.info("💡 Troubleshooting:")
            logger.info("   1. Check that Tempest hub is on the same network")
            logger.info("   2. Verify Tempest station is broadcasting (usually enabled by default)")
            logger.info("   3. Check firewall/router settings for UDP port 50222")
            logger.info("   4. Try running with --no-firewall if you've already configured firewall")
    
    logger.info("")
    logger.info("📡 Tempest plugin is running and publishing data to Waggle stream")
    logger.info("🛑 Press Ctrl+C to stop")
    logger.info("")
    
    try:
        # Main loop - just keep the plugin running
        # The UDP listener thread handles all data processing and publishing
        while True:
            time.sleep(60)  # Check every minute
            
            # Periodic status update
            with tempest_data_lock:
                if latest_tempest_raw_by_type:
                    logger.info(f"📊 Status: Active, {len(latest_tempest_raw_by_type)} message types received")
                else:
                    logger.warning("📊 Status: No data received from Tempest station")
                    
    except KeyboardInterrupt:
        logger.info("🛑 Tempest plugin stopped by user")
    except Exception as e:
        logger.error(f"❌ Unexpected error in Tempest plugin: {e}")
        raise
    finally:
        # Cleanup
        logger.info("🧹 Cleaning up Tempest plugin...")
        if plugin:
            plugin.publish("tempest.status", 0, 
                         meta={"description": "Tempest plugin status (1=active, 0=error)", "state": "shutdown"})


if __name__ == "__main__":
    main()


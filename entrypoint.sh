#!/bin/bash

# Flexible entrypoint for Davis Wind Sensor Plugin
# Supports both main plugin and Tempest calibration modes

set -e

# Default mode
MODE="${DAVIS_MODE:-main}"

# Help function
show_help() {
    echo "Davis Wind Sensor Docker Container"
    echo "=================================="
    echo ""
    echo "Usage:"
    echo "  docker run ... ericvh/waggle-davis-wind-sensor [OPTIONS]"
    echo ""
    echo "Modes (set via DAVIS_MODE environment variable):"
    echo "  main       - Run Davis wind sensor plugin (default)"
    echo "  calibrate  - Run Tempest calibration (interactive)"
    echo "  web        - Run Tempest calibration web interface"
    echo "  continuous - Run continuous auto-calibration (15-minute intervals)"
    echo "  test       - Test Tempest UDP connection"
    echo ""
    echo "Examples:"
    echo "  # Run main Davis plugin"
    echo "  docker run --device=/dev/ttyACM2 ericvh/waggle-davis-wind-sensor"
    echo ""
    echo "  # Run calibration in interactive mode"
    echo "  docker run -e DAVIS_MODE=calibrate -it --network host ericvh/waggle-davis-wind-sensor"
    echo ""
    echo "  # Run calibration web interface"
    echo "  docker run -e DAVIS_MODE=web -p 8080:8080 --network host ericvh/waggle-davis-wind-sensor"
    echo ""
    echo "  # Run continuous auto-calibration"
    echo "  docker run -e DAVIS_MODE=continuous --device=/dev/ttyACM2 --network host ericvh/waggle-davis-wind-sensor"
    echo ""
    echo "  # Test UDP connection"
    echo "  docker run -e DAVIS_MODE=test --network host ericvh/waggle-davis-wind-sensor"
    echo ""
    echo "Environment Variables:"
    echo "  DAVIS_MODE        - Operation mode (main|calibrate|web|continuous|test)"
    echo "  TEMPEST_PORT      - Tempest web server port (default: 8080)"
    echo "  NO_FIREWALL       - Skip firewall setup (set to 'true')"
    echo ""
    echo "Docker Network Notes:"
    echo "  - For Tempest calibration, use --network host for UDP broadcasts"
    echo "  - May need --privileged for firewall management in containers"
    echo "  - Web interface needs port mapping: -p 8080:8080"
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --help|-h)
            show_help
            exit 0
            ;;
        --mode)
            MODE="$2"
            shift 2
            ;;
        *)
            # Pass through all other arguments
            EXTRA_ARGS+=("$1")
            shift
            ;;
    esac
done

# Function to check if we're in a container environment
check_container_env() {
    if [ -f /.dockerenv ] || grep -q docker /proc/1/cgroup 2>/dev/null; then
        echo "🐳 Running in Docker container"
        
        # Check for network host mode (needed for UDP broadcasts)
        if [ "$MODE" != "main" ]; then
            local has_host_net=false
            
            # Check if we can see host network interfaces
            if ip route show | grep -q "default via.*docker0" 2>/dev/null; then
                echo "⚠️  Warning: Using Docker bridge network"
                echo "   Tempest UDP broadcasts may not work properly"
                echo "   Consider using: --network host"
            else
                echo "✓ Network configuration appears suitable for UDP broadcasts"
            fi
        fi
        
        # Check for privileged mode if firewall management needed
        if [ "$MODE" != "main" ] && [ "$NO_FIREWALL" != "true" ]; then
            if [ -w /proc/sys/net ] 2>/dev/null; then
                echo "✓ Container has network privileges for firewall management"
            else
                echo "⚠️  Warning: Limited network privileges"
                echo "   Firewall management may not work"
                echo "   Consider using: --privileged or set NO_FIREWALL=true"
            fi
        fi
        echo ""
    fi
}

# Function to wait for device availability (for main mode)
wait_for_device() {
    local device="$1"
    local timeout=30
    local count=0
    
    if [ -n "$device" ] && [[ "$device" == /dev/* ]]; then
        echo "Waiting for device $device..."
        while [ $count -lt $timeout ] && [ ! -e "$device" ]; do
            sleep 1
            count=$((count + 1))
            if [ $((count % 5)) -eq 0 ]; then
                echo "Still waiting for $device ($count/${timeout}s)"
            fi
        done
        
        if [ ! -e "$device" ]; then
            echo "❌ Device $device not found after ${timeout}s"
            echo "Make sure device is connected and mapped: --device=$device"
            exit 1
        else
            echo "✓ Device $device found"
        fi
    fi
}

# Main execution logic
main() {
    echo "Davis Wind Sensor Container Starting..."
    echo "Mode: $MODE"
    echo ""
    
    # Check container environment for calibration modes
    if [ "$MODE" != "main" ]; then
        check_container_env
    fi
    
    case "$MODE" in
        "main")
            echo "🌪️  Starting Davis Wind Sensor Plugin"
            echo "======================================="
            
            # Check for device in arguments
            for arg in "${EXTRA_ARGS[@]}"; do
                if [[ "$arg" == --port* ]] || [[ "$arg" == /dev/* ]]; then
                    if [[ "$arg" == /dev/* ]]; then
                        wait_for_device "$arg"
                    elif [[ "$arg" == --port ]]; then
                        # Next argument should be the device
                        wait_for_device "${EXTRA_ARGS[1]}"
                    fi
                    break
                fi
            done
            
            exec python3 main.py "${EXTRA_ARGS[@]}"
            ;;
            
        "calibrate")
            echo "🎯 Starting Tempest Calibration (Interactive Mode)"
            echo "================================================="
            echo "This mode requires interactive terminal input"
            echo "Make sure you run with: docker run -it ..."
            echo ""
            
            # Build tempest args
            tempest_args=("--calibrate")
            if [ "$NO_FIREWALL" = "true" ]; then
                tempest_args+=("--no-firewall")
            fi
            tempest_args+=("${EXTRA_ARGS[@]}")
            
            exec python3 tempest.py "${tempest_args[@]}"
            ;;
            
        "web")
            echo "🌐 Starting Tempest Calibration Web Interface"
            echo "============================================"
            
            # Set default port
            port="${TEMPEST_PORT:-8080}"
            
            # Build tempest args
            tempest_args=("--port" "$port")
            if [ "$NO_FIREWALL" = "true" ]; then
                tempest_args+=("--no-firewall")
            fi
            tempest_args+=("${EXTRA_ARGS[@]}")
            
            echo "Web interface will be available at:"
            echo "  http://localhost:$port/calibration"
            echo ""
            
            exec python3 tempest.py "${tempest_args[@]}"
            ;;
            
        "test")
            echo "🔍 Testing Tempest UDP Connection"
            echo "================================"
            
            # Build tempest args
            tempest_args=("--test-connection")
            if [ "$NO_FIREWALL" = "true" ]; then
                tempest_args+=("--no-firewall")
            fi
            tempest_args+=("${EXTRA_ARGS[@]}")
            
            exec python3 tempest.py "${tempest_args[@]}"
            ;;
            
        "continuous")
            echo "🔄 Starting Continuous Tempest Calibration"
            echo "=========================================="
            echo "This mode continuously compares Davis and Tempest readings"
            echo "and automatically adjusts calibration every 15 minutes"
            echo ""
            
            # Check for device in arguments (similar to main mode)
            for arg in "${EXTRA_ARGS[@]}"; do
                if [[ "$arg" == --port* ]] || [[ "$arg" == /dev/* ]]; then
                    if [[ "$arg" == /dev/* ]]; then
                        wait_for_device "$arg"
                    elif [[ "$arg" == --port ]]; then
                        # Next argument should be the device
                        wait_for_device "${EXTRA_ARGS[1]}"
                    fi
                    break
                fi
            done
            
            # Build tempest args
            tempest_args=("--continuous")
            if [ "$NO_FIREWALL" = "true" ]; then
                tempest_args+=("--no-firewall")
            fi
            tempest_args+=("${EXTRA_ARGS[@]}")
            
            exec python3 tempest.py "${tempest_args[@]}"
            ;;
            
        *)
            echo "❌ Unknown mode: $MODE"
            echo "Valid modes: main, calibrate, web, continuous, test"
            echo ""
            show_help
            exit 1
            ;;
    esac
}

# Handle signals gracefully
trap 'echo "Received interrupt signal, shutting down..."; exit 0' INT TERM

# Run main function
main "$@" 
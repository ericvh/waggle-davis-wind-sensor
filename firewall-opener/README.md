# Firewall Opener Container

A standalone Docker container for managing iptables firewall rules to allow UDP broadcasts from Tempest weather stations.

## Purpose

This container extracts the firewall management functionality from the main waggle-davis project, allowing you to:

- Open UDP ports for Tempest weather station broadcasts
- Manage iptables rules in a containerized environment
- Provide firewall management as a separate service

## Usage

### Basic Setup (Open Port)

```bash
# Build the container
docker build -t firewall-opener .

# Run with default settings (opens port 50222)
docker run --privileged firewall-opener

# Run with custom port
docker run --privileged -e FIREWALL_PORT=50223 firewall-opener

# Run and wait for a specific time (useful for testing)
docker run --privileged -e FIREWALL_WAIT=60 firewall-opener
```

### Different Actions

```bash
# Setup firewall rules (default)
docker run --privileged firewall-opener setup

# Check firewall status
docker run --privileged firewall-opener status

# Cleanup firewall rules
docker run --privileged firewall-opener cleanup
```

### Environment Variables

- `FIREWALL_PORT`: UDP port to manage (default: 50222)
- `FIREWALL_ACTION`: Action to perform - setup, cleanup, or status (default: setup)
- `FIREWALL_WAIT`: Wait N seconds after action before exiting (default: 0)

### Command Line Override

You can override environment variables with command line arguments:

```bash
docker run --privileged firewall-opener --port 50223 --action status
```

## Docker Run Options

### Privileged Mode (Recommended)

```bash
docker run --privileged firewall-opener
```

This gives the container full access to modify iptables rules.

### Capability-Based Security (Alternative)

```bash
docker run --cap-add=NET_ADMIN --cap-add=NET_RAW firewall-opener
```

This provides only the necessary capabilities for network management.

### Host Network Mode

```bash
docker run --privileged --network host firewall-opener
```

Use this if you need the container to access the host's network interfaces directly.

## Integration with Main Project

This container can be used as a sidecar container alongside the main waggle-davis container:

```bash
# Start firewall opener
docker run --privileged --name firewall-opener -d firewall-opener

# Start main waggle-davis container (with --no-firewall flag)
docker run --device=/dev/ttyACM2 --network container:firewall-opener waggle-davis --no-firewall
```

## Troubleshooting

### Permission Issues

If you get permission errors:

```bash
# Try with privileged mode
docker run --privileged firewall-opener

# Or check if you need sudo
sudo docker run firewall-opener
```

### Port Already Open

The container will detect if the port is already open and skip adding duplicate rules:

```bash
docker run --privileged firewall-opener status
```

### Manual Firewall Commands

If the container fails, you can manually open the port:

```bash
# On the host system
sudo iptables -I INPUT -p udp --dport 50222 -j ACCEPT

# Check if rule was added
sudo iptables -L INPUT -n --line-numbers | grep 50222

# Remove the rule when done
sudo iptables -D INPUT -p udp --dport 50222 -j ACCEPT
```

## Building from Source

```bash
cd firewall-opener
docker build -t firewall-opener .
```

## Testing

```bash
# Test port accessibility
docker run --privileged firewall-opener --action status

# Test with a specific port
docker run --privileged firewall-opener --port 50223 --action status

# Test cleanup
docker run --privileged firewall-opener --action cleanup
```

## Security Notes

- This container modifies system firewall rules
- Only run with necessary privileges
- Consider using capability-based security instead of full privileged mode
- The container automatically cleans up rules on exit
- Rules are tagged with comments for easy identification and cleanup

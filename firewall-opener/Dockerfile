FROM python:3.9-slim

# Install system dependencies for firewall management
RUN apt-get update && apt-get install -y \
    iptables \
    iputils-ping \
    net-tools \
    && rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app

# Copy the firewall manager script
COPY firewall_manager.py /app/
RUN chmod +x /app/firewall_manager.py

# Set default environment variables
ENV FIREWALL_PORT=50222
ENV FIREWALL_ACTION=setup
ENV FIREWALL_WAIT=0

# Create entrypoint script
RUN echo '#!/bin/bash\n\
set -e\n\
\n\
# Default values\n\
PORT="${FIREWALL_PORT:-50222}"\n\
ACTION="${FIREWALL_ACTION:-setup}"\n\
WAIT="${FIREWALL_WAIT:-0}"\n\
\n\
echo "🔥 Firewall Opener Container Starting..."\n\
echo "Port: $PORT"\n\
echo "Action: $ACTION"\n\
echo "Wait: $WAIT seconds"\n\
echo ""\n\
\n\
# Check if we have the necessary privileges\n\
if [ ! -w /proc/sys/net ] 2>/dev/null; then\n\
    echo "⚠️  Warning: Container may not have sufficient privileges for firewall management"\n\
    echo "   Consider running with: --privileged or --cap-add=NET_ADMIN"\n\
    echo ""\n\
fi\n\
\n\
# Run the firewall manager\n\
exec python3 /app/firewall_manager.py --port "$PORT" --action "$ACTION" --wait "$WAIT" "$@"\n\
' > /app/entrypoint.sh

RUN chmod +x /app/entrypoint.sh

# Set the entrypoint
ENTRYPOINT ["/app/entrypoint.sh"]

# Default command (can be overridden)
CMD []

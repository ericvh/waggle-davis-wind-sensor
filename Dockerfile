FROM waggle/plugin-base:1.1.1-base

# Install system dependencies for serial communication
RUN apt-get update && apt-get install -y \
    iptables \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt /app/
RUN pip3 install --no-cache-dir -r /app/requirements.txt

# Copy plugin source code
COPY main.py /app/
COPY tempest.py /app/
COPY entrypoint.sh /app/

# Set the working directory
WORKDIR /app

# Make scripts executable
RUN chmod +x main.py tempest.py entrypoint.sh

# Set the flexible entrypoint
ENTRYPOINT ["/app/entrypoint.sh"] 

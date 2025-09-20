FROM waggle/plugin-base:1.1.1-base

# Install system dependencies for serial communication
RUN apt-get update && apt-get install -y \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt /app/
RUN pip3 install --no-cache-dir -r /app/requirements.txt

# Copy plugin source code
COPY main.py /app/

# Set the working directory
WORKDIR /app

# Make the main script executable
RUN chmod +x main.py

# Set the entrypoint
ENTRYPOINT ["python3", "main.py"] 
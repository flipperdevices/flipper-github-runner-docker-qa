#!/bin/bash

set -euo pipefail

# Check if script is run as root
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root"
    exit 1
fi

# Parse arguments
if [ "$#" -ne 2 ]; then
    echo "Usage: $0 FLIPPER_ID ST_LINK_ID"
    echo "Example: $0 flip_abc123 xyz789"
    exit 1
fi

FLIPPER_ID="$1"
ST_LINK_ID="$2"

echo "Installing Flipper GitHub Runner for:"
echo "Flipper ID: $FLIPPER_ID"
echo "ST-Link ID: $ST_LINK_ID"

# Install system dependencies
echo "Installing system dependencies..."
apt-get update
apt-get install -y docker-ce ccache python3-pip logrotate

# Install Python dependencies
echo "Installing Python dependencies..."
pip3 install pyudev docker pygelf

# Configure Docker logging
echo "Configuring Docker logging..."
mkdir -p /etc/docker
cat > /etc/docker/daemon.json << EOF
{
    "log-driver": "journald"
}
EOF

# Create required directories and copy files
echo "Setting up directories and files..."
mkdir -p /var/lib/flipper-docker
mkdir -p "/opt/${FLIPPER_ID}/logs"

# Copy Docker-related files
cp docker/* /var/lib/flipper-docker/

# Copy Python script to system
echo "Installing Python scripts..."
cp scripts/flipper_docker.py /usr/bin/
chmod +x /usr/bin/flipper_docker.py

# Create service file
echo "Creating systemd service..."
cat > "/etc/systemd/system/github-runner-${FLIPPER_ID}.service" << EOF
[Unit]
Description=Dockerized github runner ${FLIPPER_ID}
After=docker.service
Requires=docker.service

[Service]
TimeoutStartSec=0
Restart=always
ExecStart=sudo python3 /usr/bin/flipper_docker.py ${FLIPPER_ID} ${ST_LINK_ID} FlipperZeroTest
KillSignal=SIGINT

[Install]
WantedBy=multi-user.target
EOF

# Configure log rotation
echo "Configuring log rotation..."
cat > "/etc/logrotate.d/flip_all" << EOF
/opt/${FLIPPER_ID}/logs/*.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    dateext
    create 0644 root root
}
EOF

# Reload systemd and enable service
echo "Configuring systemd service..."
systemctl daemon-reload
systemctl restart docker
systemctl enable "github-runner-${FLIPPER_ID}"

echo "Installation complete!"
echo "Please ensure you have placed the following files in /var/lib/flipper-docker/:"
echo "1. flipper-docker.cfg"
echo "2. region_data"
echo ""
echo "Then start the service with:"
echo "systemctl start github-runner-${FLIPPER_ID}"
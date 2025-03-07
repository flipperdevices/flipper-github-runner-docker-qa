#!/bin/bash

set -euo pipefail

# Check if script is run as root
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root"
    exit 1
fi

echo "===== Flipper GitHub Runner Monitor Installer ====="
echo "This script will install the monitoring service for Flipper GitHub Runners"

# Define paths
MONITOR_SCRIPT_PATH="/usr/local/bin/github-runner-metrics.py"
SERVICE_FILE="/etc/systemd/system/github-runner-monitor.service"
METRICS_DIR="/var/lib/node_exporter/textfile_collector"
LOG_DIR="/var/log"

# Install system dependencies
echo "Installing system dependencies..."
apt-get update
apt-get install -y python3-pip docker.io

# Install Python dependencies
echo "Installing Python dependencies..."
pip3 install pyudev docker pygelf

# Create required directories
echo "Setting up directories..."
mkdir -p ${METRICS_DIR}
chmod 755 ${METRICS_DIR}

# Copy the monitoring script
echo "Installing monitoring script..."
cp scripts/flipper_monitor.py ${MONITOR_SCRIPT_PATH}
chmod +x ${MONITOR_SCRIPT_PATH}

# Copy the service file
echo "Installing systemd service..."
cat > ${SERVICE_FILE} << 'EOF'
[Unit]
Description=GitHub Runner Metrics Collector
After=docker.service node_exporter.service
Requires=docker.service

[Service]
Type=simple
User=root
Group=root
ExecStart=/usr/local/bin/github-runner-metrics.py --daemon
Restart=always
RestartSec=30

SupplementaryGroups=systemd-journal

PrivateTmp=yes
ProtectSystem=full
ReadWritePaths=/var/lib/node_exporter/textfile_collector /var/log
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF

# Set up log rotation for metrics logs
echo "Configuring log rotation..."
cat > "/etc/logrotate.d/github-runner-metrics" << EOF
/var/log/github-runner-metrics.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    create 0644 root root
}
EOF

# Reload systemd and enable service
echo "Configuring systemd service..."
systemctl daemon-reload
systemctl enable github-runner-monitor.service

echo "Installation complete!"
echo "The monitoring service is now installed and will start on next boot."
echo "To start it immediately, run: systemctl start github-runner-monitor.service"
echo ""
echo "The service uses the same configuration as the runners from:"
echo "/var/lib/flipper-docker/flipper-docker.cfg"
echo ""
echo "Metrics will be collected in: ${METRICS_DIR}"
echo "Logs will be written to: ${LOG_DIR}/github-runner-metrics.log"
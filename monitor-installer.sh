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
INSTALL_DIR="/opt/flipper-monitor"
VENV_DIR="${INSTALL_DIR}/venv"
MONITOR_SCRIPT="${INSTALL_DIR}/github-runner-metrics.py"
SERVICE_FILE="/etc/systemd/system/github-runner-monitor.service"
METRICS_DIR="/var/lib/node_exporter/textfile_collector"
LOG_DIR="/var/log"
WRAPPER_SCRIPT="/usr/local/bin/flipper-monitor-wrapper.sh"

# Create installation directory
echo "Creating installation directory..."
mkdir -p ${INSTALL_DIR}
mkdir -p ${METRICS_DIR}
chmod 755 ${METRICS_DIR}

# Set up Python virtual environment
echo "Setting up Python virtual environment..."
python3 -m venv ${VENV_DIR}
${VENV_DIR}/bin/pip install --upgrade pip
${VENV_DIR}/bin/pip install pyudev docker pygelf

# Copy the monitoring script
echo "Installing monitoring script..."
cp scripts/flipper_monitor.py ${MONITOR_SCRIPT}
chmod +x ${MONITOR_SCRIPT}

# Create a wrapper script to activate the virtual environment
echo "Creating wrapper script..."
cat > ${WRAPPER_SCRIPT} << EOF
#!/bin/bash
source ${VENV_DIR}/bin/activate
exec python ${MONITOR_SCRIPT} "\$@"
EOF
chmod +x ${WRAPPER_SCRIPT}

# Copy the service file
echo "Installing systemd service..."
cat > ${SERVICE_FILE} << EOF
[Unit]
Description=GitHub Runner Metrics Collector
After=docker.service node_exporter.service
Requires=docker.service

[Service]
Type=simple
User=root
Group=root
ExecStart=${WRAPPER_SCRIPT} --daemon
Restart=always
RestartSec=30

SupplementaryGroups=systemd-journal

PrivateTmp=yes
ProtectSystem=full
ReadWritePaths=${INSTALL_DIR} ${METRICS_DIR} ${LOG_DIR}
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

# Create a basic configuration for node_exporter if it doesn't exist
if [ ! -f "/etc/node_exporter/config.yml" ]; then
    mkdir -p /etc/node_exporter
    cat > "/etc/node_exporter/config.yml" << EOF
# Node Exporter configuration
collectors:
  textfile:
    directory: "${METRICS_DIR}"
EOF
    echo "Created basic node_exporter configuration"
fi

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
echo "Installation directory: ${INSTALL_DIR}"
echo "Python virtual environment: ${VENV_DIR}"
echo "Metrics will be collected in: ${METRICS_DIR}"
echo "Logs will be written to: ${LOG_DIR}/github-runner-metrics.log"
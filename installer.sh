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

# Define installation paths
INSTALL_DIR="/opt/flipper-runners"
VENV_DIR="${INSTALL_DIR}/venv"
SCRIPTS_DIR="${INSTALL_DIR}/scripts"
CONFIG_DIR="/var/lib/flipper-docker"
WRAPPER_SCRIPT="/usr/local/bin/flipper-docker-wrapper.sh"

# Install system dependencies
echo "Installing system dependencies..."
apt-get update
apt-get install -y docker-ce ccache python3-venv python3-dev logrotate

# Create required directories
echo "Setting up directories..."
mkdir -p "${INSTALL_DIR}"
mkdir -p "${SCRIPTS_DIR}"
mkdir -p "${CONFIG_DIR}"
mkdir -p "/opt/${FLIPPER_ID}/logs"

# Set up Python virtual environment
echo "Setting up Python virtual environment..."
python3 -m venv ${VENV_DIR}
${VENV_DIR}/bin/pip install --upgrade pip
${VENV_DIR}/bin/pip install pyudev docker pygelf

# Copy Docker-related files
echo "Copying Docker files..."
cp -r docker/* ${CONFIG_DIR}/

# Copy Python scripts
echo "Installing Python scripts..."
cp scripts/flipper_docker.py ${SCRIPTS_DIR}/
chmod +x ${SCRIPTS_DIR}/flipper_docker.py

# Create a wrapper script to activate the virtual environment
echo "Creating wrapper script..."
cat > ${WRAPPER_SCRIPT} << EOF
#!/bin/bash
source ${VENV_DIR}/bin/activate
exec python ${SCRIPTS_DIR}/flipper_docker.py "\$@"
EOF
chmod +x ${WRAPPER_SCRIPT}

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
ExecStart=${WRAPPER_SCRIPT} ${FLIPPER_ID} ${ST_LINK_ID} FlipperZeroTest
KillSignal=SIGINT

[Install]
WantedBy=multi-user.target
EOF

# Configure Docker logging
echo "Configuring Docker logging..."
mkdir -p /etc/docker
cat > /etc/docker/daemon.json << EOF
{
    "log-driver": "journald"
}
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
echo ""
echo "Please ensure you have placed the following files in ${CONFIG_DIR}:"
echo "1. flipper-docker.cfg with GitHub credentials"
echo "2. region_data"
echo ""
echo "Installation directory: ${INSTALL_DIR}"
echo "Python virtual environment: ${VENV_DIR}"
echo "Log files: /opt/${FLIPPER_ID}/logs/"
echo ""
echo "To start the service, run:"
echo "systemctl start github-runner-${FLIPPER_ID}"
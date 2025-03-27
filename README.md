# Dockerized GitHub Runners for Flipper Zero QA Team

This system provides a complete solution for running self-hosted GitHub runners with Flipper Zero devices for automated testing, flashing, and QA tasks. The system includes a runner management service, monitoring capabilities, and handles the device firmware flashing lifecycle.

## Overview

The system consists of several components:
- Docker-based GitHub runner containers
- Python management scripts
- Systemd services
- Monitoring solution with Prometheus integration

### Flow

1. **Initialization**: The systemd service starts a Python script that locates the specified ST-Link and Flipper devices.
2. **Repair Mode**: Docker container runs in 'REPAIR' state first, which flashes the latest release firmware to the Flipper device.
3. **Normal Mode**: After successful firmware flashing, the container restarts in 'NORMAL' state and registers as a GitHub self-hosted runner.
4. **Job Execution**: The runner picks up jobs with matching tags from GitHub and executes them.
5. **Monitoring**: A dedicated monitoring service tracks the status of all runners and provides metrics.

## Project Structure

```
├── docker/
│   ├── Dockerfile            # Docker image definition
│   ├── entrypoint.sh         # Container entry point script
│   ├── serial_monitor.py     # Serial output monitoring script
│   └── region_data/          # Region-specific data for Flipper firmware
├── scripts/
│   ├── flipper_docker.py     # Main runner management script
│   └── flipper_monitor.py    # Metrics collection script
├── installer.sh              # Runner installation script
├── monitor-installer.sh      # Monitoring service installation script
```

## Prerequisites

Before installation, ensure:
1. Docker is installed and properly configured
2. Python 3.6+ is available
3. The Flipper Zero device and ST-Link device are connected via USB
4. You have the serial IDs for both devices (can be obtained via `lsusb -v` or `ls -l /dev/serial/by-id/`)
5. You have appropriate GitHub permissions to register self-hosted runners

## Installation

### Runner Installation

```bash
sudo ./installer.sh --flipper-id=FLIPPER_ID --stlink=ST_LINK_ID [--simulate]
```

Example:
```bash
sudo ./installer.sh --flipper-id=flip_Testii --stlink=002F00000000000000000001
```

This will:
1. Install required dependencies
2. Set up the necessary directories
3. Configure the systemd service
4. Set up logging

The `--simulate` flag can be used to preview the changes without actually making them.

### Node Exporter metrics installation

```bash
sudo ./monitor-installer.sh
```

This will:
1. Install the monitoring service
2. Configure Prometheus metrics collection
3. Set up log rotation
4. Enable the monitoring systemd service

## Configuration

### Runner Configuration

Create a configuration file at `/var/lib/flipper-docker/flipper-docker.cfg`:

```ini
[github]
access_token = GITHUB_ACCESS_TOKEN
org_name = GITHUB_ORG_NAME
app_id = GITHUB_APP_ID
app_private_key = GITHUB_APP_PRIVATE_KEY

[gelf]
host = GELF_HTTP_UPLOAD_URL
port = GELF_HTTP_UPLOAD_PORT
username = GELF_HTTP_UPLOAD_BASIC_AUTH_USER
password = GELF_HTTP_UPLOAD_BASIC_AUTH_PASS
```

Where:
- `GITHUB_ACCESS_TOKEN` - GitHub Personal Access Token
- `GITHUB_ORG_NAME` - GitHub organization name
- `GITHUB_APP_ID` - GitHub App ID (if using GitHub App authentication)
- `GITHUB_APP_PRIVATE_KEY` - GitHub App private key (if using GitHub App authentication)
- `GELF_HTTP_UPLOAD_*` - Optional GELF logging configuration

### Docker Configuration

The system uses a custom Docker image based on `myoung34/github-runner:2.322.0-ubuntu-jammy` with additional tools for Flipper Zero development. The Dockerfile includes:

- Python 3 and required libraries
- Build tools (gcc, make, etc.)
- libusb for USB device access
- ccache for faster builds
- Preloaded Flipper Zero firmware

You can specify a custom firmware version during installation:

```
# Example in Dockerfile
ARG FirmwareVersion=1.1.2
ARG UpdateServerURL=https://update.flipperzero.one/builds
```

### Systemd Services

For each Flipper + ST-Link pair, a dedicated systemd service is created automatically by the installer:

```ini
[Unit]
Description=Dockerized github runner FLIPPER_ID
After=docker.service
Requires=docker.service

[Service]
TimeoutStartSec=0
Restart=always
ExecStart=/usr/local/bin/flipper-docker-wrapper.sh FLIPPER_ID ST_LINK_ID FlipperZeroTest
KillSignal=SIGINT

[Install]
WantedBy=multi-user.target
```

The monitoring service is configured as:

```ini
[Unit]
Description=GitHub Runner Metrics Collector
After=docker.service node_exporter.service
Requires=docker.service

[Service]
Type=simple
User=root
Group=root
ExecStart=/usr/local/bin/flipper-monitor-wrapper.sh --daemon
Restart=always
RestartSec=30

SupplementaryGroups=systemd-journal

PrivateTmp=yes
ProtectSystem=full
ReadWritePaths=/opt/flipper-monitor /var/lib/node_exporter/textfile_collector /var/log
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
```

## Device Management

### Serial Output Monitoring

The `serial_monitor.py` script captures and logs all serial output from the Flipper Zero device during operation. Features include:

- Real-time logging to files
- Timestamp addition to each log line
- Automatic reconnection on device disconnect
- Unicode handling for proper character display

## Monitoring

The monitoring system collects metrics about runner state, container status, and job execution. 

### Metrics

The following metrics are available in Prometheus format:
- `github_runner_state` - Current state of GitHub runners (offline, starting, repairing, online, error, flashing)
- `github_runner_container_status` - Docker container status
- `github_runner_run_level` - Current run level (REPAIR or NORMAL)
- `github_runner_service_status` - Systemd service status
- `github_runner_uptime_seconds` - Runner uptime
- `github_runner_job_info` - Information about currently running jobs
- `github_runner_job_runtime_seconds` - Duration of current job

### Metrics Collection

The `flipper_monitor.py` script collects data from multiple sources:
- **systemd Journal**: For runner state information
- **Docker API**: For container status and job information
- **systemd Units**: For service status

Data is processed and formatted as Prometheus metrics, then written to the Node Exporter textfile directory.

### Integrations

The monitoring service outputs metrics to `/var/lib/node_exporter/textfile_collector/`, ready to be picked up by Prometheus Node Exporter.
Make sure to configure Node Exporter to scrape the metrics directory, that can be done by adding
`-v /var/lib/node_exporter/textfile_collector:/textfile_collector:ro \
--collector.textfile.directory=/textfile_collector` to your docker create script.

## Logs

- Runner logs: `/opt/<FLIPPER_ID>/logs/`
- Container logs: Accessible via `docker logs` or systemd journal
- Serial monitor logs: `/opt/<FLIPPER_ID>/logs/<FLIPPER_ID>_<TIMESTAMP>_<RUN_LEVEL>.log`
- Monitoring logs: `/var/log/github-runner-metrics.log`

Log rotation is configured automatically to prevent excessive disk usage.

## Runner States

Runners go through the following states:
1. **Offline**: Not running
2. **Starting**: Service is initializing
3. **Repairing**: In repair mode, preparing to flash firmware
4. **Flashing**: Actively flashing firmware to Flipper
5. **Online**: Registered with GitHub and ready for jobs
6. **Error**: Encountered an error during operation

## Implementation Details

### Run Levels

The system operates in two primary run levels:
- **REPAIR**: Focuses on flashing firmware to Flipper Zero
- **NORMAL**: Operates as a GitHub runner

When a new device is added or after a job completes, the system starts in REPAIR mode, flashes the device, then switches to NORMAL mode.

### Container Lifecycle

1. The Docker container is created with device mappings for both Flipper and ST-Link
2. The container's entrypoint script handles:
   - Serial port monitoring
   - Firmware flashing using FBT (Flipper Build Tool)
   - GitHub runner registration and startup
3. When a job completes, the container exits with code 0, triggering a restart in REPAIR mode

## Troubleshooting

### Common Issues

1. **Device not found**
   - Check USB connections
   - Verify ST-Link and Flipper IDs

2. **Container fails to start**
   - Check Docker service status: `systemctl status docker`
   - Verify configuration file existence and permissions
   - Check for USB device conflicts: `lsusb -t`

3. **Runner doesn't register with GitHub**
   - Check GitHub access token permissions
   - Verify network connectivity
   - Check the container logs for registration errors

4. **Firmware flashing fails**
   - Verify ST-Link connection and permissions
   - Check if firmware file exists in the container
   - Review serial monitor logs for specific errors

### Diagnostic Commands

```bash
# Check runner service status
systemctl status github-runner-<FLIPPER_ID>

# View runner logs
journalctl -u github-runner-<FLIPPER_ID> -f

# Check monitor service status
systemctl status github-runner-monitor

# View monitor logs
tail -f /var/log/github-runner-metrics.log

# Check Docker container status
docker ps -a | grep <FLIPPER_ID>

# View serial monitor logs
ls -la /opt/toolchain/logs/
cat /opt/toolchain/logs/<FLIPPER_ID>_<TIMESTAMP>_<RUN_LEVEL>.log

# Check udev rules 
cat /etc/udev/rules.d/99-flipper-devices.rules

# Verify device symlinks
ls -la /dev/ttyACM*
ls -la /dev/serial/by-id/
```

### Restarting Services

If you need to restart the entire system:

```bash
# Restart a specific runner
systemctl restart github-runner-<FLIPPER_ID>

# Restart the monitoring service
systemctl restart github-runner-monitor

# Restart all runner services
systemctl restart 'github-runner-*'
```

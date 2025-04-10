# Flipper Zero GitHub Runner System

This system provides a complete solution for running self-hosted GitHub runners with Flipper Zero devices for automated testing, flashing, and QA tasks. The system includes a runner management service, monitoring capabilities, and handles the device firmware flashing lifecycle.

## Overview

The system consists of several components:
- Docker-based GitHub runner containers
- Python management scripts
- Systemd services for automatic device detection and binding
- Monitoring solution with Prometheus integration

### Flow

1. **Device Detection**: udev rules detect when Flipper devices are connected and trigger binding services
2. **Binding**: The binding service creates mounts in `/dev/flipper/`
2. **Initialization**: The systemd service starts a Python script that locates the specified ST-Link and Flipper devices
3. **Repair Mode**: Docker container runs in 'REPAIR' state first, which flashes the latest release firmware to the Flipper device
4. **Normal Mode**: After successful firmware flashing, the container restarts in 'NORMAL' state and registers as a GitHub self-hosted runner
5. **Job Execution**: The runner picks up jobs with matching tags from GitHub and executes them
6. **Monitoring**: A dedicated monitoring service tracks the status of all runners and provides metrics

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
sudo ./installer.sh --flipper=FLIPPER_SERIAL --stlink=STLINK_SERIAL [--github-tag=GITHUB_TAG] [--simulate]
```

Example:
```bash
sudo ./installer.sh --flipper=flip_Testii --stlink=002F00000000000000000001 --github-tag=FlipperDeviceTest
```

This will:
1. Create necessary directories in `/opt/flipper-runner/`
2. Copy scripts and service files to their respective locations
3. Install udev rules for automatic device detection
4. Configure systemd services for the specified Flipper and ST-Link devices
5. Install service binaries to `/usr/local/bin/`

The `--simulate` flag can be used to preview the changes without actually making them.

After that you need just to put firmware repo and build Docker image
```bash
cd /var/lib/flipper-docker/
git clone --branch 1.2.0 git@github.com:flipperdevices/flipperzero-firmware.git
docker build -t flipper-custom-image:FlipperZeroTest .
```

### Monitor Installation

```bash
sudo ./monitor-installer.sh
```

This will:
1. Install the monitoring service at `/opt/flipper-monitor/`
2. Configure Prometheus metrics collection in `/var/lib/node_exporter/textfile_collector/`
3. Set up log rotation for `/var/log/github-runner-metrics.log`
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

You'll need to prepare a Docker image with the necessary tools for Flipper Zero development. The Dockerfile should include:

1. Base on GitHub runner image (e.g., `myoung34/github-runner:latest`)
2. Python 3 and required libraries
3. Build tools (gcc, make, etc.)
4. libusb for USB device access
5. Flipper Zero build toolchain

Place your Dockerfile and any required assets in a directory that will be copied to `/var/lib/flipper-docker/`.

## Device Management

### Automatic Device Detection

The system uses udev rules to automatically detect when Flipper devices are connected or disconnected:

1. When a Flipper device is connected, the udev rule triggers the binder service
2. The binder service creates the necessary device mappings in `/dev/flipper/`
3. When a Flipper device is disconnected, the unbinder service removes these mappings

This allows for hot-plugging Flipper devices without manual intervention.

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

The `github-runner-monitor.py` script collects data from multiple sources:
- **systemd Journal**: For runner state information
- **Docker API**: For container status and job information
- **systemd Units**: For service status

Data is processed and formatted as Prometheus metrics, then written to the Node Exporter textfile directory.

### Integrations

The monitoring service outputs metrics to `/var/lib/node_exporter/textfile_collector/`, ready to be picked up by Prometheus Node Exporter.
Make sure to configure Node Exporter to scrape the metrics directory by adding
`-v /var/lib/node_exporter/textfile_collector:/textfile_collector:ro \
--collector.textfile.directory=/textfile_collector` to your docker create script.

## Logs

- Runner logs: `/opt/flipper-runner/FLIPPER_SERIAL/logs/`
- Container logs: Accessible via `docker logs` or systemd journal
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
   - Firmware flashing (in REPAIR mode)
   - GitHub runner registration and startup (in NORMAL mode)
3. When a job completes, the container exits with code 0, triggering a restart in REPAIR mode

## Troubleshooting

### Common Issues

1. **Device not found**
   - Check USB connections
   - Verify ST-Link and Flipper IDs
   - Check `/run/` directory for environment files

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
   - Check if the Docker container has access to the device
   - Review container logs for specific errors

### Diagnostic Commands

```bash
# Check runner service status
systemctl status github-runner-flip-<FLIPPER_SERIAL>

# View runner logs
journalctl -u github-runner-flip-<FLIPPER_SERIAL> -f

# Check monitor service status
systemctl status github-runner-monitor

# View monitor logs
tail -f /var/log/github-runner-metrics.log

# Check Docker container status
docker ps -a | grep <FLIPPER_SERIAL>

# Check udev rules 
cat /etc/udev/rules.d/99-udev-flipper-zero.rules

# Verify device symlinks
ls -la /dev/flipper/
```

### Restarting Services

If you need to restart:

```bash
# Restart a specific runner
systemctl restart github-runner-flip-<FLIPPER_SERIAL>

# Restart the monitoring service
systemctl restart github-runner-monitor

# Restart all runner services
systemctl restart 'github-runner-flip-*'
```

## License

This project is licensed under the MIT License - see the LICENSE file for details.
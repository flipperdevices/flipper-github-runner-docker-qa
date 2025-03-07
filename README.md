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

## Installation

### Runner Installation

```bash
sudo ./installer.sh FLIPPER_ID ST_LINK_ID
```

Example:
```bash
sudo ./installer.sh flip_Testii 002F00000000000000000001
```

This will:
1. Install required dependencies
2. Set up the necessary directories
3. Configure the systemd service
4. Set up logging

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

### Systemd Service

For each Flipper + ST-Link pair, a dedicated systemd service is created:

```ini
[Unit]
Description=Dockerized github runner FLIPPER_SHORT_NAME
After=docker.service
Requires=docker.service

[Service]
TimeoutStartSec=0
Restart=always
ExecStart=sudo python3 /usr/bin/flipper_docker.py FLIPPER_SHORT_NAME ST_LINK_DEVICE_ID GITHUB_RUNNER_TAG
KillSignal=SIGINT

[Install]
WantedBy=multi-user.target
```

Example:
```ini
ExecStart=sudo python3 /usr/bin/flipper_docker.py flip_Testii 002F00000000000000000001 FlipperZeroTest
```

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

### Integrations

The monitoring service outputs metrics to `/var/lib/node_exporter/textfile_collector/`, ready to be picked up by Prometheus Node Exporter.
Make sure to configure Node Exporter to scrape the metrics directory.

## Logs

- Runner logs: `/opt/<FLIPPER_ID>/logs/`
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

## Troubleshooting

### Common Issues

1. **Device not found**
   - Check USB connections
   - Verify ST-Link and Flipper IDs

2. **Container fails to start**
   - Check Docker service status
   - Verify configuration file

3. **Runner doesn't register with GitHub**
   - Check GitHub access token permissions
   - Verify network connectivity

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
```

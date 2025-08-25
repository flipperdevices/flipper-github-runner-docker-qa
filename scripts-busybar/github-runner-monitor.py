import os
import time
import subprocess
import logging
import re
import fcntl
import argparse
import telnetlib
from datetime import datetime
import docker

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('/var/log/github-runner-busybar-metrics.log')
    ]
)
logger = logging.getLogger('github-runner-busybar-metrics')


class BusyBarMetricsCollector:
    def __init__(self, output_dir, interval=60):
        self.output_dir = output_dir
        self.interval = interval
        self.last_run = None
        self.metric_file = os.path.join(output_dir, 'github_busybar_runners.prom')
        self.lock_file = '/tmp/github_busybar_runner_metrics.lock'
        self.previous_docker_containers = {}
        self.busybar_devices = {}

        os.makedirs(output_dir, exist_ok=True)

        try:
            self.docker_client = docker.from_env()
        except Exception as e:
            logger.error(f"Failed to initialize Docker client: {e}")
            self.docker_client = None

    def get_lock(self):
        """Get an exclusive lock to prevent multiple instances from running"""
        self.lock_fd = open(self.lock_file, 'w')
        try:
            fcntl.lockf(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except IOError:
            logger.warning("Another instance is already running. Exiting.")
            return False

    def release_lock(self):
        """Release the lock"""
        if hasattr(self, 'lock_fd'):
            fcntl.lockf(self.lock_fd, fcntl.LOCK_UN)
            self.lock_fd.close()

    def check_busybar_connectivity(self, ip="10.0.4.20", port=23):
        """Check if BusyBar is accessible via telnet"""
        try:
            tn = telnetlib.Telnet(ip, port, timeout=2)
            tn.close()
            return 1  # Connected
        except Exception:
            return 0  # Not connected

    def get_busybar_version(self, ip="10.0.4.20", port=23):
        """Get BusyBar firmware version via telnet"""
        try:
            tn = telnetlib.Telnet(ip, port, timeout=5)
            time.sleep(0.5)
            tn.write(b"version\n")
            response = tn.read_until(b"\n", timeout=2).decode('utf-8', errors='ignore')
            tn.close()

            # Extract version from response
            version_match = re.search(r'Version:\s*([^\s]+)', response)
            if version_match:
                return version_match.group(1)
            return "unknown"
        except Exception as e:
            logger.debug(f"Failed to get BusyBar version: {e}")
            return "unknown"

    def check_busybar_interfaces(self):
        """Check for BusyBar network interfaces"""
        interfaces = {}
        try:
            result = subprocess.run(
                "ip link show | grep -B1 '37:c1'",
                shell=True,
                capture_output=True,
                text=True
            )

            if result.returncode == 0 and result.stdout:
                for line in result.stdout.split('\n'):
                    match = re.match(r'^\d+:\s+(\w+):', line)
                    if match:
                        interface_name = match.group(1)
                        status_result = subprocess.run(
                            f"ip link show {interface_name} | grep -o 'state [A-Z]*'",
                            shell=True,
                            capture_output=True,
                            text=True
                        )
                        if status_result.stdout:
                            state = status_result.stdout.strip().split()[1]
                            interfaces[interface_name] = state
        except Exception as e:
            logger.error(f"Error checking BusyBar interfaces: {e}")

        return interfaces

    def query_blackmagic_devices(self):
        """Query for Blackmagic UART devices"""
        blackmagic_devices = {}
        try:
            result = subprocess.run(
                "ls -l /dev/serial/by-id/ | grep blackmagic",
                shell=True,
                capture_output=True,
                text=True
            )

            if result.returncode == 0:
                for line in result.stdout.strip().split('\n'):
                    if 'blackmagic' in line:
                        parts = line.split()
                        if len(parts) >= 2:
                            device_id = parts[-2].split('_')[-1]
                            device_path = f"/dev/{parts[-1].split('/')[-1]}"
                            blackmagic_devices[device_id] = {
                                'path': device_path,
                                'connected': os.path.exists(device_path)
                            }
        except Exception as e:
            logger.error(f"Error querying Blackmagic devices: {e}")

        return blackmagic_devices

    def query_busybar_containers(self):
        """Query Docker for BusyBar runner containers"""
        if not self.docker_client:
            return {}

        try:
            containers = self.docker_client.containers.list(all=True)
            busybar_containers = {}

            for container in containers:
                container_name = container.name

                if not (container_name.startswith('busybar_') or 'busybar' in container_name.lower()):
                    continue

                runner_id = container_name
                container_info = {
                    'id': container.id,
                    'name': container.name,
                    'status': container.status,
                    'started_at': container.attrs.get('State', {}).get('StartedAt', ''),
                    'image': container.image.tags[0] if container.image.tags else 'unknown'
                }

                try:
                    env_vars = container.attrs.get('Config', {}).get('Env', [])
                    github_tag = 'unknown'
                    run_level = 'unknown'
                    hostname = 'unknown'
                    busybar_ip = '10.0.4.20'

                    for env_var in env_vars:
                        if env_var.startswith('LABELS='):
                            github_tag = env_var.split('=', 1)[1]
                        elif env_var.startswith('RUN_LEVEL='):
                            run_level = env_var.split('=', 1)[1]
                        elif env_var.startswith('RUNNER_NAME='):
                            hostname_parts = env_var.split('=', 1)[1].split('-')
                            if len(hostname_parts) > 1:
                                hostname = hostname_parts[0]
                        elif env_var.startswith('BUSYBAR_IP='):
                            busybar_ip = env_var.split('=', 1)[1]

                    container_info['github_tag'] = github_tag
                    container_info['run_level'] = run_level
                    container_info['host'] = hostname
                    container_info['busybar_ip'] = busybar_ip

                except Exception as e:
                    logger.warning(f"Failed to extract metadata from container {runner_id}: {e}")
                    container_info['github_tag'] = 'unknown'
                    container_info['host'] = 'unknown'
                    container_info['run_level'] = 'unknown'
                    container_info['busybar_ip'] = '10.0.4.20'

                # Check BusyBar connectivity for running containers
                if container.status == 'running':
                    container_info['busybar_connected'] = self.check_busybar_connectivity(
                        container_info['busybar_ip']
                    )
                    container_info['busybar_version'] = self.get_busybar_version(
                        container_info['busybar_ip']
                    )
                else:
                    container_info['busybar_connected'] = 0
                    container_info['busybar_version'] = 'unknown'

                busybar_containers[runner_id] = container_info

            return busybar_containers

        except Exception as e:
            logger.exception(f"Error querying BusyBar Docker containers: {e}")
            return {}

    def process_metrics(self, busybar_containers, blackmagic_devices, interfaces):
        """Process all data sources into Prometheus metrics"""

        metrics = []

        # Define metric headers
        metrics.append("# HELP github_busybar_runner_state Current state of BusyBar GitHub runners")
        metrics.append("# TYPE github_busybar_runner_state gauge")
        metrics.append("# HELP github_busybar_container_status Docker container status for BusyBar runners")
        metrics.append("# TYPE github_busybar_container_status gauge")
        metrics.append(
            "# HELP github_busybar_connectivity BusyBar telnet connectivity status (0=disconnected, 1=connected)")
        metrics.append("# TYPE github_busybar_connectivity gauge")
        metrics.append("# HELP github_busybar_network_interface BusyBar network interface status")
        metrics.append("# TYPE github_busybar_network_interface gauge")
        metrics.append("# HELP github_blackmagic_device Blackmagic UART device status")
        metrics.append("# TYPE github_blackmagic_device gauge")
        metrics.append("# HELP github_busybar_firmware_info BusyBar firmware version info (always 1)")
        metrics.append("# TYPE github_busybar_firmware_info gauge")

        # Define state mappings
        docker_status_values = {
            'not_found': 0, 'created': 1, 'running': 2, 'paused': 3,
            'restarting': 4, 'removing': 5, 'exited': 6, 'dead': 7
        }

        interface_status_values = {
            'DOWN': 0, 'UP': 1, 'UNKNOWN': 2
        }

        # Process BusyBar containers
        for runner_id, container_info in busybar_containers.items():
            host = container_info.get('host', 'unknown')
            tag = container_info.get('github_tag', 'unknown')
            run_level = container_info.get('run_level', 'unknown')

            # Container status
            container_status = container_info.get('status', 'not_found')
            status_value = docker_status_values.get(container_status, 0)
            metrics.append(
                f'github_busybar_container_status{{runner_id="{runner_id}",host="{host}",tag="{tag}",run_level="{run_level}"}} {status_value}'
            )

            # BusyBar connectivity
            connected = container_info.get('busybar_connected', 0)
            busybar_ip = container_info.get('busybar_ip', '10.0.4.20')
            metrics.append(
                f'github_busybar_connectivity{{runner_id="{runner_id}",host="{host}",tag="{tag}",ip="{busybar_ip}"}} {connected}'
            )

            # Firmware version info
            version = container_info.get('busybar_version', 'unknown')
            if version != 'unknown':
                metrics.append(
                    f'github_busybar_firmware_info{{runner_id="{runner_id}",host="{host}",tag="{tag}",version="{version}"}} 1'
                )

        # Process network interfaces
        for interface_name, status in interfaces.items():
            status_value = interface_status_values.get(status, 2)
            metrics.append(
                f'github_busybar_network_interface{{interface="{interface_name}",status="{status}"}} {status_value}'
            )

        # Process Blackmagic devices
        for device_id, device_info in blackmagic_devices.items():
            connected = 1 if device_info['connected'] else 0
            device_path = device_info['path']
            metrics.append(
                f'github_blackmagic_device{{device_id="{device_id}",path="{device_path}"}} {connected}'
            )

        return metrics

    def write_metrics(self, metrics):
        """Write metrics to the output file"""
        try:
            # Write to temporary file first
            temp_file = f"{self.metric_file}.tmp"
            with open(temp_file, 'w') as f:
                f.write('\n'.join(metrics) + '\n')

            # Atomic move to final location
            os.rename(temp_file, self.metric_file)
        except Exception as e:
            logger.exception(f"Error writing metrics: {e}")

    def run_once(self):
        """Run collection once"""
        last_run_before = self.last_run
        self.last_run = datetime.now()

        # Collect data from all sources
        busybar_containers = self.query_busybar_containers()
        blackmagic_devices = self.query_blackmagic_devices()
        interfaces = self.check_busybar_interfaces()

        if not busybar_containers and not blackmagic_devices and not interfaces:
            logger.warning("No BusyBar data found from any source")
            self.last_run = last_run_before
            return

        # Process and write metrics
        metrics = self.process_metrics(busybar_containers, blackmagic_devices, interfaces)
        self.write_metrics(metrics)

        # Update previous state
        self.previous_docker_containers.update(busybar_containers)

    def run_daemon(self):
        """Run as daemon, collecting metrics at regular intervals"""
        logger.info(f"Starting BusyBar metrics collector, interval: {self.interval}s")

        while True:
            try:
                self.run_once()
            except Exception as e:
                logger.exception(f"Error in collector loop: {e}")

            time.sleep(self.interval)


def main():
    parser = argparse.ArgumentParser(description='BusyBar GitHub Runner Metrics Collector')
    parser.add_argument('--output-dir', '-o', default='/var/lib/node_exporter/textfile_collector',
                        help='Output directory for Prometheus metrics')
    parser.add_argument('--interval', '-i', type=int, default=60,
                        help='Collection interval in seconds when running as daemon')
    parser.add_argument('--daemon', '-d', action='store_true',
                        help='Run as daemon')
    parser.add_argument('--once', action='store_true',
                        help='Run once and exit')
    parser.add_argument('--debug', action='store_true',
                        help='Enable debug logging')

    args = parser.parse_args()

    if args.debug:
        logger.setLevel(logging.DEBUG)

    collector = BusyBarMetricsCollector(args.output_dir, args.interval)

    if not collector.get_lock():
        exit(1)

    try:
        if args.once:
            collector.run_once()
        else:
            collector.run_daemon()
    finally:
        collector.release_lock()


if __name__ == "__main__":
    main()
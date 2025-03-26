#!/usr/bin/env python3

import os
import json
import time
import subprocess
import logging
import re
import fcntl
import argparse
from datetime import datetime
import docker

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('/var/log/github-runner-metrics.log')
    ]
)
logger = logging.getLogger('github-runner-metrics')


class GithubRunnerMetricsCollector:
    def __init__(self, output_dir, interval=60):
        self.output_dir = output_dir
        self.interval = interval
        self.last_run = None
        self.metric_file = os.path.join(output_dir, 'github_runners.prom')
        self.lock_file = '/tmp/github_runner_metrics.lock'

        # Create output directory if it doesn't exist
        os.makedirs(output_dir, exist_ok=True)

        # Initialize Docker client
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

    def query_journal(self):
        """Query systemd journal for runner state information"""
        try:
            # Set time filter
            if not self.last_run:
                since_arg = "--since='1 hour ago'"
            else:
                formatted_time = self.last_run.strftime("%Y-%m-%d %H:%M:%S")
                since_arg = f"--since='{formatted_time}'"

            # Query for logs from github-runner services
            cmd = f"journalctl -u 'github-runner-*' {since_arg} -o json"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)

            if result.returncode != 0:
                logger.error(f"Error querying journal: {result.stderr}")
                return []

            # Parse journal entries
            logs = []
            for line in result.stdout.strip().split('\n'):
                if not line:
                    continue

                try:
                    entry = json.loads(line)
                    message = entry.get('MESSAGE', '')

                    # Extract JSON data from message
                    json_match = re.search(r'({.*})$', message)
                    if json_match:
                        try:
                            data = json.loads(json_match.group(1))
                            if data.get('MONITORING_TYPE') == 'github_runner_state':
                                data['HOST'] = entry.get('_HOSTNAME', 'unknown')
                                data['UNIT'] = entry.get('_SYSTEMD_UNIT', 'unknown')
                                logs.append(data)
                        except json.JSONDecodeError:
                            pass
                except (json.JSONDecodeError, AttributeError):
                    pass

            return logs

        except Exception as e:
            logger.exception(f"Error querying journal: {e}")
            return []

    def query_docker_containers(self):
        """Query Docker for GitHub runner containers"""
        if not self.docker_client:
            return {}

        try:
            containers = self.docker_client.containers.list(all=True)
            runner_containers = {}

            for container in containers:
                container_name = container.name

                # Skip if not a runner container
                if not (container_name.startswith('flip_') or 'github' in container_name.lower()):
                    continue

                flipper_id = container_name

                # Basic container info
                container_info = {
                    'id': container.id,
                    'name': container.name,
                    'status': container.status,
                    'started_at': container.attrs.get('State', {}).get('StartedAt', ''),
                    'image': container.image.tags[0] if container.image.tags else 'unknown'
                }

                # Extract environment variables
                try:
                    env_vars = container.attrs.get('Config', {}).get('Env', [])
                    github_tag = 'unknown'
                    run_level = 'unknown'
                    hostname = 'unknown'

                    for env_var in env_vars:
                        if env_var.startswith('LABELS='):
                            github_tag = env_var.split('=', 1)[1]
                        elif env_var.startswith('RUN_LEVEL='):
                            run_level = env_var.split('=', 1)[1]
                        elif env_var.startswith('RUNNER_NAME='):
                            hostname_parts = env_var.split('=', 1)[1].split('-')
                            if len(hostname_parts) > 1:
                                hostname = hostname_parts[0]

                    container_info['github_tag'] = github_tag
                    container_info['run_level'] = run_level
                    container_info['host'] = hostname

                except Exception as e:
                    logger.warning(f"Failed to extract metadata from container {flipper_id}: {e}")
                    container_info['github_tag'] = 'unknown'
                    container_info['host'] = 'unknown'
                    container_info['run_level'] = 'unknown'

                # Try to get job information from logs if container is running
                if container.status == 'running':
                    try:
                        logs = container.logs(tail=100).decode('utf-8', errors='replace')

                        # Extract job name from logs
                        job_name = 'Unknown Job'
                        job_id = container.short_id
                        workflow_name = 'Unknown Workflow'

                        # Simple patterns to check for job information
                        job_match = re.search(r'Running job: ([^\n]+)', logs)
                        if job_match:
                            job_name = job_match.group(1).strip()

                        workflow_match = re.search(r'Running workflow: ([^\n]+)', logs)
                        if workflow_match:
                            workflow_name = workflow_match.group(1).strip()

                        # Get job start time
                        job_start_time = None
                        timestamp_match = re.search(r'(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}).*Running job:', logs)
                        if timestamp_match:
                            try:
                                time_str = timestamp_match.group(1)
                                if 'T' in time_str:
                                    job_start_time = datetime.fromisoformat(time_str)
                                else:
                                    job_start_time = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
                            except ValueError:
                                pass

                        container_info['job_name'] = job_name
                        container_info['job_id'] = job_id
                        container_info['workflow_name'] = workflow_name
                        container_info['job_start_time'] = job_start_time

                        # If run level not found in environment, try logs
                        if container_info['run_level'] == 'unknown':
                            if re.search(r'App running into repair mode|REPAIR mode|flashing the flipper|Flashing done',
                                         logs, re.IGNORECASE):
                                container_info['run_level'] = 'REPAIR'
                            elif re.search(r'Starting runner|NORMAL mode|actions-runner|Starting job', logs,
                                           re.IGNORECASE):
                                container_info['run_level'] = 'NORMAL'

                    except Exception as e:
                        logger.warning(f"Failed to extract job info from container {flipper_id}: {e}")

                runner_containers[flipper_id] = container_info

            return runner_containers

        except Exception as e:
            logger.exception(f"Error querying Docker containers: {e}")
            return {}

    def query_systemd_units(self):
        """Query systemd for unit status information"""
        try:
            # List all GitHub runner units
            cmd = "systemctl list-units 'github-runner-*' --all --output=json"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)

            if result.returncode != 0:
                logger.error(f"Error querying systemd units: {result.stderr}")
                return {}

            units = {}
            try:
                unit_list = json.loads(result.stdout)
                for unit in unit_list:
                    unit_name = unit.get('unit', '')
                    if unit_name.startswith('github-runner-'):
                        flipper_id = unit_name.replace('github-runner-', '')
                        units[flipper_id] = {
                            'unit': unit_name,
                            'load': unit.get('load', ''),
                            'active': unit.get('active', ''),
                            'sub': unit.get('sub', ''),
                            'description': unit.get('description', '')
                        }
            except json.JSONDecodeError:
                logger.error("Failed to parse systemd unit list JSON")

            return units

        except Exception as e:
            logger.exception(f"Error querying systemd units: {e}")
            return {}

    def process_metrics(self, journal_logs, docker_containers, systemd_units):
        """Process all data sources into Prometheus metrics"""
        # First, group journal logs by runner ID to get the latest state for each runner
        runners_journal = {}

        for log in journal_logs:
            runner_id = log.get('RUNNER_ID')
            if not runner_id:
                continue

            # Check if we already have this runner and if this log is newer
            if runner_id not in runners_journal or log.get('STATE_TIMESTAMP', '') > runners_journal[runner_id].get(
                    'STATE_TIMESTAMP', ''):
                runners_journal[runner_id] = log

        # Get all runner IDs from all sources
        all_runner_ids = set(list(runners_journal.keys()) +
                             list(docker_containers.keys()) +
                             list(systemd_units.keys()))

        # Generate Prometheus metrics
        metrics = []

        # Define metric headers
        metrics.append(
            "# HELP github_runner_state Current state of Github runners based on journal logs (0=offline, 1=starting, 2=repairing, 3=online, 4=error, 5=flashing)")
        metrics.append("# TYPE github_runner_state gauge")

        metrics.append(
            "# HELP github_runner_container_status Current status of Github runner Docker containers (0=not_found, 1=created, 2=running, 3=paused, 4=restarting, 5=removing, 6=exited, 7=dead)")
        metrics.append("# TYPE github_runner_container_status gauge")

        metrics.append(
            "# HELP github_runner_run_level Current run level of GitHub runner (0=unknown, 1=repair, 2=normal)")
        metrics.append("# TYPE github_runner_run_level gauge")

        metrics.append(
            "# HELP github_runner_service_status Current status of Github runner systemd services (0=inactive, 1=active, 2=activating, 3=deactivating, 4=failed)")
        metrics.append("# TYPE github_runner_service_status gauge")

        metrics.append("# HELP github_runner_uptime_seconds Time in seconds the runner has been in its current state")
        metrics.append("# TYPE github_runner_uptime_seconds gauge")

        metrics.append("# HELP github_runner_job_info Information about the currently running job (always 1)")
        metrics.append("# TYPE github_runner_job_info gauge")

        metrics.append("# HELP github_runner_job_runtime_seconds Time in seconds the current job has been running")
        metrics.append("# TYPE github_runner_job_runtime_seconds gauge")

        # Define state mappings
        journal_state_values = {
            'offline': 0, 'starting': 1, 'repairing': 2,
            'online': 3, 'error': 4, 'flashing': 5
        }

        docker_status_values = {
            'not_found': 0, 'created': 1, 'running': 2, 'paused': 3,
            'restarting': 4, 'removing': 5, 'exited': 6, 'dead': 7
        }

        run_level_values = {'unknown': 0, 'REPAIR': 1, 'NORMAL': 2}

        systemd_status_values = {
            'inactive': 0, 'active': 1, 'activating': 2,
            'deactivating': 3, 'failed': 4
        }

        now = datetime.now()

        # Process each runner's data
        for runner_id in all_runner_ids:
            journal_data = runners_journal.get(runner_id, {})
            docker_data = docker_containers.get(runner_id, {})
            systemd_data = systemd_units.get(runner_id, {})

            # Get basic information from any available source
            host = journal_data.get('HOST', docker_data.get('host', 'unknown'))
            tag = journal_data.get('RUNNER_TAG', docker_data.get('github_tag', 'unknown'))
            unit = journal_data.get('UNIT', systemd_data.get('unit', '')).replace('github-runner-', '')

            # Process run level information
            run_level = docker_data.get('run_level', 'unknown')
            run_level_value = run_level_values.get(run_level, 0)

            # Add run level metric
            metrics.append(
                f'github_runner_run_level{{runner_id="{runner_id}",host="{host}",tag="{tag}",run_level="{run_level}"}} {run_level_value}')

            # Process journal-based state
            if journal_data:
                state = journal_data.get('RUNNER_STATE', 'unknown')
                state_value = journal_state_values.get(state, -1)

                metrics.append(
                    f'github_runner_state{{runner_id="{runner_id}",host="{host}",tag="{tag}",unit="{unit}",state="{state}"}} {state_value}')

                # Calculate uptime based on journal state
                try:
                    ts_string = journal_data.get('STATE_TIMESTAMP', '')
                    if ts_string:
                        if 'T' in ts_string:
                            timestamp = datetime.fromisoformat(ts_string.replace('Z', '+00:00'))
                        else:
                            timestamp = datetime.strptime(ts_string, "%Y-%m-%d %H:%M:%S.%f")

                        journal_uptime = (now - timestamp).total_seconds()
                        metrics.append(
                            f'github_runner_uptime_seconds{{runner_id="{runner_id}",host="{host}",tag="{tag}",source="journal",state="{state}"}} {journal_uptime}')
                except (ValueError, TypeError) as e:
                    logger.warning(f"Error processing timestamp for {runner_id}: {e}")

            # Process Docker container status
            if docker_data:
                container_status = docker_data.get('status', 'not_found')
                status_value = docker_status_values.get(container_status, 0)
                container_id = docker_data.get("id", "unknown")

                metrics.append(
                    f'github_runner_container_status{{runner_id="{runner_id}",host="{host}",tag="{tag}",container_id="{container_id}",run_level="{run_level}"}} {status_value}')

                # Calculate container uptime if running
                if container_status == 'running' and 'started_at' in docker_data:
                    try:
                        started_at = docker_data['started_at']
                        if started_at:
                            started_at = started_at.split('.')[0]
                            if started_at.endswith('Z'):
                                started_at = started_at[:-1]

                            start_time = datetime.fromisoformat(started_at)
                            container_uptime = (now - start_time).total_seconds()

                            metrics.append(
                                f'github_runner_container_uptime_seconds{{runner_id="{runner_id}",host="{host}",tag="{tag}",run_level="{run_level}"}} {container_uptime}')
                    except (ValueError, TypeError) as e:
                        logger.warning(f"Error calculating container uptime for {runner_id}: {e}")

                # Process job information if available
                if container_status == 'running':
                    job_name = docker_data.get('job_name', f"Unknown Job ({runner_id})")
                    job_id = docker_data.get('job_id', container_id[:12])
                    workflow_name = docker_data.get('workflow_name', 'Unknown Workflow')

                    # Clean strings for Prometheus
                    job_name = job_name.replace('"', '\\"').replace('\n', ' ').strip()
                    workflow_name = workflow_name.replace('"', '\\"').replace('\n', ' ').strip()

                    # Add job info metric
                    metrics.append(
                        f'github_runner_job_info{{runner_id="{runner_id}",host="{host}",tag="{tag}",job_name="{job_name}",job_id="{job_id}",workflow="{workflow_name}",run_level="{run_level}"}} 1')

                    # Calculate job runtime
                    job_start_time = docker_data.get('job_start_time')
                    if job_start_time:
                        job_runtime = (now - job_start_time).total_seconds()
                        metrics.append(
                            f'github_runner_job_runtime_seconds{{runner_id="{runner_id}",host="{host}",tag="{tag}",job_name="{job_name}",job_id="{job_id}",run_level="{run_level}"}} {job_runtime}')
            else:
                # Container not found
                metrics.append(
                    f'github_runner_container_status{{runner_id="{runner_id}",host="{host}",tag="{tag}",container_id="none",run_level="unknown"}} 0')

            # Process systemd unit status
            if systemd_data:
                service_status = systemd_data.get('active', 'inactive').lower()
                service_sub_status = systemd_data.get('sub', '').lower()

                # Determine the status value
                if service_status == 'active':
                    status_value = systemd_status_values['active']
                elif service_status == 'activating':
                    status_value = systemd_status_values['activating']
                elif service_status == 'deactivating':
                    status_value = systemd_status_values['deactivating']
                elif service_status == 'failed' or service_sub_status == 'failed':
                    status_value = systemd_status_values['failed']
                else:
                    status_value = systemd_status_values['inactive']

                metrics.append(
                    f'github_runner_service_status{{runner_id="{runner_id}",host="{host}",tag="{tag}",unit="{unit}",status="{service_status}",substatus="{service_sub_status}",run_level="{run_level}"}} {status_value}')

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
            logger.info(f"Updated metrics file with {len(metrics)} lines")
        except Exception as e:
            logger.exception(f"Error writing metrics: {e}")

    def run_once(self):
        """Run collection once"""
        # Set last_run to now before collecting data
        last_run_before = self.last_run
        self.last_run = datetime.now()

        # Collect data from all sources
        journal_logs = self.query_journal()
        docker_containers = self.query_docker_containers()
        systemd_units = self.query_systemd_units()

        if not journal_logs and not docker_containers and not systemd_units:
            logger.warning("No data found from any source")
            # Reset last_run if we didn't find anything
            self.last_run = last_run_before
            return

        # Process and write metrics
        metrics = self.process_metrics(journal_logs, docker_containers, systemd_units)
        self.write_metrics(metrics)

    def run_daemon(self):
        """Run as daemon, collecting metrics at regular intervals"""
        logger.info(f"Starting metrics collector, interval: {self.interval}s")

        while True:
            try:
                self.run_once()
            except Exception as e:
                logger.exception(f"Error in collector loop: {e}")

            time.sleep(self.interval)


def main():
    parser = argparse.ArgumentParser(description='GitHub Runner Metrics Collector')
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

    collector = GithubRunnerMetricsCollector(args.output_dir, args.interval)

    if not collector.get_lock():
        sys.exit(1)

    try:
        if args.once:
            collector.run_once()
        else:
            collector.run_daemon()
    finally:
        collector.release_lock()


if __name__ == "__main__":
    main()

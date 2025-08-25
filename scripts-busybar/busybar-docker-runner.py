#!/usr/bin/env python3
import time
import json
import pyudev
import docker
import socket
import atexit
import pathlib
import logging
import argparse
import configparser
import telnetlib
import serial
from enum import Enum
from pygelf import GelfHttpsHandler
import os
from datetime import datetime


class JournalAdapter(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        kwargs.setdefault('extra', {})
        return msg, kwargs


logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)


class RunnerState(Enum):
    OFFLINE = "offline"
    STARTING = "starting"
    REPAIRING = "repairing"
    ONLINE = "online"
    ERROR = "error"
    FLASHING = "flashing"


class BusyBarDocker:
    class RunLevel(Enum):
        REPAIR = 0
        NORMAL = 1

    def __init__(self, busybar_id: str, blackmagic_id: str, github_tag: str):
        self.logger = logging.getLogger()
        self.journal_logger = JournalAdapter(self.logger, {})
        self.logger.setLevel(logging.DEBUG)
        self.pyudev_context = pyudev.Context()
        self.docker_client = docker.from_env()
        self.busybar_id = busybar_id
        self.blackmagic_id = blackmagic_id
        self.github_tag = github_tag
        self.devices = []
        self.device_mappings = {}
        self.toolchain_directory = f"/opt/{self.busybar_id}"
        self.run_level = self.RunLevel.REPAIR
        self.container = None
        self.image = None
        self.runner_state = RunnerState.OFFLINE
        self.last_state_change = datetime.now().isoformat()
        self.busybar_ip = "10.0.4.20"  # Default BusyBar IP
        self._parse_config()
        self._init_logs()
        self._build_image()
        self.report_state(RunnerState.STARTING)

    def report_state(self, state: RunnerState, error_message: str = None):
        """Report runner state in a structured format to systemd journal"""
        self.runner_state = state
        self.last_state_change = datetime.now().isoformat()

        state_data = {
            "RUNNER_ID": self.busybar_id,
            "RUNNER_STATE": state.value,
            "RUNNER_TAG": self.github_tag,
            "STATE_TIMESTAMP": self.last_state_change,
            "MONITORING_TYPE": "github_runner_state"
        }

        if error_message:
            state_data["ERROR_MESSAGE"] = error_message

        log_message = f"Runner state: {state.value}"
        if error_message:
            log_message += f" - Error: {error_message}"

        self.logger.info(f"{log_message} {json.dumps(state_data)}")

    def _create_toolchain_directory(self) -> None:
        pathlib.Path(self.toolchain_directory).mkdir(parents=True, exist_ok=True)

    def _parse_config(self):
        try:
            config_file_path = "/var/lib/busybar-docker/busybar-docker.cfg"
            config = configparser.ConfigParser()
            config.read(config_file_path)
            self.config = config

            # Get BusyBar specific config if available
            if "busybar" in config:
                self.busybar_ip = config["busybar"].get("ip", "10.0.4.20")

        except Exception as e:
            self.logger.exception("Failed to parse configuration file.", exc_info=e)
            self.report_state(RunnerState.ERROR, f"Failed to parse config: {str(e)}")

    def _init_logs(self):
        try:
            if "gelf" not in self.config:
                return
            auth_host = self.config["gelf"]["host"]
            auth_port = self.config["gelf"]["port"]
            auth_user = self.config["gelf"]["username"]
            auth_pass = self.config["gelf"]["password"]
            hostname = socket.gethostname()
            hostname_short = hostname.split(".", 1)[0]
            handler = GelfHttpsHandler(
                host=auth_host,
                port=auth_port,
                username=auth_user,
                password=auth_pass,
                _runner_name=f"{hostname_short}-{self.busybar_id}",
                _app="busybar-docker-qa",
            )
            self.logger.addHandler(handler)
        except Exception as e:
            self.logger.exception("Failed to initialize GELF logging.", exc_info=e)
            self.report_state(RunnerState.ERROR, f"Failed to initialize logging: {str(e)}")

    def _build_image(self):
        try:
            dockerfile_path = "/var/lib/busybar-docker/"
            image_tag = f"busybar-custom-image:{self.github_tag}"

            try:
                existing = self.docker_client.containers.get(self.busybar_id)
                self.logger.info(f"Found existing container '{self.busybar_id}' with status '{existing.status}'")

                if existing.status == "running":
                    self.logger.info("Stopping existing container...")
                    existing.stop(timeout=10)

                self.logger.info("Removing existing container...")
                existing.remove(force=True)
                self.logger.info("Existing container removed successfully")
            except docker.errors.NotFound:
                pass
            except Exception as e:
                self.logger.warning(f"Error handling existing container: {str(e)}")

            try:
                existing_image = self.docker_client.images.get(image_tag)
                self.logger.info(f"Image '{image_tag}' already exists with ID '{existing_image.id}'. Skipping build.")
                self.image = existing_image
                return
            except docker.errors.ImageNotFound:
                self.logger.info(f"Image '{image_tag}' not found. Building new image...")
            except Exception as e:
                self.logger.warning(f"Error checking for existing image: {str(e)}")

            self.logger.info(
                f"Building Docker image with tag '{image_tag}' from '{dockerfile_path}'..."
            )

            image, build_logs = self.docker_client.images.build(
                path=dockerfile_path,
                tag=image_tag,
                rm=True,
            )

            for chunk in build_logs:
                if "stream" in chunk:
                    for line in chunk["stream"].splitlines():
                        self.logger.debug(line)

            self.image = image
            self.logger.info(f"Docker image '{image_tag}' built successfully.")

        except docker.errors.BuildError as build_err:
            self.logger.error("Docker build failed.", exc_info=build_err)
            self.report_state(RunnerState.ERROR, f"Docker build failed: {str(build_err)}")
            raise
        except docker.errors.APIError as api_err:
            self.logger.error("Docker API error during build.", exc_info=api_err)
            self.report_state(RunnerState.ERROR, f"Docker API error: {str(api_err)}")
            raise
        except Exception as e:
            self.logger.exception("Unexpected error during Docker build.", exc_info=e)
            self.report_state(RunnerState.ERROR, f"Build error: {str(e)}")
            raise

    def find_device_by_id_and_get_path(
            self, device_id: str, device_subsystem: str
    ) -> str:
        try:
            devices = self.pyudev_context.list_devices(subsystem=device_subsystem)
            device = next(
                filter(lambda x: x.get("ID_SERIAL_SHORT") == device_id, devices)
            )
            return device.device_node
        except StopIteration:
            error_msg = f"Device {device_id} not found!"
            self.logger.error(error_msg)
            self.report_state(RunnerState.ERROR, error_msg)
        except Exception as e:
            self.logger.exception("Error finding device.", exc_info=e)
            self.report_state(RunnerState.ERROR, f"Device error: {str(e)}")

    def find_busybar_network_interface(self) -> str:
        """Find the BusyBar USB Ethernet interface"""
        try:
            devices = self.pyudev_context.list_devices(subsystem="net")
            for device in devices:
                parent = device.parent
                if parent and parent.get("ID_VENDOR_ID") == "37c1" and parent.get("ID_MODEL_ID") == "6213":
                    interface_name = device.sys_name
                    self.logger.info(f"Found BusyBar network interface: {interface_name}")
                    return interface_name
        except Exception as e:
            self.logger.error(f"Error finding BusyBar network interface: {e}")
        return None

    def find_devices(self) -> None:
        self.devices = []
        self.device_mappings = {}

        # Find Blackmagic UART devices
        tty_devices = self.pyudev_context.list_devices(subsystem="tty")
        blackmagic_ttys = []

        for device in tty_devices:
            if device.parent and device.parent.get("ID_SERIAL_SHORT") == self.blackmagic_id:
                blackmagic_ttys.append(device.device_node)

        # Typically ttyACM0 is for u5 CPU, ttyACM1 is for 917 CPU
        if len(blackmagic_ttys) >= 2:
            blackmagic_ttys.sort()  # Ensure consistent ordering
            self.device_mappings[blackmagic_ttys[0]] = "/dev/tty_busybar_u5"
            self.device_mappings[blackmagic_ttys[1]] = "/dev/tty_busybar_917"
            self.devices.extend(blackmagic_ttys)
            self.logger.info(f"Found Blackmagic UART devices: {blackmagic_ttys}")
        else:
            self.logger.warning(f"Expected 2 Blackmagic UART devices, found {len(blackmagic_ttys)}")

        # Find BusyBar network interface
        busybar_interface = self.find_busybar_network_interface()
        if busybar_interface:
            self.busybar_interface = busybar_interface

    def test_busybar_telnet_connection(self) -> bool:
        """Test if BusyBar CLI is accessible via telnet"""
        try:
            tn = telnetlib.Telnet(self.busybar_ip, 23, timeout=5)
            tn.close()
            self.logger.info(f"BusyBar CLI accessible at {self.busybar_ip}:23")
            return True
        except Exception as e:
            self.logger.warning(f"Cannot connect to BusyBar CLI at {self.busybar_ip}:23: {e}")
            return False

    def create_docker_container(self) -> None:
        if not self.image:
            error_msg = "Docker image is not built. Cannot create container."
            self.logger.error(error_msg)
            self.report_state(RunnerState.ERROR, error_msg)
            return

        hostname = socket.gethostname().split(".", 1)[0]
        volumes = {
            self.toolchain_directory: {"bind": "/opt/toolchain", "mode": "rw"},
            "~/.cache/ccache": {"bind": "/root/.cache/ccache", "mode": "rw"},
            f"/dev/busybar/{self.busybar_id}": {"bind": f"/dev/{self.busybar_id}", "mode": "rw",
                                                "propagation": "shared"},
        }

        device_mappings = []
        for host_device, container_device in self.device_mappings.items():
            device_mappings.append(f"{host_device}:{container_device}")
        for device in self.devices:
            if device not in self.device_mappings:
                device_mappings.append(device)

        try:
            github_org_name = self.config["github"]["org_name"]
            github_app_id = self.config["github"]["app_id"]
            github_private_key = self.config["github"]["app_private_key"]
        except KeyError as e:
            error_msg = f"Missing GitHub configuration: {e}"
            self.logger.error(error_msg)
            self.report_state(RunnerState.ERROR, error_msg)
            raise
        except Exception as e:
            self.logger.exception("Error reading GitHub configuration.", exc_info=e)
            self.report_state(RunnerState.ERROR, f"Config error: {str(e)}")
            raise

        self.logger.debug(f"BUSYBAR_ID: {self.busybar_id}")
        self.logger.debug(f"BLACKMAGIC_ID: {self.blackmagic_id}")
        environment = {
            "ORG_NAME": github_org_name,
            "APP_ID": github_app_id,
            "APP_PRIVATE_KEY": github_private_key,
            "DEBUG_OUTPUT": True,
            "RUNNER_NAME": f"{hostname}-{self.busybar_id}",
            "LABELS": self.github_tag,
            "RUN_LEVEL": self.run_level.name,
            "RUNNER_SCOPE": "org",
            "EPHEMERAL": "1",
            "BUSYBAR_IP": self.busybar_ip,
        }

        self.logger.info(
            f"Creating Docker container '{self.busybar_id}' from image '{self.image.tags[0]}'..."
        )

        try:
            # Test BusyBar connectivity before starting container
            if self.run_level == self.RunLevel.REPAIR:
                self.test_busybar_telnet_connection()
                self.report_state(RunnerState.REPAIRING)
            elif self.run_level == self.RunLevel.NORMAL:
                self.report_state(RunnerState.STARTING)

            # Network mode host to access BusyBar at 10.0.4.20
            self.container = self.docker_client.containers.run(
                image=self.image.tags[0],
                name=self.busybar_id,
                environment=environment,
                devices=device_mappings,
                volumes=volumes,
                auto_remove=True,
                detach=True,
                network_mode="host",  # Important for BusyBar telnet access
                device_cgroup_rules=['c 166:* rwm', 'c 188:* rwm'],  # ttyUSB and ttyACM
                cap_add=["SYS_ADMIN", "NET_ADMIN"],  # NET_ADMIN for network access
                command=["/entrypoint-busybar.sh", self.busybar_id, self.blackmagic_id],
            )

            if self.run_level == self.RunLevel.NORMAL:
                self.report_state(RunnerState.ONLINE)
            elif self.run_level == self.RunLevel.REPAIR:
                self.report_state(RunnerState.FLASHING)

            self.logger.info("Container started successfully.")
        except docker.errors.ContainerError as ce:
            self.logger.error("Container exited with an error.", exc_info=ce)
            self.report_state(RunnerState.ERROR, f"Container error: {str(ce)}")
            raise
        except docker.errors.APIError as api_err:
            self.logger.error(
                "Docker API error during container creation.", exc_info=api_err
            )
            self.report_state(RunnerState.ERROR, f"API error: {str(api_err)}")
            raise
        except Exception as e:
            self.logger.exception(
                "Unexpected error during container creation.", exc_info=e
            )
            self.report_state(RunnerState.ERROR, f"Container creation error: {str(e)}")
            raise

    def at_exit(self):
        self.logger.debug("At exit handler was reached!")
        if self.container:
            try:
                self.container.stop()
                self.logger.info("Container stopped due to application exit.")
                self.report_state(RunnerState.OFFLINE)
            except docker.errors.DockerException:
                self.logger.info(
                    "Nothing to stop, container not found or already stopped."
                )
                self.report_state(RunnerState.OFFLINE)

    def run(self):
        self.logger.info("Application started!")
        atexit.register(self.at_exit)
        self._create_toolchain_directory()

        for run_level in self.RunLevel:
            self.logger.debug(f"Running in {run_level.name} mode!")
            self.run_level = run_level

            if run_level == self.RunLevel.REPAIR:
                self.report_state(RunnerState.REPAIRING)

            self.find_devices()
            self.logger.debug(f"Found devices: {self.devices}")
            self.create_docker_container()

            if not self.container:
                error_msg = "Container was not created. Exiting run loop."
                self.logger.error(error_msg)
                self.report_state(RunnerState.ERROR, error_msg)
                break

            container_result = self.container.wait()
            container_exit_code = container_result.get("StatusCode")

            if container_exit_code not in [0, 4]:
                error_msg = f"Container exited with code {container_exit_code}!"
                self.logger.error(error_msg)
                self.logger.error(self.container.logs().decode("utf-8"))
                self.report_state(RunnerState.ERROR, error_msg)
                self.container = None
                break

            self.container = None

            if run_level == self.RunLevel.REPAIR:
                timeout_sec = 10
                self.logger.info(f"Waiting {timeout_sec} seconds for BusyBar to boot!")
                time.sleep(timeout_sec)

        if self.runner_state != RunnerState.ERROR:
            self.report_state(RunnerState.ONLINE)

        atexit.unregister(self.at_exit)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="BusyBar Docker Manager")
    parser.add_argument("busybar_id", help="ID of the BusyBar device")
    parser.add_argument("blackmagic_id", help="ID of the Blackmagic device")
    parser.add_argument("github_tag", help="GitHub tag for the runner")
    args = parser.parse_args()
    busybar_docker = BusyBarDocker(
        busybar_id=args.busybar_id,
        blackmagic_id=args.blackmagic_id,
        github_tag=args.github_tag,
    )
    busybar_docker.run()

# ====================
# docker-busybar/entrypoint-busybar.sh
# ====================

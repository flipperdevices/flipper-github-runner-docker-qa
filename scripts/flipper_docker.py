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
from enum import Enum
from pygelf import GelfHttpsHandler
import os
from datetime import datetime


# Set up structured logging for systemd journal
class JournalAdapter(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        # Add structured fields for systemd journal
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


class FlipperDocker:
    class RunLevel(Enum):
        REPAIR = 0
        NORMAL = 1

    def __init__(self, flipper_id: str, st_link_id: str, github_tag: str):
        self.logger = logging.getLogger()
        self.journal_logger = JournalAdapter(self.logger, {})
        self.logger.setLevel(logging.DEBUG)
        self.pyudev_context = pyudev.Context()
        self.docker_client = docker.from_env()
        self.flipper_id = flipper_id
        self.st_link_id = st_link_id
        self.github_tag = github_tag
        self.devices = []
        self.device_mappings = {}
        self.toolchain_directory = f"/opt/{self.flipper_id}"
        self.run_level = self.RunLevel.REPAIR
        self.container = None
        self.image = None
        self.runner_state = RunnerState.OFFLINE
        self.last_state_change = datetime.now().isoformat()
        self._parse_config()
        self._init_logs()
        self._build_image()
        self.report_state(RunnerState.STARTING)

    def report_state(self, state: RunnerState, error_message: str = None):
        """Report runner state in a structured format to systemd journal"""
        self.runner_state = state
        self.last_state_change = datetime.now().isoformat()

        # Create structured data for journal
        state_data = {
            "RUNNER_ID": self.flipper_id,
            "RUNNER_STATE": state.value,
            "RUNNER_TAG": self.github_tag,
            "STATE_TIMESTAMP": self.last_state_change,
            "MONITORING_TYPE": "github_runner_state"
        }

        if error_message:
            state_data["ERROR_MESSAGE"] = error_message

        # Log as both text and structured data
        log_message = f"Runner state: {state.value}"
        if error_message:
            log_message += f" - Error: {error_message}"

        # Log using JSON formatted string that systemd journal can parse
        self.logger.info(f"{log_message} {json.dumps(state_data)}")

    def _create_toolchain_directory(self) -> None:
        pathlib.Path(self.toolchain_directory).mkdir(parents=True, exist_ok=True)

    def _parse_config(self):
        try:
            config_file_path = "/var/lib/flipper-docker/flipper-docker.cfg"
            config = configparser.ConfigParser()
            config.read(config_file_path)
            self.config = config
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
                _runner_name=f"{hostname_short}-{self.flipper_id}",
                _app="flipper-docker-qa",
            )
            self.logger.addHandler(handler)
        except Exception as e:
            self.logger.exception("Failed to initialize GELF logging.", exc_info=e)
            self.report_state(RunnerState.ERROR, f"Failed to initialize logging: {str(e)}")

    def _build_image(self):
        try:
            dockerfile_path = "/var/lib/flipper-docker/"
            image_tag = f"flipper-custom-image:{self.github_tag}"

            # Check if we already have this container running
            try:
                existing = self.docker_client.containers.get(self.flipper_id)
                self.logger.info(f"Found existing container '{self.flipper_id}' with status '{existing.status}'")

                if existing.status == "running":
                    self.logger.info("Stopping existing container...")
                    existing.stop(timeout=10)

                self.logger.info("Removing existing container...")
                existing.remove(force=True)
                self.logger.info("Existing container removed successfully")
            except docker.errors.NotFound:
                # No existing container found, which is fine
                pass
            except Exception as e:
                self.logger.warning(f"Error handling existing container: {str(e)}")

            self.logger.info(
                f"Building Docker image with tag '{image_tag}' from '{dockerfile_path}'..."
            )

            # Build the image
            image, build_logs = self.docker_client.images.build(
                path=dockerfile_path,
                tag=image_tag,
                rm=True,  # Remove intermediate containers after a successful build
            )

            # Log build output
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

    def find_devices(self) -> None:
        self.devices = []
        self.device_mappings = {}

        tty_path = self.find_device_by_id_and_get_path(
            device_id=self.st_link_id, device_subsystem="tty"
        )
        usb_path = self.find_device_by_id_and_get_path(
            device_id=self.st_link_id, device_subsystem="usb"
        )
        flipper_tty_path = self.find_device_by_id_and_get_path(
            device_id=self.flipper_id, device_subsystem="tty"
        )

        if tty_path:
            # Find all symlinks pointing to this device
            tty_symlinks = self.find_symlinks_to_device(tty_path)
            tty_device_to_use = tty_symlinks[0] if tty_symlinks else tty_path

            if tty_symlinks:
                self.logger.debug(f"Found symlinks for {tty_path}: {tty_symlinks}")
                self.logger.debug(f"Using symlink {tty_device_to_use} for ST-Link device")

            self.device_mappings[tty_device_to_use] = "/dev/tty_stlink"
            self.devices.append(tty_device_to_use)

        if usb_path:
            self.devices.append(usb_path)

        if flipper_tty_path:
            # Try to find symlinks first
            flipper_symlinks = self.find_symlinks_to_device(flipper_tty_path)
            flipper_device_to_use = flipper_symlinks[0] if flipper_symlinks else flipper_tty_path

            # Log what we're using
            if flipper_symlinks:
                self.logger.debug(f"Found symlinks for {flipper_tty_path}: {flipper_symlinks}")
                self.logger.debug(f"Using symlink {flipper_device_to_use} for Flipper device")

            # USE THE SYMLINK PATH, not the original
            # For some reason, flipper does not detect when using ACM0 or if more than 10 are used.
            self.device_mappings[flipper_device_to_use] = "/dev/ttyACM3"
            self.devices.append(flipper_device_to_use)

        self.logger.debug(f"Final devices: {self.devices}")
        self.logger.debug(f"Device mappings: {self.device_mappings}")

    def find_symlinks_to_device(self, target_path):
        """Find all symlinks pointing to the given device path"""
        symlinks = []
        try:
            # Resolve to absolute path if it's a relative symlink
            target_real_path = os.path.realpath(target_path)

            # Common locations for device symlinks
            device_dirs = ['/dev', '/dev/serial/by-id', '/dev/serial/by-path']

            for dir_path in device_dirs:
                if not os.path.exists(dir_path):
                    continue

                for filename in os.listdir(dir_path):
                    full_path = os.path.join(dir_path, filename)
                    if os.path.islink(full_path):
                        # Check if this symlink points to our target
                        if os.path.realpath(full_path) == target_real_path:
                            symlinks.append(full_path)

            return symlinks
        except Exception as e:
            self.logger.warning(f"Error finding symlinks for {target_path}: {str(e)}")
            return []

    def create_docker_container(self) -> None:
        if not self.image:
            error_msg = "Docker image is not built. Cannot create container."
            self.logger.error(error_msg)
            self.report_state(RunnerState.ERROR, error_msg)
            return

        hostname = socket.gethostname().split(".", 1)[0]
        volumes = {
            self.toolchain_directory: {"bind": "/opt/toolchain", "mode": "rw"},
            "/root/.cache/ccache": {"bind": "/root/.cache/ccache", "mode": "rw"},
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
            github_access_token = self.config["github"]["access_token"]
        except KeyError as e:
            error_msg = f"Missing GitHub configuration: {e}"
            self.logger.error(error_msg)
            self.report_state(RunnerState.ERROR, error_msg)
            raise
        except Exception as e:
            self.logger.exception("Error reading GitHub configuration.", exc_info=e)
            self.report_state(RunnerState.ERROR, f"Config error: {str(e)}")
            raise

        self.logger.debug(f"FLIPPER_ID: {self.flipper_id}")
        self.logger.debug(f"ST_LINK_ID: {self.st_link_id}")
        environment = {
            "ORG_NAME": github_org_name,
            "APP_ID": github_app_id,
            "APP_PRIVATE_KEY": github_private_key,
            "DEBUG_OUTPUT": True,
            # "RUNNER_TOKEN": github_access_token,
            "RUNNER_NAME": f"{hostname}-{self.flipper_id}",
            "LABELS": self.github_tag,
            "RUN_LEVEL": self.run_level.name,
            "RUNNER_SCOPE": "org",
            "EPHEMERAL": "1",
        }

        self.logger.info(
            f"Creating Docker container '{self.flipper_id}' from image '{self.image.tags[0]}'..."
        )

        try:
            # Report appropriate state based on run level
            if self.run_level == self.RunLevel.REPAIR:
                self.report_state(RunnerState.REPAIRING)
            elif self.run_level == self.RunLevel.NORMAL:
                self.report_state(RunnerState.STARTING)

            self.container = self.docker_client.containers.run(
                image=self.image.tags[0],
                name=self.flipper_id,
                environment=environment,
                devices=device_mappings,
                volumes=volumes,
                auto_remove=True,
                detach=True,
                command=["/entrypoint.sh", self.flipper_id, self.st_link_id],
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
                timeout_sec = 7
                self.logger.info(f"Waiting {timeout_sec} seconds for flipper to boot!")
                time.sleep(timeout_sec)

        # If we've completed all run levels successfully, we should be ONLINE
        if self.runner_state != RunnerState.ERROR:
            self.report_state(RunnerState.ONLINE)

        atexit.unregister(self.at_exit)  # Container already exited and removed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Flipper Docker Manager")
    parser.add_argument("flipper_id", help="ID of the Flipper device")
    parser.add_argument("st_link_id", help="ID of the ST-Link device")
    parser.add_argument("github_tag", help="GitHub tag for the runner")
    args = parser.parse_args()
    flipper_docker = FlipperDocker(
        flipper_id=args.flipper_id,
        st_link_id=args.st_link_id,
        github_tag=args.github_tag,
    )
    flipper_docker.run()
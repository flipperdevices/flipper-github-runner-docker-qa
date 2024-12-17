import time

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

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

class FlipperDocker:
    class RunLevel(Enum):
        REPAIR = 0
        NORMAL = 1

    def __init__(self, flipper_id: str, st_link_id: str, github_tag: str):
        self.logger = logging.getLogger()
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
        self._parse_config()
        self._init_logs()
        self._build_image()

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

    def _build_image(self):
        try:
            dockerfile_path = "/var/lib/flipper-docker/"
            image_tag = f"flipper-custom-image:{self.github_tag}"

            self.logger.info(f"Building Docker image with tag '{image_tag}' from '{dockerfile_path}'...")

            # Build the image
            image, build_logs = self.docker_client.images.build(
                path=dockerfile_path,
                tag=image_tag,
                rm=True  # Remove intermediate containers after a successful build
            )

            # Log build output
            for chunk in build_logs:
                if 'stream' in chunk:
                    for line in chunk['stream'].splitlines():
                        self.logger.debug(line)

            self.image = image
            self.logger.info(f"Docker image '{image_tag}' built successfully.")

        except docker.errors.BuildError as build_err:
            self.logger.error("Docker build failed.", exc_info=build_err)
            raise
        except docker.errors.APIError as api_err:
            self.logger.error("Docker API error during build.", exc_info=api_err)
            raise
        except Exception as e:
            self.logger.exception("Unexpected error during Docker build.", exc_info=e)
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
            self.logger.error(f"Device {device_id} not found!")
        except Exception as e:
            self.logger.exception("Error finding device.", exc_info=e)

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
            self.device_mappings[tty_path] = "/dev/tty_stlink"
            self.devices.append(tty_path)
        if usb_path:
            self.devices.append(usb_path)
        if flipper_tty_path:
            self.devices.append(flipper_tty_path)

    def create_docker_container(self) -> None:
        if not self.image:
            self.logger.error("Docker image is not built. Cannot create container.")
            return

        hostname = socket.gethostname().split(".", 1)[0]
        volumes = {self.toolchain_directory: {'bind': '/opt/toolchain', 'mode': 'rw'},
                   '/root/.cache/ccache': {'bind': '/root/.cache/ccache', 'mode': 'rw'}}

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
            self.logger.error(f"Missing GitHub configuration: {e}")
            raise
        except Exception as e:
            self.logger.exception("Error reading GitHub configuration.", exc_info=e)
            raise
        self.logger.debug(f"FLIPPER_ID: {self.flipper_id}")
        self.logger.debug(f"ST_LINK_ID: {self.st_link_id}")
        environment = {
            "ORG_NAME": github_org_name,
            "APP_ID": github_app_id,
            "APP_PRIVATE_KEY": github_private_key,
            "DEBUG_OUTPUT": True,
#            "RUNNER_TOKEN": github_access_token,
            "RUNNER_NAME": f"{hostname}-{self.flipper_id}",
            "LABELS": self.github_tag,
            "RUN_LEVEL": self.run_level.name,
            "RUNNER_SCOPE": "org",
            "EPHEMERAL": "1",
        }

        self.logger.info(f"Creating Docker container '{self.flipper_id}' from image '{self.image.tags[0]}'...")

        try:
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
            self.logger.info("Container started successfully.")
        except docker.errors.ContainerError as ce:
            self.logger.error("Container exited with an error.", exc_info=ce)
            raise
        except docker.errors.APIError as api_err:
            self.logger.error("Docker API error during container creation.", exc_info=api_err)
            raise
        except Exception as e:
            self.logger.exception("Unexpected error during container creation.", exc_info=e)
            raise

    def at_exit(self):
        self.logger.debug("At exit handler was reached!")
        if self.container:
            try:
                self.container.stop()
                self.logger.info("Container stopped due to application exit.")
            except docker.errors.DockerException:
                self.logger.info("Nothing to stop, container not found or already stopped.")

    def run(self):
        self.logger.info("Application started!")
        atexit.register(self.at_exit)
        self._create_toolchain_directory()
        for run_level in self.RunLevel:
            self.logger.debug(f"Running in {run_level.name} mode!")
            self.run_level = run_level
            self.find_devices()
            self.logger.debug(f"Found devices: {self.devices}")
            self.create_docker_container()
            if not self.container:
                self.logger.error("Container was not created. Exiting run loop.")
                break
            container_result = self.container.wait()
            container_exit_code = container_result.get("StatusCode")
            if container_exit_code not in [0, 4]:
                self.logger.error(f"Container exited with code {container_exit_code}!")
                self.logger.error(self.container.logs().decode('utf-8'))
                self.container = None
                break
            self.container = None
            if run_level == self.RunLevel.REPAIR:
                timeout_sec = 7
                self.logger.info(f"Waiting {timeout_sec} seconds for flipper to boot!")
                time.sleep(timeout_sec)
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

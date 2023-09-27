#!/usr/bin/env python3

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
        self.toolchain_directory = f"/opt/{self.flipper_id}"
        self.run_level = self.RunLevel.REPAIR
        self._parse_config()
        self._init_logs()

    def _parse_config(self):
        try:
            config_file_path = "/var/lib/flipper-docker/flipper-docker.cfg"
            config = configparser.ConfigParser()
            config.read(config_file_path)
            self.config = config
        except Exception as e:
            self.logger.exception(e)

    def _init_logs(self):
        try:
            if not self.config["gelf"]:
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
            self.logger.exception(e)

    def _create_toolchain_directory(self) -> None:
        pathlib.Path(self.toolchain_directory).mkdir(parents=True, exist_ok=True)

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
            self.logger.exception(e)

    def find_devices(self) -> None:
        self.devices = []
        self.devices.append(
            self.find_device_by_id_and_get_path(
                device_id=self.st_link_id, device_subsystem="tty"
            )
        )
        self.devices.append(
            self.find_device_by_id_and_get_path(
                device_id=self.st_link_id, device_subsystem="usb"
            )
        )
        if self.run_level == self.RunLevel.NORMAL:
            self.devices.append(
                self.find_device_by_id_and_get_path(
                    device_id=self.flipper_id, device_subsystem="tty"
                )
            )

    def create_docker_container(self) -> None:
        hostname = socket.gethostname().split(".", 1)[0]
        volumes = [f"{self.toolchain_directory}:/opt/toolchain"]
        image = "flipperdevices/flipper-github-runner-docker-qa:0.0.9"
        try:
            github_org_name = self.config["github"]["org_name"]
            github_access_token = self.config["github"]["access_token"]
        except Exception as e:
            logging.exception(e)
        environment = [
            f"ORG_NAME={github_org_name}",
            f"ACCESS_TOKEN={github_access_token}",
            f"RUNNER_NAME={hostname}-{self.flipper_id}",
            f"LABELS={self.github_tag}",
            f"RUN_LEVEL={self.run_level.name}",
            "RUNNER_SCOPE=org",
            "EPHEMERAL=1",
        ]
        self.container = self.docker_client.containers.run(
            environment=environment,
            name=self.flipper_id,
            devices=self.devices,
            volumes=volumes,
            image=image,
            auto_remove=True,
            detach=True,
        )
        self.logger.info("Container started!")

    def at_exit(self):
        self.logger.debug("At exit handler was reached!")
        if self.container:
            try:
                self.container.stop()
                self.logger.info("Container stopped due app exit!")
            except docker.errors.DockerException:
                self.logger.info("Nothing to stop, container not found")

    def run(self):
        self.logger.info("App started!")
        atexit.register(self.at_exit)
        self._create_toolchain_directory()
        for run_level in self.RunLevel:
            self.logger.debug(f"Running into {run_level.name} mode!")
            self.run_level = run_level
            self.find_devices()
            self.create_docker_container()
            container_result = self.container.wait()
            container_exit_code = container_result.get("StatusCode")
            if container_exit_code != 0:
                self.logger.error(f"Container exited with code {container_exit_code}!")
                self.logger.error(self.container.logs())
                self.container = None
                break
            self.container = None
            if run_level == self.RunLevel.REPAIR:
                timeout_sec = 7
                self.logger.info(f"Waiting {timeout_sec} to flipper boot!")
                time.sleep(timeout_sec)
        atexit.unregister(self.at_exit)  # container already exited and removed


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("flipper_id")
    parser.add_argument("st_link_id")
    parser.add_argument("github_tag")
    args = parser.parse_args()
    flipper_docker = FlipperDocker(
        flipper_id=args.flipper_id,
        st_link_id=args.st_link_id,
        github_tag=args.github_tag,
    )
    flipper_docker.run()

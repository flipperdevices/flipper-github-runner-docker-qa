# Dockerzied github runners for Flipper QA Team

This module consists of python script, docker image, config file and systemd service.

## Flow
Systemd service starts python script which finds specified st-link and flipper, runns docker container with image builded from /docker directory with the forwarded devices. Docker image starts with the 'REPAIR' state, flashing latest release build will occur here, and then then docker container will exit with the some exit code. This script will exit here if the docker container's exit code isn't equal to 0. In case of success python script will run docker container again in 'NORMAL' state. In this state docker container will register a Self-Hosted Github runner.

## Config file format
File should be placed in `/var/lib/flipper-docker/flipper-docker.cfg`

```bash
[github] # required
access_token = GITHUB_ACCESS_TOKEN # required
org_name = GITHUB_ORG_NAME # required

[gelf] # optional
host = GELF_HTTP_UPLOAD_URL # optional
port = GELF_HTTP_UPLOAD_PORT # optional
username = GELF_HTTP_UPLOAD_BASIC_AUTH_USER # optional
password = GELF_HTTP_UPLOAD_BASIC_AUTH_PASS # optional
```

GITHUB_ACCESS_TOKEN - Github Personal Access Token
GITHUB_ORG_NAME - Github authorization name
GELF_HTTP_UPLOAD_URL - gelf http hostname
GELF_HTTP_UPLOAD_PORT - gelf http port
GELF_HTTP_UPLOAD_BASIC_AUTH_USER - gelf http basic auth user (if needed)
GELF_HTTP_UPLOAD_BASIC_AUTH_PASS - gelf http basic auth password (if needed)

## Systemd service
For each Flipper+ST-Link pair you need an individual systemd service

```bash
[Unit]
Description=Dockerized github runner FLIPPER_SHORT_NAME
After=docker.service
Requires=docker.service

[Service]
TimeoutStartSec=0
Restart=always
ExecStart=sudo /usr/bin/flipper_docker.py FLIPPER_SHORT_NAME ST_LINK_DEVICE_ID GITHUB_RUNNER_TAG
# for example:
# ExecStart=sudo /usr/bin/flipper_docker.py flip_Testii 002F00000000000000000001 FlipperZeroIntegrationTest
KillSignal=SIGINT # it't important to unregister a github runner before shutting down a container

[Install]
WantedBy=multi-user.target
```

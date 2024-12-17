FROM myoung34/github-runner:2.321.0-ubuntu-jammy

ENV DEBIAN_FRONTEND=noninteractive
ARG FirmwareVersion=1.1.2
ARG UpdateServerURL=https://update.flipperzero.one/builds

# Add qFlipper
RUN apt-get update && apt-get install -y \
    build-essential \
    python3 \
    python3-pip \
    python3-venv \
    git \
    protobuf-compiler \
    ccache \
    libusb-1.0-0-dev


# Set up PATH for ccache
ENV PATH="/usr/lib/ccache:${PATH}"

RUN mkdir -p /opt/flipperzero-firmware
RUN wget ${UpdateServerURL}/firmware/${FirmwareVersion}/flipper-z-f7-full-${FirmwareVersion}.bin -O /opt/flipperzero-firmware/firmware.bin

# Add custom entrypoint
COPY entrypoint.sh /opt/
COPY region_data /
COPY flipperzero-firmware /opt/flipperzero-firmware
RUN chmod +x /opt/entrypoint.sh
ENTRYPOINT ["/opt/entrypoint.sh"]
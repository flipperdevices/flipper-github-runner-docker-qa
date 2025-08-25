FROM myoung34/github-runner:2.323.0-ubuntu-jammy

ENV DEBIAN_FRONTEND=noninteractive

# Install required packages
RUN apt-get update && apt-get install -y \
    build-essential \
    python3 \
    python3-pip \
    python3-venv \
    git \
    protobuf-compiler \
    ccache \
    libusb-1.0-0-dev \
    usbutils \
    telnet \
    expect \
    netcat \
    iputils-ping \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install pyserial telnetlib3

# Set up PATH for ccache
ENV PATH="/usr/lib/ccache:${PATH}"

# Create directories
RUN mkdir -p /opt/busybar-firmware

# Add custom entrypoint and scripts
COPY entrypoint-busybar.sh /opt/
COPY uart_monitor.py /opt/
RUN chmod +x /opt/entrypoint-busybar.sh

ENTRYPOINT ["/opt/entrypoint-busybar.sh"]
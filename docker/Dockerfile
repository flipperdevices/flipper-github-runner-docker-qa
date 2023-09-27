FROM myoung34/github-runner:2.308.0-ubuntu-jammy

ARG qFlipperVersion=1.3.2
ARG FirmwareVersion=0.90.1
ARG OpenOCDVersion=0.12.0-2
ARG UpdateServerURL=https://update.flipperzero.one/builds

ENV DEBIAN_FRONTEND=noninteractive
RUN apt update

# Add qFlipper
RUN mkdir -p /opt/qFlipper
RUN apt -y install libusb-1.0-0-dev
RUN wget ${UpdateServerURL}/qFlipper/${qFlipperVersion}/qFlipper-x86_64-${qFlipperVersion}.AppImage -O /tmp/qFlipper.AppImage
RUN chmod +x /tmp/qFlipper.AppImage
RUN cd /tmp && /tmp/qFlipper.AppImage --appimage-extract
RUN cp -r /tmp/squashfs-root/usr/* /opt/qFlipper
ENV PATH="$PATH:/opt/qFlipper/bin"

# Add Flipper Zero firmware
RUN mkdir -p /opt/flipperzero-firmware
RUN wget ${UpdateServerURL}/firmware/${FirmwareVersion}/flipper-z-f7-full-${FirmwareVersion}.bin -O /opt/flipperzero-firmware/firmware.bin

# Add OpenOCD
RUN mkdir -p /opt/openocd
RUN wget https://github.com/xpack-dev-tools/openocd-xpack/releases/download/v${OpenOCDVersion}/xpack-openocd-${OpenOCDVersion}-linux-x64.tar.gz -O /tmp/xpack-openocd.tar.gz
RUN cd /tmp && tar -xvf /tmp/xpack-openocd.tar.gz
RUN cp -r /tmp/xpack-openocd-${OpenOCDVersion}/* /opt/openocd/
ENV PATH="$PATH:/opt/openocd/bin"

# Add custom entrypoint
ADD entrypoint.sh /opt/
RUN chmod +x /opt/entrypoint.sh
ENTRYPOINT ["/opt/entrypoint.sh"]

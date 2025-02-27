#!/usr/bin/python3

import re
import serial
import logging
import threading
import time
from datetime import datetime
import os
from argparse import ArgumentParser
import io

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class SerialMonitor:
    def __init__(self, flipper_id: str, output_file: str, run_level: str = "NORMAL",
                 device_path: str = "/dev/tty_stlink"):
        self.flipper_id = flipper_id
        self.device_path = device_path
        self.output_file = output_file
        self.run_level = run_level
        self.serial = None
        self.sio = None
        self.running = False
        self.thread = None

        # Create directory if it doesn't exist
        output_dir = os.path.dirname(output_file)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)

    def start(self):
        """Start monitoring in a separate thread."""
        self.running = True
        self.thread = threading.Thread(target=self._monitor)
        self.thread.daemon = True
        self.thread.start()
        logger.info(
            f"Started monitoring {self.flipper_id}, logging to {self.output_file}"
        )

    def stop(self):
        """Stop monitoring."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=3)  # Wait for thread to finish with timeout
        if self.serial:
            self.serial.close()
        logger.info(f"Monitoring stopped for {self.flipper_id}")

    def _connect_serial(self):
        """Try to establish a serial connection"""
        try:
            self.serial = serial.Serial(
                self.device_path,
                230400,
                timeout=1,
                exclusive=True  # Ensure exclusive access to the device
            )
            # Use TextIOWrapper for more efficient line reading
            self.sio = io.TextIOWrapper(
                io.BufferedRWPair(self.serial, self.serial),
                encoding='utf-8', errors='replace'
            )
            logger.info(f"Connected to {self.flipper_id} at {self.device_path}")
            return True
        except serial.SerialException as e:
            logger.error(f"Failed to connect to {self.flipper_id}: {e}")
            return False

    def _monitor(self):
        """Main monitoring loop with improved CPU efficiency"""
        connection_retry_interval = 5.0  # Longer retry interval when connection fails
        idle_sleep_time = 0.1  # Sleep time when no data is available (100ms)
        active_sleep_time = 0.005  # Sleep time when actively reading data (5ms)

        last_activity_time = time.time()
        current_sleep_time = idle_sleep_time
        consecutive_empty_reads = 0

        while self.running:
            # Try to establish connection if not connected
            if not self.serial:
                if not self._connect_serial():
                    time.sleep(connection_retry_interval)
                    continue

            try:
                if self.serial.in_waiting:
                    # Reset counters since we have data
                    consecutive_empty_reads = 0
                    last_activity_time = time.time()
                    current_sleep_time = active_sleep_time

                    # Read a line (this is more efficient than raw readline)
                    try:
                        line = self.sio.readline()
                        if line:
                            # Clean control characters
                            line = re.sub(r"[\x00-\x1F\x7F-\x9F]", "", line)
                            datetime_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S,%f")
                            log_line = f"{datetime_str} {line}\n"

                            # Write to file
                            with open(self.output_file, "a") as f:
                                f.write(log_line)

                            # Print to console if not empty
                            if line.strip():
                                print(log_line.strip())

                        # Flush the wrapper to ensure proper reading
                        self.sio.flush()
                    except UnicodeDecodeError:
                        # Handle potential decoding errors
                        logger.warning("Unicode decode error - skipping malformed data")
                        # Reset buffer position
                        self.serial.reset_input_buffer()
                else:
                    # No data available
                    consecutive_empty_reads += 1

                    # Gradually increase sleep time if no activity
                    if consecutive_empty_reads > 10:
                        current_elapsed = time.time() - last_activity_time
                        # After 2 seconds of inactivity, use idle sleep time
                        if current_elapsed > 2.0:
                            current_sleep_time = idle_sleep_time

                # Sleep dynamically based on activity
                time.sleep(current_sleep_time)

            except (serial.SerialException, IOError) as e:
                logger.error(f"Serial connection error for {self.flipper_id}: {e}")
                if self.serial:
                    try:
                        self.serial.close()
                    except Exception:
                        pass
                self.serial = None
                self.sio = None
                time.sleep(connection_retry_interval)


def main():
    parser = ArgumentParser(description="Serial Monitor for Flipper")
    parser.add_argument("flipper_id", help="Flipper device ID")
    parser.add_argument(
        "--run-level",
        choices=["REPAIR", "NORMAL"],
        default="NORMAL",
        help="Run level (default: NORMAL)",
    )
    parser.add_argument("-o", "--output", required=True, help="Output log file path")
    parser.add_argument(
        "-d", "--device-path", default="/dev/tty_stlink", help="Device path (default: /dev/tty_stlink)"
    )
    args = parser.parse_args()

    monitor = SerialMonitor(
        flipper_id=args.flipper_id, output_file=args.output, run_level=args.run_level, device_path=args.device_path
    )

    try:
        monitor.start()
        # Keep the main thread alive
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        monitor.stop()


if __name__ == "__main__":
    main()
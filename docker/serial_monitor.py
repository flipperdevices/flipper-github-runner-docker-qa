#!/usr/bin/python3

import re
import serial
import logging
import threading
import time
from datetime import datetime
import os
from argparse import ArgumentParser

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class SerialMonitor:
    def __init__(self, flipper_id: str, output_file: str, run_level: str = "NORMAL"):
        self.flipper_id = flipper_id
        self.device_path = "/dev/tty_stlink"
        self.output_file = output_file
        self.run_level = run_level
        self.serial = None
        self.running = False
        self.thread = None

        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(output_file), exist_ok=True)

    def start(self):
        """Start monitoring in a separate thread."""
        self.running = True
        self.thread = threading.Thread(target=self._monitor)
        self.thread.daemon = True
        self.thread.start()
        logger.info(f"Started monitoring {self.flipper_id}, logging to {self.output_file}")

    def stop(self):
        """Stop monitoring."""
        self.running = False
        if self.thread:
            self.thread.join()
        if self.serial:
            self.serial.close()
        logger.info(f"Monitoring stopped for {self.flipper_id}")

    def _monitor(self):
        while self.running:
            if not self.serial:
                try:
                    self.serial = serial.Serial(self.device_path, 230400, timeout=1)
                    logger.info(f"Connected to {self.flipper_id} at {self.device_path}")
                except serial.SerialException as e:
                    logger.error(f"Failed to connect to {self.flipper_id}: {e}")
                    time.sleep(5)
                    continue

            try:
                if self.serial.in_waiting:
                    line = self.serial.readline().decode("utf-8", errors="replace")
                    if line:
                        # Clean control characters
                        line = re.sub(r"[\x00-\x1F\x7F-\x9F]", "", line)
                        datetime_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S,%f")
                        log_line = f"{datetime_str} {line}\n"

                        # Write to file
                        with open(self.output_file, 'a') as f:
                            f.write(log_line)

                        # Print to console if not empty
                        if line.strip():
                            print(log_line.strip())

            except serial.SerialException as e:
                logger.error(f"Serial connection error for {self.flipper_id}: {e}")
                self.serial = None
                time.sleep(5)


def main():
    parser = ArgumentParser(description="Serial Monitor for Flipper")
    parser.add_argument("flipper_id", help="Flipper device ID")
    parser.add_argument("--run-level", choices=['REPAIR', 'NORMAL'], default='NORMAL',
                        help="Run level (default: NORMAL)")
    parser.add_argument("-o", "--output", required=True,
                        help="Output log file path")
    args = parser.parse_args()

    monitor = SerialMonitor(
        flipper_id=args.flipper_id,
        output_file=args.output,
        run_level=args.run_level
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
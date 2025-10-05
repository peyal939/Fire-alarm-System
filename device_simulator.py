"""Fire Alarm Device Simulator (Modified for 0–55 smoke range)
--------------------------------------------------------------
Changes:
- smoke range limited to 0–55
- most of the time values <49
- if smoke ≥50, the next message for that device:
  - waits 60s before sending
  - ensures smoke <49
"""

from __future__ import annotations
import argparse
import os
import random
import signal
import sys
import time
from dataclasses import dataclass, field
from typing import List
import json

try:
    import paho.mqtt.client as mqtt  # type: ignore
except ImportError:
    print("paho-mqtt not installed. Install with: pip install paho-mqtt", file=sys.stderr)
    sys.exit(1)

# Default configuration
DEFAULT_BROKER = os.environ.get("MQTT_BROKER", "152.42.179.228")
DEFAULT_PORT = int(os.environ.get("MQTT_PORT", "1885"))
DEFAULT_TOPIC = os.environ.get("MQTT_TOPIC", "aps/fire/data")
DEFAULT_USER = os.environ.get("MQTT_USER", "apsIoT")
DEFAULT_PASS = os.environ.get("MQTT_PASS", "apsIoT25")

STOP_REQUESTED = False


def handle_sigint(signum, frame):
    global STOP_REQUESTED
    STOP_REQUESTED = True
    print("\nStopping simulator...", flush=True)


signal.signal(signal.SIGINT, handle_sigint)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="APS Fire Alarm Device Simulator")
    parser.add_argument("--devices", type=int, default=1, help="Number of simulated devices")
    parser.add_argument("--device-prefix", default="aPsF100", help="Device ID prefix")
    parser.add_argument("--interval", type=float, default=5.0, help="Seconds between publishes per device")
    parser.add_argument("--broker", default=DEFAULT_BROKER, help="MQTT broker host")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="MQTT broker port")
    parser.add_argument("--topic", default=DEFAULT_TOPIC, help="MQTT topic to publish to")
    parser.add_argument("--user", default=DEFAULT_USER, help="MQTT username")
    parser.add_argument("--password", default=DEFAULT_PASS, help="MQTT password")
    parser.add_argument("--alert-probability", type=float, default=0.15, help="Probability that status != 'alive'")
    parser.add_argument("--dry-run", action="store_true", help="Print messages instead of publishing")
    parser.add_argument("--once", action="store_true", help="Publish only one batch then exit")
    return parser.parse_args()


@dataclass
class Device:
    device_id: str
    cooldown: bool = field(default=False)  # If True, next value must be <49

    def generate(self, *, alert_probability: float):
        """Generate one smoke reading with realistic distribution and cooldown logic."""
        if self.cooldown:
            # Force recovery value <49
            smoke = random.randint(0, 48)
            self.cooldown = False
            trigger_delay = 0
        else:
            # Weighted random: 90% chance of 0–49, 10% chance of 50–55
            if random.random() < 0.9:
                smoke = random.randint(0, 49)
            else:
                smoke = random.randint(50, 55)

            # If spike detected, mark cooldown and delay 1 minute
            trigger_delay = 60 if smoke >= 50 else 0
            if smoke >= 50:
                self.cooldown = True

        status = "alive" if random.random() > alert_probability else "alert"

        return {
            "deviceID": self.device_id,
            "timestamp": int(time.time()),
            "smoke": smoke,
            "status": status,
            "_delay": trigger_delay,  # internal use only
        }

    @staticmethod
    def to_payload(d: dict) -> str:
        clean = {k: v for k, v in d.items() if k != "_delay"}
        return json.dumps(clean, separators=(",", ":"))


def build_devices(count: int, prefix: str) -> List[Device]:
    return [Device(f"{prefix}{i+1}") for i in range(count)]


def connect_client(args: argparse.Namespace) -> mqtt.Client:
    client = mqtt.Client()
    if args.user:
        client.username_pw_set(args.user, args.password)
    try:
        client.connect(args.broker, args.port, 60)
    except Exception as e:
        print(f"Failed to connect to MQTT broker {args.broker}:{args.port} -> {e}", file=sys.stderr)
        if not args.dry_run:
            sys.exit(2)
    return client


def main():
    args = parse_args()
    devices = build_devices(args.devices, args.device_prefix)

    client = None
    if not args.dry_run:
        client = connect_client(args)
    else:
        print("[DRY-RUN] Not connecting to broker; messages will be printed only")

    print(f"Simulating {len(devices)} device(s) -> topic '{args.topic}' (interval {args.interval}s)")

    while not STOP_REQUESTED:
        start_time = time.time()
        max_delay = 0
        for dev in devices:
            sample = dev.generate(alert_probability=args.alert_probability)
            payload = Device.to_payload(sample)
            ts = time.strftime("%H:%M:%S")

            if args.dry_run:
                print(f"{ts} {payload}")
            else:
                try:
                    assert client is not None
                    client.publish(args.topic, payload)
                    print(f"{ts} published: {payload}")
                except Exception as e:
                    print(f"Publish failed for {payload}: {e}", file=sys.stderr)

            max_delay = max(max_delay, sample["_delay"])

        if args.once:
            break

        # Wait 60s if any device triggered a spike; otherwise, normal interval
        sleep_for = max(args.interval, max_delay)
        elapsed = time.time() - start_time
        time.sleep(max(0, sleep_for - elapsed))

    print("Simulator stopped.")


if __name__ == "__main__":
    main()

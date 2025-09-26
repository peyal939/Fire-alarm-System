"""Fire Alarm Device Simulator

This script simulates one or multiple APS fire alarm IoT devices by publishing
MQTT messages that match the new JSON format expected by the FastAPI app.

Message format (JSON string):
{
    "deviceID": "aPsF1001",
    "timestamp": 1758543971,
    "smoke": 2,
    "status": "alive"
}

Notes:
- latitude/longitude are NOT included in the MQTT payload anymore.
- The backend will enrich messages with map coordinates for display.

Usage examples:
    # Single device, default settings
    python device_simulator.py

    # Three devices publishing every 2 seconds
    python device_simulator.py --devices 3 --interval 2

    # Custom MQTT broker & topic
    python device_simulator.py --broker 127.0.0.1 --port 1883 --topic aps/fire/data

    # Preview messages without publishing
    python device_simulator.py --dry-run

Press Ctrl+C to stop.
"""

from __future__ import annotations
import argparse
import os
import random
import signal
import sys
import time
from dataclasses import dataclass
from typing import List
import json

try:
    import paho.mqtt.client as mqtt  # type: ignore
except ImportError:  # Helpful message if dependency missing
    print(
        "paho-mqtt not installed. Install with: pip install paho-mqtt", file=sys.stderr
    )
    sys.exit(1)

# Default values reused from app.py (keep in sync if changed)
DEFAULT_BROKER = os.environ.get("MQTT_BROKER", "152.42.179.228")
DEFAULT_PORT = int(os.environ.get("MQTT_PORT", "1885"))
DEFAULT_TOPIC = os.environ.get("MQTT_TOPIC", "aps/fire/data")
DEFAULT_USER = os.environ.get("MQTT_USER", "apsIoT")
DEFAULT_PASS = os.environ.get("MQTT_PASS", "apsIoT25")

STOP_REQUESTED = False


def handle_sigint(signum, frame):  # noqa: D401
    global STOP_REQUESTED
    STOP_REQUESTED = True
    print("\nStopping simulator...", flush=True)


signal.signal(signal.SIGINT, handle_sigint)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="APS Fire Alarm Device Simulator")
    parser.add_argument(
        "--devices", type=int, default=1, help="Number of simulated devices"
    )
    parser.add_argument("--device-prefix", default="DEV", help="Device ID prefix")
    parser.add_argument(
        "--interval",
        type=float,
        default=5.0,
        help="Seconds between publishes per device",
    )
    parser.add_argument("--broker", default=DEFAULT_BROKER, help="MQTT broker host")
    parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT, help="MQTT broker port"
    )
    parser.add_argument(
        "--topic", default=DEFAULT_TOPIC, help="MQTT topic to publish to"
    )
    parser.add_argument("--user", default=DEFAULT_USER, help="MQTT username")
    parser.add_argument("--password", default=DEFAULT_PASS, help="MQTT password")
    parser.add_argument(
        "--smoke-max", type=int, default=1024, help="Maximum smoke value (0..N)"
    )
    parser.add_argument(
        "--alert-probability",
        type=float,
        default=0.15,
        help="Probability that status != 'alive'",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print messages instead of publishing"
    )
    parser.add_argument(
        "--once", action="store_true", help="Publish only one batch then exit"
    )
    return parser.parse_args()


@dataclass
class Device:
    device_id: str

    def generate(self, *, smoke_max: int, alert_probability: float):
        smoke = random.randint(0, max(0, smoke_max))
        status = "alive" if random.random() > alert_probability else "alert"
        return {
            "deviceID": self.device_id,
            "timestamp": int(time.time()),
            "smoke": smoke,
            "status": status,
        }

    @staticmethod
    def to_payload(d: dict) -> str:
        return json.dumps(d, separators=(",", ":"))


def build_devices(count: int, prefix: str) -> List[Device]:
    return [Device(f"{prefix}{i+1}") for i in range(count)]


def connect_client(args: argparse.Namespace) -> mqtt.Client:
    client = mqtt.Client()
    if args.user:
        client.username_pw_set(args.user, args.password)
    try:
        client.connect(args.broker, args.port, 60)
    except Exception as e:
        print(
            f"Failed to connect to MQTT broker {args.broker}:{args.port} -> {e}",
            file=sys.stderr,
        )
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

    print(
        f"Simulating {len(devices)} device(s) -> topic '{args.topic}' (interval {args.interval}s)"
    )

    while not STOP_REQUESTED:
        start_time = time.time()
        for dev in devices:
            sample = dev.generate(
                smoke_max=args.smoke_max,
                alert_probability=args.alert_probability,
            )
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
        if args.once:
            break
        elapsed = time.time() - start_time
        sleep_for = max(0, args.interval - elapsed)
        time.sleep(sleep_for)

    print("Simulator stopped.")


if __name__ == "__main__":  # pragma: no cover
    main()

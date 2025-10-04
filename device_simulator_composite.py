"""
Composite Master/Slaves Device Simulator

Publishes a composite payload where a master periodically sends its own reading
plus an array of slave readings. This matches the backend composite format.

Master: aPsF1001
Slaves: aPsF1001-S1, aPsF1001-S2

Behavior:
- Every 5 seconds publish one composite payload.
- At each tick, randomly choose who is above threshold (none, master, S1, or S2).
- Threshold considered by the backend is 50; we generate values 0..100.

Usage:
  python device_simulator_composite.py --dry-run
  python device_simulator_composite.py --broker <host> --port 1883 --topic aps/fire/data

Env defaults (aligns with backend):
  MQTT_BROKER, MQTT_PORT, MQTT_TOPIC, MQTT_USER, MQTT_PASS
"""

from __future__ import annotations
import argparse
import os
import random
import signal
import sys
import time
import json
from typing import Tuple, List, Dict, Any

try:
    import paho.mqtt.client as mqtt  # type: ignore
except ImportError:
    print("paho-mqtt not installed. Install with: pip install paho-mqtt", file=sys.stderr)
    sys.exit(1)

# ====================== Defaults ======================
DEFAULT_BROKER = os.environ.get("MQTT_BROKER", "152.42.179.228")
DEFAULT_PORT = int(os.environ.get("MQTT_PORT", "1885"))
DEFAULT_TOPIC = os.environ.get("MQTT_TOPIC", "aps/fire/data")
DEFAULT_USER = os.environ.get("MQTT_USER", "apsIoT")
DEFAULT_PASS = os.environ.get("MQTT_PASS", "apsIoT25")

MASTER_ID = "aPsF1001"
SLAVE_IDS = ["aPsF1001-S1", "aPsF1001-S2"]
THRESHOLD = 50

STOP_REQUESTED = False


# ====================== Signal Handling ======================
def handle_sigint(signum, frame):
    global STOP_REQUESTED
    STOP_REQUESTED = True
    print("\nStopping composite simulator...", flush=True)


signal.signal(signal.SIGINT, handle_sigint)


# ====================== CLI Args ======================
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="APS Composite Fire Alarm Simulator")
    p.add_argument("--interval", type=float, default=5.0, help="Seconds between publishes")
    p.add_argument("--broker", default=DEFAULT_BROKER)
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--topic", default=DEFAULT_TOPIC)
    p.add_argument("--user", default=DEFAULT_USER)
    p.add_argument("--password", default=DEFAULT_PASS)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--once", action="store_true")
    return p.parse_args()


# ====================== MQTT Setup ======================
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


# ====================== Device Logic ======================
def pick_above_threshold() -> Tuple[bool, bool, bool]:
    """Randomly decide who is above threshold among (master, s1, s2)."""
    choice = random.choice(["none", "s1", "s2", "master"])  # equally likely
    return (
        choice == "master",
        choice == "s1",
        choice == "s2",
    )


def build_payload() -> Tuple[Dict[str, Any], bool]:
    """Build one composite payload for master and slaves.

    Returns:
        tuple[payload_dict, bool_high_detected]
    """
    ts = int(time.time())
    m_over, s1_over, s2_over = pick_above_threshold()

    def val(over: bool) -> int:
        return (
            random.randint(THRESHOLD + 1, THRESHOLD + 40)
            if over
            else random.randint(0, THRESHOLD)
        )

    payload = {
        "masterDeviceID": MASTER_ID,
        "timestamp": ts,
        "smoke": val(m_over),
        "status": "alive",
        "slaves": [
            {
                "deviceID": SLAVE_IDS[0],
                "timestamp": ts,
                "smoke": val(s1_over),
                "status": "alive",
            },
            {
                "deviceID": SLAVE_IDS[1],
                "timestamp": ts,
                "smoke": val(s2_over),
                "status": "alive",
            },
        ],
    }

    # High detected if any reading exceeds threshold
    high_detected = any(
        v > THRESHOLD for v in [
            payload["smoke"],
            payload["slaves"][0]["smoke"],
            payload["slaves"][1]["smoke"],
        ]
    )

    return payload, high_detected


# ====================== Main Loop ======================
def main():
    args = parse_args()
    client = None
    if not args.dry_run:
        client = connect_client(args)
    else:
        print("[DRY-RUN] Not connecting to broker; messages will be printed only")

    print(
        f"Composite sim: master {MASTER_ID} with slaves {SLAVE_IDS} "
        f"-> topic '{args.topic}' (interval {args.interval}s)"
    )

    while not STOP_REQUESTED:
        start = time.time()
        payload, high = build_payload()
        out = json.dumps(payload, separators=(",", ":"))
        ts = time.strftime("%H:%M:%S")

        if args.dry_run:
            flag = "⚠️ HIGH" if high else "✅ OK"
            print(f"{ts} {flag} {out}")
        else:
            try:
                assert client is not None
                client.publish(args.topic, out)
                flag = "⚠️" if high else "✅"
                print(f"{ts} {flag} published: {out}")
            except Exception as e:
                print(f"Publish failed: {e}", file=sys.stderr)

        if args.once:
            break

        elapsed = time.time() - start
        time.sleep(max(0, args.interval - elapsed))

    print("Composite simulator stopped.")


if __name__ == "__main__":
    main()

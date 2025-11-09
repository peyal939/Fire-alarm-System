import logging
import signal
import time

from django.core.management.base import BaseCommand

from realtime.mqtt import ensure_mqtt_thread, get_mqtt_status

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Start the MQTT ingestion worker as a standalone long-running process."

    def add_arguments(self, parser):
        parser.add_argument(
            "--poll-interval",
            type=float,
            default=5.0,
            help="Seconds between health polls while idling (default: 5).",
        )

    def handle(self, *args, **options):
        poll_interval: float = max(float(options["poll_interval"]), 0.5)
        stop_requested = False

        def _signal_handler(signum, _frame):
            nonlocal stop_requested
            logger.info("Received signal %s; requesting graceful shutdown", signum)
            stop_requested = True

        signal.signal(signal.SIGINT, _signal_handler)
        signal.signal(signal.SIGTERM, _signal_handler)

        logger.info("Bootstrapping MQTT ingestion worker")
        ensure_mqtt_thread()
        self.stdout.write(self.style.SUCCESS("MQTT ingestion thread started"))

        while not stop_requested:
            time.sleep(poll_interval)
            status = get_mqtt_status()
            if not status.get("connected"):
                logger.warning(
                    "MQTT not connected (last error: %s)", status.get("error")
                )

        logger.info("MQTT ingestion worker exiting")
        self.stdout.write("Shutting down MQTT ingestion worker...")

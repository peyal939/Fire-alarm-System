"""Django management command to check and diagnose database connection issues.

Usage:
    python manage.py check_db_connections
    python manage.py check_db_connections --kill-sleeping
"""

from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = "Check MySQL database connection status and optionally kill sleeping connections"

    def add_arguments(self, parser):
        parser.add_argument(
            "--kill-sleeping",
            action="store_true",
            help="Kill connections that have been sleeping for more than 5 minutes",
        )
        parser.add_argument(
            "--sleep-threshold",
            type=int,
            default=300,
            help="Threshold in seconds for considering a connection as stale (default: 300)",
        )

    def handle(self, *args, **options):
        kill_sleeping = options.get("kill_sleeping", False)
        sleep_threshold = options.get("sleep_threshold", 300)

        self.stdout.write(self.style.NOTICE("Checking database connection status...\n"))

        with connection.cursor() as cursor:
            # Check max connections setting
            cursor.execute("SHOW VARIABLES LIKE 'max_connections'")
            row = cursor.fetchone()
            max_connections = int(row[1]) if row else "Unknown"
            self.stdout.write(f"Max connections: {max_connections}")

            # Check current connections count
            cursor.execute("SHOW STATUS LIKE 'Threads_connected'")
            row = cursor.fetchone()
            current_connections = int(row[1]) if row else "Unknown"
            self.stdout.write(f"Current connections: {current_connections}")

            # Calculate usage percentage
            if isinstance(max_connections, int) and isinstance(current_connections, int):
                usage_pct = (current_connections / max_connections) * 100
                if usage_pct > 80:
                    self.stdout.write(
                        self.style.ERROR(f"Connection usage: {usage_pct:.1f}% - CRITICAL!")
                    )
                elif usage_pct > 60:
                    self.stdout.write(
                        self.style.WARNING(f"Connection usage: {usage_pct:.1f}% - Warning")
                    )
                else:
                    self.stdout.write(
                        self.style.SUCCESS(f"Connection usage: {usage_pct:.1f}% - OK")
                    )

            self.stdout.write("\n" + "-" * 50)
            self.stdout.write("Connection breakdown by user:\n")

            # Get connection breakdown by user
            cursor.execute("""
                SELECT user, COUNT(*) as count, 
                       SUM(CASE WHEN command = 'Sleep' THEN 1 ELSE 0 END) as sleeping
                FROM information_schema.processlist 
                GROUP BY user
                ORDER BY count DESC
            """)
            for row in cursor.fetchall():
                self.stdout.write(f"  {row[0]}: {row[1]} total, {row[2]} sleeping")

            self.stdout.write("\n" + "-" * 50)
            self.stdout.write("Sleeping connections (older than 60 seconds):\n")

            # List sleeping connections
            cursor.execute("""
                SELECT id, user, host, db, command, time, state
                FROM information_schema.processlist 
                WHERE command = 'Sleep' AND time > 60
                ORDER BY time DESC
                LIMIT 20
            """)
            sleeping_connections = cursor.fetchall()
            
            if sleeping_connections:
                for row in sleeping_connections:
                    self.stdout.write(
                        f"  ID: {row[0]}, User: {row[1]}, Host: {row[2]}, "
                        f"DB: {row[3]}, Time: {row[5]}s"
                    )
            else:
                self.stdout.write(self.style.SUCCESS("  No long-sleeping connections found"))

            # Kill sleeping connections if requested
            if kill_sleeping:
                self.stdout.write("\n" + "-" * 50)
                self.stdout.write(
                    self.style.WARNING(
                        f"Killing connections sleeping for more than {sleep_threshold} seconds...\n"
                    )
                )

                cursor.execute(f"""
                    SELECT id FROM information_schema.processlist 
                    WHERE command = 'Sleep' AND time > {sleep_threshold}
                    AND user != 'system user'
                """)
                ids_to_kill = [row[0] for row in cursor.fetchall()]

                killed_count = 0
                for conn_id in ids_to_kill:
                    try:
                        cursor.execute(f"KILL {conn_id}")
                        killed_count += 1
                        self.stdout.write(f"  Killed connection ID: {conn_id}")
                    except Exception as e:
                        self.stdout.write(
                            self.style.WARNING(f"  Failed to kill {conn_id}: {e}")
                        )

                self.stdout.write(
                    self.style.SUCCESS(f"\nKilled {killed_count} sleeping connections")
                )

            self.stdout.write("\n" + "-" * 50)
            self.stdout.write(self.style.NOTICE("\nRecommendations:"))
            
            if isinstance(current_connections, int) and isinstance(max_connections, int):
                if current_connections > max_connections * 0.8:
                    self.stdout.write(self.style.ERROR(
                        "1. URGENT: Increase max_connections in MySQL:\n"
                        "   SET GLOBAL max_connections = 300;\n"
                        "   Or add to /etc/mysql/mysql.conf.d/mysqld.cnf:\n"
                        "   max_connections = 300"
                    ))
                    self.stdout.write(self.style.WARNING(
                        "2. Restart Daphne/Gunicorn/Celery workers to release connections"
                    ))
                    self.stdout.write(self.style.WARNING(
                        "3. Run: python manage.py check_db_connections --kill-sleeping"
                    ))

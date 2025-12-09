from __future__ import annotations

import os

from celery import Celery
from celery.signals import task_prerun, task_postrun

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("config")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


@task_prerun.connect
def close_old_connections_before_task(**kwargs):
    """Close old database connections before each task.
    
    This helps prevent 'Too many connections' errors by ensuring
    stale connections are cleaned up before reuse.
    """
    from django.db import close_old_connections
    close_old_connections()


@task_postrun.connect
def close_old_connections_after_task(**kwargs):
    """Close database connections after each task completes.
    
    This ensures connections are released back to the pool
    and not left hanging after task completion.
    """
    from django.db import close_old_connections
    close_old_connections()

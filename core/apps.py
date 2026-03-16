import logging
import os

from django.apps import AppConfig
from django.conf import settings
from django.utils import timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'
    scheduler = None

    def ready(self):
        # Prevent scheduler from running in sub-processes created by Django autoreload
        if os.environ.get('RUN_MAIN') != 'true':
            return

        if not getattr(settings, 'RUN_APSCHEDULER', True):
            logger.info('APScheduler disabled via RUN_APSCHEDULER=False')
            return

        if CoreConfig.scheduler and CoreConfig.scheduler.running:
            return

        try:
            from core.services.shift_packet_scheduler import process_incident_shift_schedules

            scheduler = BackgroundScheduler(timezone=settings.TIME_ZONE)
            scheduler.add_job(
                process_incident_shift_schedules,
                trigger=IntervalTrigger(minutes=5),
                id='core_incident_shift_packet_scheduler',
                name='Incident shift packet scheduler every 5 minutes',
                replace_existing=True,
                next_run_time=timezone.now(),
            )
            scheduler.start()
            CoreConfig.scheduler = scheduler
            logger.info('Shift packet scheduler started (every 5 minutes).')

        except Exception:
            logger.exception('Failed to start shift packet scheduler in AppConfig.ready()')



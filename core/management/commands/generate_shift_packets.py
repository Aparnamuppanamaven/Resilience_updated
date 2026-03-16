from __future__ import annotations

"""
Management command to generate AI-based shift packets on a schedule.

Intended usage (from Windows Task Scheduler or cron equivalent):

    python manage.py generate_shift_packets

This command:
  - Looks at IncidentShiftSchedule to find incidents with configured shift_hours
  - Determines the last shift packet time per incident
  - Fetches new SituationUpdate rows since that time
  - Uses AI to generate:
        input_summary, what_changed, why_it_matters, decision
  - Creates a new ShiftPacket and a corresponding ShiftPacketHistory row
"""

from django.core.management.base import BaseCommand

from core.services.shift_packet_scheduler import run_scheduler_once


class Command(BaseCommand):
    help = "Generate AI-based shift packets for incidents with active shift schedules."

    def handle(self, *args, **options):
        run_scheduler_once()
        self.stdout.write(self.style.SUCCESS("Shift packet scheduler run completed."))


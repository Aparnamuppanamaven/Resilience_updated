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

import random
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction

from core.ai_shift import IncidentContext, generate_shift_packet_ai_summary
from core.models import (
    Incident,
    IncidentShiftSchedule,
    ShiftPacket,
    ShiftPacketHistory,
    SituationUpdate,
)


class Command(BaseCommand):
    help = "Generate AI-based shift packets for incidents with active shift schedules."

    def handle(self, *args, **options):
        now = timezone.now()
        schedules = IncidentShiftSchedule.objects.select_related("incident").all()

        if not schedules:
            self.stdout.write(self.style.WARNING("No incident shift schedules found. Nothing to do."))
            return

        for schedule in schedules:
            incident = schedule.incident

            # Determine last packet time for this incident from history or packets
            last_history = (
                ShiftPacketHistory.objects.filter(incident=incident)
                .order_by("-created_at")
                .first()
            )
            last_packet_time = last_history.created_at if last_history else incident.timestamp

            due_at = last_packet_time + timedelta(hours=schedule.shift_hours)
            if now < due_at:
                continue

            # Collect situation updates since last packet time
            situation_updates = list(
                SituationUpdate.objects.filter(
                    incident__id=incident.id,
                    update_time__gt=last_packet_time,
                ).order_by("update_time")
            )

            # If there is nothing new, we can optionally skip, but we still
            # allow a packet so cadence is visible. You can change this rule.
            last_packet = (
                ShiftPacket.objects.filter(organization=incident.organization)
                .order_by("-generated_at")
                .first()
            )

            ctx = IncidentContext(
                incident=incident,
                last_packet=last_packet,
                situation_updates=situation_updates,
            )

            ai_result = generate_shift_packet_ai_summary(ctx)

            with transaction.atomic():
                packet_number = f"PKT-{incident.id}-{random.randint(1000, 9999)}-{now.strftime('%Y%m%d%H%M')}"

                packet = ShiftPacket.objects.create(
                    organization=incident.organization,
                    packet_number=packet_number,
                    # Some legacy incidents may have NULL status; default to 'Open'
                    status=incident.status or "Open",
                    executive_summary=ai_result["input_summary"] or "No summary generated.",
                    key_risks=ai_result["why_it_matters"] or "",
                    next_actions=ai_result["decision_summary"] or "",
                    what_happened=ai_result["what_changed"] or "",
                    next_steps=ai_result["decision_summary"] or "",
                    tx_type="AI",
                    sent_at=now,
                )

                ShiftPacketHistory.objects.create(
                    shiftpacket=packet,
                    incident=incident,
                    incident_uid=getattr(incident, "incident_uid", None),
                    input="Auto-generated from incident + situation updates.",
                    what_happened=ai_result["what_changed"] or "",
                    next_steps=ai_result["decision_summary"] or "",
                    tx_type="AI",
                    input_summary=ai_result["input_summary"],
                    what_changed=ai_result["what_changed"],
                    why_it_matters=ai_result["why_it_matters"],
                    decision_summary=ai_result["decision_summary"],
                    decision_maker=ai_result["decision_maker"],
                    decision_time=ai_result["decision_time"],
                )

                self.stdout.write(
                    self.style.SUCCESS(
                        f"Generated AI shift packet {packet_number} for incident {incident.id}"
                    )
                )


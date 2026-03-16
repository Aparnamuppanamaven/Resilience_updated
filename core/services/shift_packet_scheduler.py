import logging
import random
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from core.ai_shift import IncidentContext, generate_shift_packet_ai_summary
from core.models import (
    IncidentCapture,
    IncidentShiftSchedule,
    IncidentEvent,
    ShiftPacket,
    ShiftPacketHistory,
    ShiftPacketSchedulerLog,
    SituationUpdate,
)

logger = logging.getLogger(__name__)


def process_incident_shift_schedules():
    """Process one pass of incident shift schedule and generate shift packets."""
    now = timezone.now()
    next_scheduled = now + timedelta(minutes=5)

    schedules = IncidentShiftSchedule.objects.select_related("incident", "incident__organization").all()
    if not schedules:
        logger.info("No incident shift schedules found for scheduler run.")
        return

    for schedule in schedules:
        incident = schedule.incident
        incident_capture = None
        core_incident_id = None

        if getattr(incident, 'incident_uid', None) is not None:
            incident_capture = IncidentCapture.objects.filter(incident_uid=incident.incident_uid).first()
            if incident_capture is not None:
                core_incident_id = incident_capture.id

        try:
            # Active incident check
            if incident.status == "Resolved":
                ShiftPacketSchedulerLog.objects.create(
                    incident=incident,
                    capture_incident=incident_capture,
                    triggered_at=now,
                    next_scheduled=next_scheduled,
                    schedule_status="generated",
                    message=f"capture_incident_id={core_incident_id} Incident {incident.id} is resolved; skipping generation.",
                )
                continue

            # Determine when a packet was last generated for this incident.
            last_history = (
                ShiftPacketHistory.objects.filter(incident=incident)
                .order_by("-created_at")
                .first()
            )
            last_packet_time = last_history.created_at if last_history else incident.timestamp
            due_at = last_packet_time + timedelta(hours=schedule.shift_hours)

            if now < due_at:
                # Skip logging when packet is not due yet.
                continue

            situation_updates = list(
                SituationUpdate.objects.filter(
                    incident__id=incident.id,
                    update_time__gt=last_packet_time,
                ).order_by("update_time")
            )

            incident_events = list(
                IncidentEvent.objects.filter(
                    incident=incident,
                ).order_by("created_time")
            )

            last_packet = (
                ShiftPacket.objects.filter(organization=incident.organization)
                .order_by("-generated_at")
                .first()
            )

            ctx = IncidentContext(
                incident=incident,
                last_packet=last_packet,
                situation_updates=situation_updates,
                incident_events=incident_events,
            )

            ai_result = generate_shift_packet_ai_summary(ctx)

            with transaction.atomic():
                packet_number = f"PKT-{incident.id}-{random.randint(1000, 9999)}-{now.strftime('%Y%m%d%H%M')}"

                packet = ShiftPacket.objects.create(
                    organization=incident.organization,
                    packet_number=packet_number,
                    status=incident.status or "Open",
                    executive_summary=ai_result.get("input_summary") or "No summary generated.",
                    key_risks=ai_result.get("why_it_matters") or "",
                    next_actions=ai_result.get("decision_summary") or "",
                    what_happened=ai_result.get("what_changed") or "",
                    next_steps=ai_result.get("decision_summary") or "",
                    tx_type="AI",
                    sent_at=now,
                )

                ShiftPacketHistory.objects.create(
                    shiftpacket=packet,
                    incident=incident,
                    incident_uid=getattr(incident, "incident_uid", None),
                    input="Auto-generated from incident + situation updates",
                    what_happened=ai_result.get("what_changed") or "",
                    next_steps=ai_result.get("decision_summary") or "",
                    tx_type="AI",
                    input_summary=ai_result.get("input_summary"),
                    what_changed=ai_result.get("what_changed"),
                    why_it_matters=ai_result.get("why_it_matters"),
                    decision_summary=ai_result.get("decision_summary"),
                    decision_maker=ai_result.get("decision_maker"),
                    decision_time=ai_result.get("decision_time"),
                )

                ShiftPacketSchedulerLog.objects.create(
                    incident=incident,
                    capture_incident=incident_capture,
                    triggered_at=now,
                    next_scheduled=next_scheduled,
                    schedule_status="generated",
                    message=f"capture_incident_id={core_incident_id} Generated packet {packet.packet_number} successfully.",
                )

                logger.info("Generated shift packet %s for incident %s", packet.packet_number, incident.id)

        except Exception as err:
            logger.exception("Scheduler error for incident %s", getattr(incident, 'id', 'unknown'))
            try:
                ShiftPacketSchedulerLog.objects.create(
                    incident=incident,
                    capture_incident=incident_capture,
                    triggered_at=now,
                    next_scheduled=next_scheduled,
                    schedule_status="failed",
                    message=f"capture_incident_id={core_incident_id} {str(err)}",
                )
            except Exception:
                logger.exception("Failed to write scheduler log for incident %s", getattr(incident, 'id', 'unknown'))


def run_scheduler_once():
    """Helper for manual invocation from management command or tests."""
    process_incident_shift_schedules()  # pragma: no cover

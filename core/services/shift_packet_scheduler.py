import logging
import random
from datetime import timedelta

from django.db import transaction, OperationalError
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


def _log_shift_packet_generated_event(incident, packet_number, generated_at, shift_hours):
    """
    Single user-facing incident event when a shift packet is actually generated.

    Technical scheduler audit (every poll, failures, etc.) lives in
    ShiftPacketSchedulerLog (System Logs), not in core_incident_events.
    """
    if incident is None or not packet_number:
        return
    message = (
        f"Shift packet {packet_number} was auto-generated for this incident. "
        f"Next packet is scheduled after {shift_hours} hour(s) of operational time."
    )
    IncidentEvent.objects.create(
        incident=incident,
        event_desc=message,
        created_time=generated_at,
    )


def _create_scheduler_log(incident, incident_capture, triggered_at, next_scheduled, schedule_status, message):
    """
    Write a scheduler log row.

    IMPORTANT for your requirement:
    - We store the ID from core_incidents (IncidentCapture) in the incident_id column.
      This is done by passing the IncidentCapture instance to the 'incident' field.
    - We no longer reference any non‑existent capture_incident_id column.
    """
    # If we have a matching IncidentCapture, use it; otherwise we skip logging
    if incident_capture is None:
        return

    # Legacy audit log table (core_shiftpacket_scheduler_log)
    try:
        ShiftPacketSchedulerLog.objects.create(
            incident=incident_capture,
            triggered_at=triggered_at,
            next_scheduled=next_scheduled,
            schedule_status=schedule_status,
            message=message,
        )
    except OperationalError:
        # If legacy table is not present or mismatched, we don't want to break
        # the scheduler; the primary log for product behavior is IncidentEvent.
        logger.warning("ShiftPacketSchedulerLog write failed", exc_info=True)


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
                _create_scheduler_log(
                    incident=incident,
                    incident_capture=incident_capture,
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
            # IMPORTANT:
            # - For the very first run we use the incident timestamp as the
            #   "last packet" time (no packets yet).
            # - For subsequent runs we always base the schedule on the last
            #   packet generation time so that intervals stay correct.
            last_packet_time = last_history.created_at if last_history else incident.timestamp
            due_at = last_packet_time + timedelta(hours=schedule.shift_hours)

            if now < due_at:
                # Not yet due — no row in core_incident_events (avoids spamming the
                # situational / incident events UI). Audit trail is optional via logger.
                logger.debug(
                    "Shift packet not due for incident %s until %s",
                    incident.id,
                    due_at.isoformat(),
                )
                continue

            # SituationUpdate is linked to IncidentCapture (core_incidents), not the
            # normalized Incident (core_operationalupdate). Use incident_capture.id
            # so updates are correctly counted and included in AI context.
            situation_updates = []
            if incident_capture is not None:
                situation_updates = list(
                    SituationUpdate.objects.filter(
                        incident_id=incident_capture.id,
                        update_time__gt=last_packet_time,
                    ).order_by("update_time")
                )

            incident_events = list(
                IncidentEvent.objects.filter(incident=incident)
                .exclude(event_desc__startswith="[SCHEDULER]")
                .order_by("created_time")
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

                # User-visible event: one line per actual packet generation.
                _log_shift_packet_generated_event(
                    incident=incident,
                    packet_number=packet.packet_number,
                    generated_at=now,
                    shift_hours=schedule.shift_hours,
                )

                _create_scheduler_log(
                    incident=incident,
                    incident_capture=incident_capture,
                    triggered_at=now,
                    next_scheduled=next_scheduled,
                    schedule_status="generated",
                    message=f"capture_incident_id={core_incident_id} Generated packet {packet.packet_number} successfully.",
                )

                logger.info("Generated shift packet %s for incident %s", packet.packet_number, incident.id)

        except Exception as err:
            logger.exception("Scheduler error for incident %s", getattr(incident, 'id', 'unknown'))
            try:
                _create_scheduler_log(
                    incident=incident,
                    incident_capture=incident_capture,
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

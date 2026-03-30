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

# Status values stored in schedule_status (legacy: generated / failed still supported for old rows)
STATUS_RUNNING = "RUNNING"
STATUS_SUCCESS = "SUCCESS"
STATUS_FAILED = "FAILED"


def _log_shift_packet_generated_event(incident, packet_number, generated_at, shift_hours):
    """
    Single user-facing incident event when a shift packet is actually generated.

    Technical scheduler audit lives in ShiftPacketSchedulerLog (System Logs).
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


def _finalize_stale_running_logs(incident_capture):
    """
    If a previous run crashed after creating RUNNING, close those rows so we do not
    accumulate duplicate RUNNING entries.
    """
    if incident_capture is None:
        return
    try:
        now = timezone.now()
        ShiftPacketSchedulerLog.objects.filter(
            incident=incident_capture,
            schedule_status=STATUS_RUNNING,
        ).update(
            schedule_status=STATUS_FAILED,
            next_scheduled=now,
            message="(Recovered) RUNNING did not complete; closed before new shift run.",
        )
    except OperationalError:
        logger.warning("ShiftPacketSchedulerLog stale cleanup failed", exc_info=True)


def _create_running_log(incident_capture, started_at):
    """Single audit row per shift execution: start of processing."""
    return ShiftPacketSchedulerLog.objects.create(
        incident=incident_capture,
        triggered_at=started_at,
        next_scheduled=started_at,
        schedule_status=STATUS_RUNNING,
        message="Shift packet generation started.",
    )


def _complete_scheduler_log_success(log_row, ended_at, message):
    ShiftPacketSchedulerLog.objects.filter(pk=log_row.pk).update(
        next_scheduled=ended_at,
        schedule_status=STATUS_SUCCESS,
        message=message,
    )


def _complete_scheduler_log_failed(log_row, ended_at, message):
    ShiftPacketSchedulerLog.objects.filter(pk=log_row.pk).update(
        next_scheduled=ended_at,
        schedule_status=STATUS_FAILED,
        message=message[:2000] if message else "",
    )


def _create_failure_only_log(incident_capture, ended_at, message):
    """
    Used when we cannot create a RUNNING row first (should be rare).
    Inserts a FAILED row as an additional diagnostic entry.
    """
    try:
        ShiftPacketSchedulerLog.objects.create(
            incident=incident_capture,
            triggered_at=ended_at,
            next_scheduled=ended_at,
            schedule_status=STATUS_FAILED,
            message=(message or "")[:2000],
        )
    except OperationalError:
        logger.warning("ShiftPacketSchedulerLog failure row write failed", exc_info=True)


def process_incident_shift_schedules():
    """Process one pass of incident shift schedule and generate shift packets."""
    now = timezone.now()

    schedules = IncidentShiftSchedule.objects.select_related("incident", "incident__organization").all()
    if not schedules:
        logger.info("No incident shift schedules found for scheduler run.")
        return

    for schedule in schedules:
        incident = schedule.incident
        incident_capture = None
        core_incident_id = None
        run_log = None

        if getattr(incident, "incident_uid", None) is not None:
            incident_capture = IncidentCapture.objects.filter(incident_uid=incident.incident_uid).first()
            if incident_capture is not None:
                core_incident_id = incident_capture.id

        try:
            if incident.status == "Resolved":
                # No audit row on skip (avoids 5-minute spam for resolved incidents)
                continue

            last_history = (
                ShiftPacketHistory.objects.filter(incident=incident).order_by("-created_at").first()
            )
            last_packet_time = last_history.created_at if last_history else incident.timestamp
            due_at = last_packet_time + timedelta(hours=schedule.shift_hours)

            if now < due_at:
                logger.debug(
                    "Shift packet not due for incident %s until %s",
                    incident.id,
                    due_at.isoformat(),
                )
                continue

            if incident_capture is None:
                logger.warning(
                    "Shift packet due for incident %s but no IncidentCapture; skipping.",
                    incident.id,
                )
                continue

            _finalize_stale_running_logs(incident_capture)
            run_log = _create_running_log(incident_capture, now)

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
                ShiftPacket.objects.filter(organization=incident.organization).order_by("-generated_at").first()
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

                _log_shift_packet_generated_event(
                    incident=incident,
                    packet_number=packet.packet_number,
                    generated_at=now,
                    shift_hours=schedule.shift_hours,
                )

            ended = timezone.now()
            _complete_scheduler_log_success(
                run_log,
                ended,
                f"capture_incident_id={core_incident_id} Generated packet {packet.packet_number} successfully.",
            )
            logger.info("Generated shift packet %s for incident %s", packet.packet_number, incident.id)

        except Exception as err:
            logger.exception("Scheduler error for incident %s", getattr(incident, "id", "unknown"))
            try:
                if run_log is not None:
                    _complete_scheduler_log_failed(
                        run_log,
                        timezone.now(),
                        f"capture_incident_id={core_incident_id} {str(err)}",
                    )
                elif incident_capture is not None:
                    _create_failure_only_log(
                        incident_capture,
                        timezone.now(),
                        f"capture_incident_id={core_incident_id} {str(err)}",
                    )
            except Exception:
                logger.exception("Failed to update scheduler log for incident %s", getattr(incident, "id", "unknown"))


def run_scheduler_once():
    """Helper for manual invocation from management command or tests."""
    process_incident_shift_schedules()  # pragma: no cover

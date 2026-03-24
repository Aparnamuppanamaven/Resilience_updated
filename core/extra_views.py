"""
UI-only views for new pages (Situation Updates, Shift Packets, Reports,
System Logs, User Management) that match the existing Resilience layout.

These do NOT persist data yet – they are meant for front-end review only.
"""

from datetime import timedelta
import json
from io import BytesIO
from pathlib import Path

from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.template.loader import render_to_string
from django.utils import timezone
from django.urls import reverse
from django.contrib.auth.models import User
from django.core.files.storage import default_storage
from django.utils.text import get_valid_filename

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
from reportlab.lib.enums import TA_LEFT

from django.contrib.auth.models import User
from django.db.models import Q

from .models import (
    Incident,
    IncidentCapture,
    IncidentEvent,
    IncidentShiftSchedule,
    OperationalUpdate,
    ShiftPacket,
    ShiftPacketHistory,
    ShiftPacketSchedulerLog,
    SystemSettings,
    Organization,
    TxLog,
    UserCredentials,
    Liaison,
    UsersTable,
)


def _get_org_and_status(request):
    """
    Resolve organization and system status for header display.
    Mirrors the logic used in existing dashboard/incidents_list views.
    """
    organization = None

    if request.user.is_authenticated:
        try:
            liaison = request.user.liaison_profile
            organization = liaison.organization
        except Exception:
            organization = None
    elif "user_credentials_id" in request.session:
        try:
            organization = Organization.objects.first()
        except Exception:
            organization = None

    settings_obj, _created = SystemSettings.objects.get_or_create(
        organization=organization,
        defaults={
            "current_status": "Normal",
            "cadence_hours": 24,
        },
    )

    last_sync = settings_obj.last_sync
    now = timezone.now()
    time_diff = now - last_sync

    if time_diff < timedelta(minutes=1):
        sync_time_display = "Just now"
    elif time_diff < timedelta(hours=1):
        minutes = int(time_diff.total_seconds() / 60)
        sync_time_display = f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    elif time_diff < timedelta(days=1):
        hours = int(time_diff.total_seconds() / 3600)
        sync_time_display = f"{hours} hour{'s' if hours != 1 else ''} ago"
    else:
        sync_time_display = last_sync.strftime("%b %d, %Y at %I:%M %p")

    return organization, settings_obj.current_status, sync_time_display


def _require_auth(request):
    """Redirect to login if neither Django auth nor legacy session is present."""
    if not request.user.is_authenticated and "user_credentials_id" not in request.session:
        return redirect("login")
    return None


def _normalize_county(value):
    if value is None:
        return ""
    return str(value).strip().casefold()


def _county_for_incident_capture(incident):
    if not incident:
        return ""
    try:
        cb = getattr(incident, "created_by", None)
        if cb is not None:
            c = getattr(cb, "county", None) or ""
            if _normalize_county(c):
                return _normalize_county(c)
    except Exception:
        pass
    try:
        org = getattr(incident, "organization", None)
        if org is not None:
            li = Liaison.objects.filter(organization=org).exclude(county__exact="").first()
            if li:
                return _normalize_county(li.county)
    except Exception:
        pass
    return ""


def _county_for_users_table(ut):
    if not ut:
        return ""
    for email in (ut.email_id, ut.liaison_email):
        if not email:
            continue
        li = Liaison.objects.filter(user__email__iexact=email.strip()).first()
        if li:
            return _normalize_county(li.county or "")
    return ""


def _legacy_users_table_row(request):
    if not request.session.get("user_credentials_id"):
        return None
    uname = (request.session.get("user_credentials_username") or "").strip()
    if not uname:
        return None
    return UsersTable.objects.filter(
        Q(primary_liaison_name__iexact=uname)
        | Q(liaison_email__iexact=uname)
        | Q(email_id__iexact=uname)
    ).first()


def _county_for_request_user(request):
    if request.user.is_authenticated:
        try:
            li = request.user.liaison_profile
            c = _normalize_county(getattr(li, "county", "") or "")
            if c:
                return c
        except Exception:
            pass
    ut = _legacy_users_table_row(request)
    if ut is not None:
        return _county_for_users_table(ut)
    return ""


def _user_can_access_incident_capture(request, incident):
    if not incident:
        return False
    inc_c = _county_for_incident_capture(incident)
    user_c = _county_for_request_user(request)
    if inc_c:
        if not user_c:
            return False
        return inc_c == user_c
    # Fallback if incident county is unavailable: preserve existing org behavior.
    if request.user.is_authenticated:
        try:
            li = request.user.liaison_profile
            lo_id = getattr(li, "organization_id", None) or getattr(
                getattr(li, "organization", None), "pk", None
            )
            return lo_id is not None and int(incident.organization_id) == int(lo_id)
        except Exception:
            return False
    ut = _legacy_users_table_row(request)
    if ut is not None:
        try:
            emails = Liaison.objects.filter(organization=incident.organization).values_list(
                "user__email", flat=True
            )
            em = {e.strip().lower() for e in emails if e}
            for e in (ut.email_id, ut.liaison_email):
                if e and e.strip().lower() in em:
                    return True
        except Exception:
            return False
    return False


def _filter_incidents_by_county(request, incidents):
    return [inc for inc in incidents if _user_can_access_incident_capture(request, inc)]


def situation_updates_page(request):
    """
    UI-only Situation Updates page.
    Shows:
    - Incident selector
    - Add Situation Update form (no backend persistence yet)
    - Sample Situation Logs table
    """
    auth_redirect = _require_auth(request)
    if auth_redirect:
        return auth_redirect

    organization, current_status, last_sync_display = _get_org_and_status(request)

    if request.method == "POST":
        incident_id = request.POST.get("incident_id")
        try:
            incident = IncidentCapture.objects.get(id=incident_id)
        except (IncidentCapture.DoesNotExist, ValueError, TypeError):
            incident = None
        if incident is not None and not _user_can_access_incident_capture(request, incident):
            incident = None

        from django.utils import timezone
        from datetime import datetime

        raw_update_time = request.POST.get("update_time") or ""
        parsed_update_time = None
        if raw_update_time:
            try:
                # HTML5 datetime-local: "YYYY-MM-DDTHH:mm" (or with seconds)
                parsed_update_time = datetime.fromisoformat(raw_update_time)
            except ValueError:
                # Legacy UI format: DD-MM-YYYY HH:MM
                try:
                    parsed_update_time = datetime.strptime(raw_update_time, "%d-%m-%Y %H:%M")
                    parsed_update_time = timezone.make_aware(
                        parsed_update_time, timezone.get_current_timezone()
                    )
                except ValueError:
                    parsed_update_time = timezone.now()
            if parsed_update_time is not None and timezone.is_naive(parsed_update_time):
                parsed_update_time = timezone.make_aware(
                    parsed_update_time, timezone.get_current_timezone()
                )
        else:
            parsed_update_time = timezone.now()

        from .models import SituationUpdate

        if incident:
            # SituationUpdate.attachments is a CharField in this project.
            # Persist the uploaded file to MEDIA and store a relative media path.
            attachments_value = request.POST.get("attachments") or ""
            try:
                uploaded_files = request.FILES.getlist("attachments_file")
                if uploaded_files:
                    first_file = uploaded_files[0]
                    original_name = Path(first_file.name).name
                    safe_name = get_valid_filename(original_name)
                    timestamp_prefix = timezone.now().strftime("%Y%m%d%H%M%S")
                    rel_path = (
                        f"situation_updates/{incident.id}/{timestamp_prefix}_{safe_name}"
                    )
                    saved_path = default_storage.save(rel_path, first_file)
                    attachments_value = str(saved_path).replace("\\", "/")[:100]
            except Exception:
                pass

            SituationUpdate.objects.create(
                incident=incident,
                title=request.POST.get("situationupdate_title") or "",
                description=request.POST.get("situationupdate_description") or "",
                update_time=parsed_update_time,
                reported_by=request.POST.get("reported_by") or "",
                department=request.POST.get("department") or "",
                severity_change=request.POST.get("severity_change") or "",
                status_change=request.POST.get("status_change") or "",
                casualties_injured=(
                    int(request.POST.get("casualties_injured"))
                    if request.POST.get("casualties_injured")
                    else None
                ),
                casualties_dead=(
                    int(request.POST.get("casualties_dead"))
                    if request.POST.get("casualties_dead")
                    else None
                ),
                affected_area=request.POST.get("affected_area") or "",
                actions_taken=request.POST.get("actions_taken") or "",
                resources_deployed=request.POST.get("resources_deployed") or "",
                next_steps=request.POST.get("next_steps") or "",
                confidence_level=request.POST.get("confidence_level") or "",
                attachments=attachments_value,
                created_at=parsed_update_time,
                tenant_id=getattr(organization, "tenant_id", None),
            )

            from .models import log_system_action

            actionby_id = getattr(request.user, "id", None)
            # If no Django auth user is attached, fall back to legacy UserCredentials id
            if actionby_id is None:
                actionby_id = request.session.get("user_credentials_id")
            log_system_action(
                tenant_id=getattr(organization, "tenant_id", None),
                entity="SituationUpdate",
                actionby=actionby_id,
                actionon=f"{incident.id}:{request.POST.get('situationupdate_title') or ''}",
                action="Create",
            )

            from django.contrib import messages
            from django.shortcuts import redirect

            messages.success(request, "Situation update added successfully.")
            # After adding an update, reload page with this incident selected so its updates show
            return redirect(f"{reverse('situation_updates')}?incident_id={incident.id}")

    incidents = IncidentCapture.objects.all().order_by("-reported_time")[:50]
    incidents = _filter_incidents_by_county(request, list(incidents))

    # Load distinct department categories for the Department/Sub Department dropdowns
    from .models import Department
    department_categories = (
        Department.objects.values_list("category", flat=True)
        .distinct()
        .order_by("category")
    )

    # If an incident is selected (via query param), load its situation updates
    selected_incident = None
    situation_updates = []
    incident_id_param = request.GET.get("incident_id")
    if incident_id_param:
        try:
            selected_incident = IncidentCapture.objects.get(id=incident_id_param)
            if not _user_can_access_incident_capture(request, selected_incident):
                raise IncidentCapture.DoesNotExist
            from .models import SituationUpdate

            situation_updates = list(
                SituationUpdate.objects.filter(incident=selected_incident).order_by("-update_time")
            )
            for item in situation_updates:
                raw_attachments = (item.attachments or "").strip()
                item.attachment_links = [
                    path.strip()
                    for path in raw_attachments.split(",")
                    if path and path.strip()
                ]
        except (IncidentCapture.DoesNotExist, ValueError, TypeError):
            selected_incident = None
            situation_updates = []

    context = {
        "organization": organization,
        "current_status": current_status,
        "last_sync_display": last_sync_display,
        "incidents": incidents,
        "selected_incident": selected_incident,
        "situation_updates": situation_updates,
        "department_categories": department_categories,
    }
    return render(request, "core/situation_updates.html", context)


def _ensure_incident_for_capture(capture: IncidentCapture, organization: Organization) -> Incident:
    """
    Ensure there is an Incident (core_operationalupdate) representing this
    captured incident. If none exists, create a simple one from the capture.
    """
    uid = capture.incident_uid or capture.id
    if capture.incident_uid is None:
        capture.incident_uid = uid
        capture.save(update_fields=["incident_uid"])

    incident, _created = Incident.objects.get_or_create(
        organization=organization,
        incident_uid=uid,
        defaults={
            "title": capture.title,
            "description": capture.description or "",
            "severity": capture.severity or "LOW",
            "impact": capture.impact or "",
            "next_action": "",
            "status": "Open",
            "owner": None,
            "is_synthesized": False,
            "tenant_id": capture.tenant_id,
        },
    )
    return incident


def shift_packets_page(request):
    """
    UI-only Shift Packets page.
    Shows incident selector, shift cadence configuration, and
    a table of actual shift packet history entries (AI/manual).
    """
    auth_redirect = _require_auth(request)
    if auth_redirect:
        return auth_redirect

    organization, current_status, last_sync_display = _get_org_and_status(request)
    # Use capture incidents for the dropdown, but map them to Incident for scheduling/history
    incidents = IncidentCapture.objects.all().order_by("-reported_time")[:50]
    incidents = _filter_incidents_by_county(request, list(incidents))
    selected_incident_capture = None
    selected_incident = None
    incident_id_param = request.GET.get("incident_id")
    history_entries = []
    current_schedule = None

    if incident_id_param:
        try:
            selected_incident_capture = IncidentCapture.objects.get(id=incident_id_param)
            if not _user_can_access_incident_capture(request, selected_incident_capture):
                raise IncidentCapture.DoesNotExist
            selected_incident = _ensure_incident_for_capture(selected_incident_capture, organization)
        except (IncidentCapture.DoesNotExist, ValueError, TypeError):
            selected_incident_capture = None
            selected_incident = None

    # Handle cadence selection POST
    if request.method == "POST":
        incident_id = request.POST.get("incident_id")
        shift_hours = request.POST.get("shift_hours")

        if incident_id and shift_hours:
            try:
                capture_obj = IncidentCapture.objects.get(id=incident_id)
                if not _user_can_access_incident_capture(request, capture_obj):
                    capture_obj = None
                    raise IncidentCapture.DoesNotExist
                incident_obj = _ensure_incident_for_capture(capture_obj, organization)
                shift_hours_int = int(shift_hours)
            except (IncidentCapture.DoesNotExist, ValueError, TypeError):
                incident_obj = None
                shift_hours_int = None

            if incident_obj is not None and shift_hours_int is not None:
                IncidentShiftSchedule.objects.update_or_create(
                    incident=incident_obj,
                    defaults={
                        "shift_hours": shift_hours_int,
                        "created_by": request.user.id if request.user.is_authenticated else 0,
                        "incident_uid": incident_obj.incident_uid,
                    },
                )
                # Redirect with the same capture incident selected so history reloads
                return redirect(f"{reverse('shift_packets')}?incident_id={capture_obj.id}")

    # Load existing schedule and history for the selected capture incident
    if selected_incident_capture:
        selected_incident = _ensure_incident_for_capture(selected_incident_capture, organization)
        current_schedule = IncidentShiftSchedule.objects.filter(
            incident_uid=selected_incident.incident_uid
        ).first()
        history_entries = list(
            ShiftPacketHistory.objects.filter(incident_uid=selected_incident.incident_uid)
            .order_by("-created_at")[:50]
        )

        # Derive shift window:
        # - End time  = current history row created_at
        # - Start time = previous (older) history row created_at
        # Since history_entries is sorted newest -> oldest (descending created_at),
        # the previous shift packet time is the next item in the loop.
        for i, entry in enumerate(history_entries):
            if i + 1 < len(history_entries):
                entry.start_time = history_entries[i + 1].created_at
            else:
                entry.start_time = None

    context = {
        "organization": organization,
        "current_status": current_status,
        "last_sync_display": last_sync_display,
        "incidents": incidents,
        "selected_incident": selected_incident_capture,
        "history_entries": history_entries,
        "current_schedule": current_schedule,
        "allowed_shift_hours": [1, 2, 3, 4, 6, 8, 10, 12, 18, 24, 48, 72],
    }
    return render(request, "core/shift_packets.html", context)


def edit_shift_packet_history(request, history_id: int):
    """
    Allow manual editing of a single ShiftPacketHistory entry.

    Behaviour:
    - User can edit the narrative fields shown on the Shift Packet cards.
    - When edited, tx_type is set to 'MANUAL' so the UI badge shows MANUAL
      instead of AI.
    - All edits are stored in core_shiftpacket_history only.
    """
    auth_redirect = _require_auth(request)
    if auth_redirect:
        return auth_redirect

    organization, current_status, last_sync_display = _get_org_and_status(request)

    history = get_object_or_404(ShiftPacketHistory, id=history_id)

    # Resolve capture incident so we can link back to the Shift Packets page
    capture_incident = (
        IncidentCapture.objects.filter(incident_uid=history.incident_uid).first()
        if history.incident_uid
        else None
    )

    if request.method == "POST":
        history.input_summary = request.POST.get("input_summary", history.input_summary or "")
        history.what_changed = request.POST.get("what_changed", history.what_changed or "")
        history.why_it_matters = request.POST.get("why_it_matters", history.why_it_matters or "")
        history.decision_summary = request.POST.get("decision_summary", history.decision_summary or "")
        history.decision_maker = request.POST.get("decision_maker", history.decision_maker or "")

        # Mark as MANUAL once a human has edited the entry
        history.tx_type = "MANUAL"
        if request.user.is_authenticated:
            history.updated_by = request.user.id

        history.save()

        if capture_incident:
            return redirect(f"{reverse('shift_packets')}?incident_id={capture_incident.id}")
        return redirect("shift_packets")

    context = {
        "organization": organization,
        "current_status": current_status,
        "last_sync_display": last_sync_display,
        "history": history,
        "capture_incident": capture_incident,
    }
    return render(request, "core/shift_packet_edit.html", context)


def _reports_counts_for_capture(capture: IncidentCapture):
    """Situation logs (core_incident_events) and shift packet history rows for this capture."""
    try:
        logs = IncidentEvent.objects.filter(incident_id=capture.id).count()
    except Exception:
        logs = 0
    uid = capture.incident_uid if capture.incident_uid is not None else capture.id
    try:
        packets = ShiftPacketHistory.objects.filter(incident_uid=uid).count()
    except Exception:
        packets = 0
    return logs, packets


def _reports_summary_text(inc: IncidentCapture) -> str:
    """Plain-text narrative from stored incident fields (no external AI service)."""
    lines = []
    if inc.title:
        lines.append(f"Title: {inc.title}")
    sev = inc.get_severity_display() if hasattr(inc, "get_severity_display") else (inc.severity or "")
    if sev:
        lines.append(f"Severity: {str(sev).strip()}")
    if inc.status:
        lines.append(f"Status: {inc.status}")
    if inc.reported_time:
        lines.append(f"Reported: {inc.reported_time.strftime('%b %d, %Y %I:%M %p')}")
    if inc.location:
        lines.append(f"Location: {inc.location}")
    if inc.category or inc.sub_category:
        cat = " / ".join(x for x in (inc.category or "", inc.sub_category or "") if x)
        if cat.strip():
            lines.append(f"Category: {cat.strip()}")
    if inc.description and str(inc.description).strip():
        lines.append("")
        lines.append("Description:")
        lines.append(str(inc.description).strip())
    if inc.impact and str(inc.impact).strip():
        lines.append("")
        lines.append("Impact / why it matters:")
        lines.append(str(inc.impact).strip())
    return "\n".join(lines) if lines else "No additional detail is available for this incident."


def _build_report_context(request):
    """
    Shared helper for the Reports page and PDF generation.

    Incidents are scoped like Incident Management (org filter for liaison users).
    Preview uses ?incident_id= when present (must be in the visible list).
    If no incident is selected, preview remains empty and the UI shows placeholders.
    Metrics for the tiles are per selected incident; total_situation_logs remains a global count.
    """
    organization, current_status, last_sync_display = _get_org_and_status(request)

    liaison = None
    if request.user.is_authenticated:
        try:
            liaison = request.user.liaison_profile
        except Exception:
            liaison = None

    if liaison is not None and organization is not None:
        incidents_qs = IncidentCapture.objects.filter(organization=organization).order_by(
            "-reported_time"
        )[:50]
    else:
        incidents_qs = IncidentCapture.objects.all().order_by("-reported_time")[:50]

    incidents = _filter_incidents_by_county(request, list(incidents_qs))
    visible_ids = {i.id for i in incidents}
    for inc in incidents:
        lc, pc = _reports_counts_for_capture(inc)
        inc.reports_logs_count = lc
        inc.reports_packets_count = pc

    incident_id_param = request.GET.get("incident_id")
    preview_incident = None
    if incident_id_param:
        try:
            cand = IncidentCapture.objects.get(id=int(incident_id_param))
            if cand.id in visible_ids:
                preview_incident = cand
        except (IncidentCapture.DoesNotExist, ValueError, TypeError):
            preview_incident = None

    if preview_incident is None:
        incident_situation_logs = 0
        incident_shift_packets = 0
        report_summary_text = ""
    else:
        incident_situation_logs, incident_shift_packets = _reports_counts_for_capture(preview_incident)
        report_summary_text = _reports_summary_text(preview_incident)

    try:
        # "Situation logs" for Reports should exclude internal scheduler noise AND
        # shift-packet generation system events.
        total_situation_logs = (
            IncidentEvent.objects.exclude(event_desc__icontains="[SCHEDULER]")
            .exclude(event_desc__icontains="was auto-generated for this incident")
            .count()
        )
    except Exception:
        total_situation_logs = 0

    try:
        total_shift_packets = ShiftPacket.objects.count()
    except Exception:
        total_shift_packets = 0

    context = {
        "organization": organization,
        "current_status": current_status,
        "last_sync_display": last_sync_display,
        "incidents": incidents,
        "preview_incident": preview_incident,
        "incident_situation_logs": incident_situation_logs,
        "incident_shift_packets": incident_shift_packets,
        "report_summary_text": report_summary_text,
        "total_situation_logs": total_situation_logs,
        "total_shift_packets": total_shift_packets,
    }
    return context


def api_reports_incident(request):
    """
    JSON detail for Reports page when user selects an incident (same scoping as incident list).
    """
    if request.method != "GET":
        return JsonResponse({"error": "Method not allowed"}, status=405)

    auth_redirect = _require_auth(request)
    if auth_redirect:
        return JsonResponse({"error": "Unauthorized"}, status=401)

    organization, _, _ = _get_org_and_status(request)
    liaison = None
    if request.user.is_authenticated:
        try:
            liaison = request.user.liaison_profile
        except Exception:
            pass

    if liaison is not None and organization is not None:
        visible = IncidentCapture.objects.filter(organization=organization)
    else:
        visible = IncidentCapture.objects.all()
    visible_ids = {i.id for i in _filter_incidents_by_county(request, list(visible))}

    incident_id = request.GET.get("incident_id")
    if not incident_id:
        return JsonResponse({"error": "incident_id required"}, status=400)
    try:
        inc = IncidentCapture.objects.get(id=int(incident_id))
    except (ValueError, TypeError, IncidentCapture.DoesNotExist):
        return JsonResponse({"error": "Incident not found"}, status=404)

    if inc.id not in visible_ids:
        return JsonResponse({"error": "Incident not found"}, status=404)

    logs, packets = _reports_counts_for_capture(inc)
    summary = _reports_summary_text(inc)
    sev = inc.get_severity_display() if hasattr(inc, "get_severity_display") else (inc.severity or "")
    return JsonResponse(
        {
            "id": inc.id,
            "title": inc.title or "",
            "severity_display": str(sev).strip(),
            "incident_situation_logs": logs,
            "incident_shift_packets": packets,
            "report_summary_text": summary,
        }
    )


def reports_page(request):
    """
    Reports page.
    Lets the user pick an incident and see a summary/AI narrative preview.
    """
    auth_redirect = _require_auth(request)
    if auth_redirect:
        return auth_redirect

    context = _build_report_context(request)
    return render(request, "core/reports.html", context)


def reports_pdf(request):
    """
    Generate a PDF snapshot of the current Report Preview and AI summary.
    Uses ReportLab only (no WeasyPrint) so it works cross‑platform
    without native GTK/Pango dependencies.
    """
    auth_redirect = _require_auth(request)
    if auth_redirect:
        return auth_redirect

    context = _build_report_context(request)
    buffer = BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
    )

    styles = getSampleStyleSheet()
    body_style = styles["BodyText"]
    body_style.alignment = TA_LEFT
    title_style = styles["Heading1"]
    subtitle_style = styles["Heading3"]

    story = []

    # Title
    story.append(Paragraph("Incident Summary Report", title_style))
    story.append(Spacer(1, 0.2 * inch))

    # Organization / status
    org = context.get("organization")
    org_name = getattr(org, "name", "Resilience System")
    current_status = context.get("current_status") or "NORMAL"
    story.append(Paragraph(f"Organization: {org_name}", body_style))
    story.append(Paragraph(f"Current Status: {current_status}", body_style))
    story.append(Spacer(1, 0.2 * inch))

    # Incident overview
    preview_incident = context.get("preview_incident")
    story.append(Spacer(1, 0.05 * inch))
    if preview_incident:
        story.append(Paragraph(f"<b>ID:</b> INC-{preview_incident.id}", body_style))
        story.append(Paragraph(f"<b>Title:</b> {preview_incident.title}", body_style))
        desc = getattr(preview_incident, "description", "") or ""
        if desc:
            story.append(Paragraph(f"<b>Description:</b> {desc}", body_style))
    else:
        story.append(Paragraph("<b>ID:</b> —", body_style))
        story.append(Paragraph("<b>Title:</b> —", body_style))
        story.append(Paragraph("<b>Description:</b> —", body_style))
    story.append(Spacer(1, 0.2 * inch))

    isl = context.get("incident_situation_logs", 0)
    isp = context.get("incident_shift_packets", 0)
    story.append(Paragraph("Metrics (selected incident)", subtitle_style))
    story.append(Spacer(1, 0.1 * inch))
    story.append(Paragraph(f"Situation logs for this incident: {isl}", body_style))
    story.append(Paragraph(f"Shift packet history rows for this incident: {isp}", body_style))

    total_situation_logs = context.get("total_situation_logs", 0)
    total_shift_packets = context.get("total_shift_packets", 0)
    story.append(Spacer(1, 0.1 * inch))
    story.append(Paragraph("System-wide totals", subtitle_style))
    story.append(Spacer(1, 0.08 * inch))
    story.append(Paragraph(f"Total situation log entries (all incidents): {total_situation_logs}", body_style))
    story.append(Paragraph(f"Total shift packet records (all): {total_shift_packets}", body_style))

    summary = (context.get("report_summary_text") or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    if summary:
        story.append(Spacer(1, 0.2 * inch))
        story.append(Paragraph("Summary", subtitle_style))
        story.append(Spacer(1, 0.08 * inch))
        for line in summary.split("\n"):
            if line.strip():
                story.append(Paragraph(line, body_style))

    story.append(Spacer(1, 0.3 * inch))
    story.append(
        Paragraph(
            "This PDF is a compact summary for quick sharing. "
            "For full interactive details, use the web dashboard Incident Reports view.",
            body_style,
        )
    )

    doc.build(story)

    pdf_bytes = buffer.getvalue()
    buffer.close()

    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = 'inline; filename=\"incident_report_summary.pdf\"'
    return response


def system_logs_page(request):
    """
    System Logs page backed by TxLog table.
    """
    auth_redirect = _require_auth(request)
    if auth_redirect:
        return auth_redirect

    organization, current_status, last_sync_display = _get_org_and_status(request)

    # Fetch latest system logs from TxLog.
    # If organization/tenant context exists, filter by that tenant_id; otherwise, show recent global logs.
    logs_qs = TxLog.objects.all()
    if organization is not None:
        tenant_id = getattr(organization, "tenant_id", None) or getattr(organization, "pk", None)
        if tenant_id is not None:
            logs_qs = logs_qs.filter(tenant_id=tenant_id)

    logs = list(logs_qs.order_by("-created_date")[:200])

    # Build maps of user_id -> username from both auth User and legacy UserCredentials
    actionby_ids = {log.actionby for log in logs if log.actionby is not None}
    usercred_map = {
        u["user_id"]: u["username"]
        for u in UserCredentials.objects.filter(user_id__in=actionby_ids).values("user_id", "username")
    }
    authuser_map = {
        u["id"]: u["username"]
        for u in User.objects.filter(id__in=actionby_ids).values("id", "username")
    }

    # Adapt to template shape: expose action_by as username (fallback to id string)
    enriched_logs = []
    for log in logs:
        action_by_display = ""
        if log.actionby is not None:
            # Prefer username from legacy UserCredentials (for historical rows),
            # otherwise fall back to Django auth user, then raw id.
            action_by_display = usercred_map.get(
                log.actionby,
                authuser_map.get(log.actionby, str(log.actionby)),
            )

        enriched_logs.append(
            {
                "id": log.id,
                "tenant_id": log.tenant_id,
                "entity": log.entity,
                "action_by": action_by_display,
                "action": log.action,
                "created_date": log.created_date,
            }
        )

    scheduler_logs = []
    try:
        for row in ShiftPacketSchedulerLog.objects.select_related("incident").order_by(
            "-triggered_at"
        )[:200]:
            inc = row.incident
            cap_label = f"INC-{inc.id}" if inc else "—"
            scheduler_logs.append(
                {
                    "run_id": row.run_id,
                    "incident_label": cap_label,
                    "triggered_at": row.triggered_at,
                    "next_scheduled": row.next_scheduled,
                    "schedule_status": row.schedule_status,
                    "message": (row.message or "")[:500],
                }
            )
    except Exception:
        scheduler_logs = []

    context = {
        "organization": organization,
        "current_status": current_status,
        "last_sync_display": last_sync_display,
        "logs": enriched_logs,
        "scheduler_logs": scheduler_logs,
    }
    return render(request, "core/system_logs.html", context)


def user_management_page(request):
    """
    UI-only User Management page.
    Shows a simple user creation form and an Agency User Counter table.
    """
    auth_redirect = _require_auth(request)
    if auth_redirect:
        return auth_redirect

    organization, current_status, last_sync_display = _get_org_and_status(request)

    sample_agencies = [
        {
            "agency_id": "AG-2001",
            "admin_user_id": "admin@county.gov",
            "allowed": 25,
            "current": 18,
        },
        {
            "agency_id": "AG-2002",
            "admin_user_id": "admin@city.gov",
            "allowed": 15,
            "current": 15,
        },
        {
            "agency_id": "AG-2003",
            "admin_user_id": "admin@health.org",
            "allowed": 10,
            "current": 7,
        },
    ]

    context = {
        "organization": organization,
        "current_status": current_status,
        "last_sync_display": last_sync_display,
        "agencies": sample_agencies,
    }
    return render(request, "core/user_management.html", context)


def api_situation_logs(request):
    """
    API endpoint to fetch situation logs as JSON.
    Used by the Reports page to display logs in a modal.
    Optional: ?incident_id=<core_incidents.id> filters to that capture incident.
    """
    auth_redirect = _require_auth(request)
    if auth_redirect:
        return JsonResponse({'error': 'Unauthorized'}, status=401)

    try:
        # Reports "View Situation Logs" should show Situation Updates (core_situation_updates)
        # for the selected capture incident.
        incident_id = request.GET.get("incident_id")
        if not incident_id:
            return JsonResponse(
                {"logs": [], "total": 0, "error": "Please select an incident."},
                status=400,
            )

        capture_incident = IncidentCapture.objects.filter(id=incident_id).first()
        if capture_incident is None:
            return JsonResponse(
                {"logs": [], "total": 0, "error": "Selected incident not found."},
                status=404,
            )
        if not _user_can_access_incident_capture(request, capture_incident):
            return JsonResponse(
                {"logs": [], "total": 0, "error": "Access denied: Cross-county operations are not permitted"},
                status=403,
            )

        from .models import SituationUpdate

        qs = SituationUpdate.objects.filter(incident_id=capture_incident.id).order_by(
            "-update_time"
        )
        total = qs.count()
        updates = list(qs[:200])

        logs_data = []
        for su in updates:
            desc = su.description or su.title or "No description"
            status = su.status_change or "LOGGED"
            logs_data.append(
                {
                    "id": su.id,
                    "timestamp": su.update_time.strftime("%m/%d/%Y %H:%M")
                    if su.update_time
                    else "N/A",
                    "department": su.department or "—",
                    "description": desc,
                    "status": status.upper() if isinstance(status, str) else "LOGGED",
                }
            )
        return JsonResponse({"logs": logs_data, "total": total}, safe=False)
    except Exception as e:
        return JsonResponse({'error': str(e), 'logs': [], 'total': 0}, status=500)


def api_report_summary(request):
    """
    API endpoint used by Reports → "Generate Summary Report".
    Builds a concise incident-specific narrative from Situation Updates.
    """
    auth_redirect = _require_auth(request)
    if auth_redirect:
        return JsonResponse({"error": "Unauthorized"}, status=401)

    try:
        incident_id = request.GET.get("incident_id")
        if not incident_id:
            return JsonResponse({"error": "Please select an incident."}, status=400)

        incident = IncidentCapture.objects.filter(id=incident_id).first()
        if incident is None:
            return JsonResponse({"error": "Selected incident not found."}, status=404)
        if not _user_can_access_incident_capture(request, incident):
            return JsonResponse(
                {"error": "Access denied: Cross-county operations are not permitted"},
                status=403,
            )

        from .models import SituationUpdate

        qs = SituationUpdate.objects.filter(incident_id=incident.id).order_by("-update_time")
        total_updates = qs.count()
        recent = list(qs[:8])

        if not recent:
            paragraphs = [
                "No updates received for this incident during the selected period. Continue monitoring."
            ]
        else:
            latest_time = recent[0].update_time.strftime("%b %d, %Y %H:%M") if recent[0].update_time else "N/A"
            departments = sorted({(su.department or "").strip() for su in recent if (su.department or "").strip()})
            dep_text = ", ".join(departments) if departments else "multiple teams"

            paragraphs = [
                f'Incident "{incident.title}" has {total_updates} recorded situation update(s). Latest update: {latest_time}.',
                f"Recent updates involve {dep_text}. Review the entries below for operational changes and next steps.",
            ]

            # Add a compact digest of recent unique items (avoid dumping raw logs)
            digest = []
            seen = set()
            for su in reversed(recent):  # chronological within the recent window
                text = (su.description or su.title or "").strip()
                if not text:
                    continue
                key = text.lower()
                if key in seen:
                    continue
                seen.add(key)
                digest.append(text)
                if len(digest) >= 5:
                    break

            if digest:
                paragraphs.append("Key recent updates: " + " | ".join(digest) + ".")

        return JsonResponse(
            {
                "incident_id": incident.id,
                "incident_title": incident.title,
                "total_updates": total_updates,
                "paragraphs": paragraphs,
            }
        )
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)

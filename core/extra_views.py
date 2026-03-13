"""
UI-only views for new pages (Situation Updates, Shift Packets, Reports,
System Logs, User Management) that match the existing Resilience layout.

These do NOT persist data yet – they are meant for front-end review only.
"""

from datetime import timedelta
import json
from io import BytesIO

from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect
from django.template.loader import render_to_string
from django.utils import timezone
from django.urls import reverse
from django.contrib.auth.models import User

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
from reportlab.lib.enums import TA_LEFT

from .models import (
    Incident,
    IncidentCapture,
    IncidentEvent,
    IncidentShiftSchedule,
    OperationalUpdate,
    ShiftPacket,
    ShiftPacketHistory,
    SystemSettings,
    Organization,
    TxLog,
    UserCredentials,
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

        from django.utils import timezone
        from datetime import datetime

        raw_update_time = request.POST.get("update_time") or ""
        parsed_update_time = None
        if raw_update_time:
            try:
                parsed_update_time = datetime.fromisoformat(raw_update_time)
            except ValueError:
                parsed_update_time = timezone.now()
        else:
            parsed_update_time = timezone.now()

        from .models import SituationUpdate

        if incident:
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
                attachments=request.POST.get("attachments") or "",
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

    # If an incident is selected (via query param), load its situation updates
    selected_incident = None
    situation_updates = []
    incident_id_param = request.GET.get("incident_id")
    if incident_id_param:
        try:
            selected_incident = IncidentCapture.objects.get(id=incident_id_param)
            from .models import SituationUpdate

            situation_updates = list(
                SituationUpdate.objects.filter(incident=selected_incident).order_by("-update_time")
            )
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
    selected_incident_capture = None
    selected_incident = None
    incident_id_param = request.GET.get("incident_id")
    history_entries = []
    current_schedule = None

    if incident_id_param:
        try:
            selected_incident_capture = IncidentCapture.objects.get(id=incident_id_param)
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


def _build_report_context(request):
    """
    Shared helper for the Reports page and PDF generation.

    Currently uses simple global counts and the most recent incident
    as the preview data source.
    """
    organization, current_status, last_sync_display = _get_org_and_status(request)
    incidents = IncidentCapture.objects.all().order_by("-reported_time")[:50]
    preview_incident = incidents[0] if incidents else None

    # Global counts for situation logs and shift packets
    try:
        total_situation_logs = IncidentEvent.objects.count()
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
        "total_situation_logs": total_situation_logs,
        "total_shift_packets": total_shift_packets,
    }
    return context


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
    story.append(Paragraph("Incident Report Summary", title_style))
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
    if preview_incident:
        story.append(Paragraph("Preview Incident", subtitle_style))
        story.append(Spacer(1, 0.1 * inch))
        story.append(Paragraph(f"ID: INC-{preview_incident.id}", body_style))
        story.append(Paragraph(f"Title: {preview_incident.title}", body_style))
        desc = getattr(preview_incident, "description", "")
        if desc:
            story.append(Paragraph(f"Description: {desc}", body_style))
        story.append(Spacer(1, 0.2 * inch))

    # Situation logs and shift packets counts
    total_situation_logs = context.get("total_situation_logs", 0)
    total_shift_packets = context.get("total_shift_packets", 0)
    story.append(Paragraph("Summary Metrics", subtitle_style))
    story.append(Spacer(1, 0.1 * inch))
    story.append(Paragraph(f"Total Situation Logs: {total_situation_logs}", body_style))
    story.append(Paragraph(f"Total Shift Packets: {total_shift_packets}", body_style))

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

    context = {
        "organization": organization,
        "current_status": current_status,
        "last_sync_display": last_sync_display,
        "logs": enriched_logs,
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
    """
    auth_redirect = _require_auth(request)
    if auth_redirect:
        return JsonResponse({'error': 'Unauthorized'}, status=401)

    try:
        # Fetch incident events (situation logs)
        logs = IncidentEvent.objects.all().order_by('-created_time')[:100]
        
        logs_data = []
        for log in logs:
            department = 'System'
            if log.user_log:
                try:
                    liaison = log.user_log.liaison_profile
                    department = liaison.organization.name if liaison.organization else 'Operations'
                except Exception:
                    department = 'System'
            
            logs_data.append({
                'id': log.id,
                'timestamp': log.created_time.strftime('%m/%d/%Y %H:%M') if log.created_time else 'N/A',
                'department': department,
                'description': log.event_desc or 'No description',
                'status': 'ACTIVE',  # Default status
            })
        
        return JsonResponse({'logs': logs_data, 'total': len(logs_data)}, safe=False)
    except Exception as e:
        return JsonResponse({'error': str(e), 'logs': [], 'total': 0}, status=500)


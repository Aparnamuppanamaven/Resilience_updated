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

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
from reportlab.lib.enums import TA_LEFT

from .models import (
    IncidentCapture,
    IncidentEvent,
    OperationalUpdate,
    ShiftPacket,
    SystemSettings,
    Organization,
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
    incidents = IncidentCapture.objects.all().order_by("-created_at")[:50]

    context = {
        "organization": organization,
        "current_status": current_status,
        "last_sync_display": last_sync_display,
        "incidents": incidents,
    }
    return render(request, "core/situation_updates.html", context)


def shift_packets_page(request):
    """
    UI-only Shift Packets page.
    Shows incident selector and a table of example shift packet entries.
    """
    auth_redirect = _require_auth(request)
    if auth_redirect:
        return auth_redirect

    organization, current_status, last_sync_display = _get_org_and_status(request)
    incidents = IncidentCapture.objects.all().order_by("-created_at")[:50]

    context = {
        "organization": organization,
        "current_status": current_status,
        "last_sync_display": last_sync_display,
        "incidents": incidents,
    }
    return render(request, "core/shift_packets.html", context)


def _build_report_context(request):
    """
    Shared helper for the Reports page and PDF generation.

    Currently uses simple global counts and the most recent incident
    as the preview data source.
    """
    organization, current_status, last_sync_display = _get_org_and_status(request)
    incidents = IncidentCapture.objects.all().order_by("-created_at")[:50]
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
    UI-only System Logs page.
    Currently uses sample data; can later be wired to TxLog model.
    """
    auth_redirect = _require_auth(request)
    if auth_redirect:
        return auth_redirect

    organization, current_status, last_sync_display = _get_org_and_status(request)

    sample_logs = [
        {
            "id": 10432,
            "tenant_id": 2001,
            "entity": "User",
            "action_by": "admin@county.gov",
            "action": "User Login",
            "created_date": "Mar 09, 2026 06:00",
        },
        {
            "id": 10433,
            "tenant_id": 2001,
            "entity": "Incident",
            "action_by": "admin@county.gov",
            "action": "Incident Created",
            "created_date": "Mar 09, 2026 06:05",
        },
        {
            "id": 10434,
            "tenant_id": 2001,
            "entity": "SituationUpdate",
            "action_by": "duty.officer@county.gov",
            "action": "Situation Update Added",
            "created_date": "Mar 09, 2026 06:20",
        },
        {
            "id": 10435,
            "tenant_id": 2001,
            "entity": "ShiftPacket",
            "action_by": "duty.officer@county.gov",
            "action": "Shift Packet Generated",
            "created_date": "Mar 09, 2026 06:25",
        },
    ]

    context = {
        "organization": organization,
        "current_status": current_status,
        "last_sync_display": last_sync_display,
        "logs": sample_logs,
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


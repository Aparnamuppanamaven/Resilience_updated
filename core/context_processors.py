"""Template context processors."""

from django.conf import settings
from django.db.models import Q


def _user_table_image_q(email, username, full_name):
    """Build Q to find core_users row by email or name (liaison_email, email_id, primary_liaison_name)."""
    q = Q()
    if email:
        q = q | Q(liaison_email__iexact=email) | Q(email_id__iexact=email)
    if username:
        q = q | Q(primary_liaison_name__iexact=username)
    if full_name:
        q = q | Q(primary_liaison_name__iexact=full_name)
    return q


def auth_context(request):
    """Add is_admin, sidebar profile image URL, and sidebar display name/org so sidebar is consistent on all pages."""
    data = {
        'is_admin': (
            request.user.is_authenticated
            and getattr(request.user, 'is_staff', False)
        ),
        'sidebar_profile_image_url': None,
        'sidebar_display_name': None,
        'sidebar_organization_name': None,
        'MEDIA_URL': getattr(settings, 'MEDIA_URL', '/media/'),
    }
    # Legacy user: session has user_credentials_id — set display name and org for sidebar on every page
    if request.session.get('user_credentials_id'):
        try:
            from .models import UserCredentials, UsersTable, Organization
            cred = UserCredentials.objects.filter(
                user_id=request.session['user_credentials_id']
            ).first()
            if cred:
                data['sidebar_display_name'] = request.session.get(
                    'user_credentials_username', cred.username
                ) or cred.username
                # Prefer org from first Organization; optionally from UsersTable (agency_name) if matched
                org = Organization.objects.first()
                if org:
                    data['sidebar_organization_name'] = org.name
                q = (
                    Q(liaison_email__iexact=cred.username)
                    | Q(email_id__iexact=cred.username)
                    | Q(primary_liaison_name__iexact=cred.username)
                )
                user_table = UsersTable.objects.filter(q).first()
                if user_table and user_table.agency_name:
                    data['sidebar_organization_name'] = user_table.agency_name
                elif user_table and user_table.primary_liaison_name and not data['sidebar_display_name']:
                    data['sidebar_display_name'] = user_table.primary_liaison_name
        except Exception:
            pass
    # Django auth: set display name and org from user / liaison so every page has same sidebar
    elif getattr(request.user, 'is_authenticated', False) and request.user.is_authenticated:
        try:
            liaison = getattr(request.user, 'liaison_profile', None)
            if liaison and getattr(liaison, 'organization', None):
                data['sidebar_organization_name'] = liaison.organization.name
            name = (getattr(request.user, 'get_full_name', lambda: '')() or '').strip()
            if not name:
                name = (getattr(request.user, 'username', None) or '').strip()
            if name:
                data['sidebar_display_name'] = name
        except Exception:
            pass

    # Legacy user: resolve profile image from core_users by username
    if request.session.get('user_credentials_id'):
        try:
            from .models import UserCredentials, UsersTable
            cred = UserCredentials.objects.filter(
                user_id=request.session['user_credentials_id']
            ).first()
            if cred:
                q = (
                    Q(liaison_email__iexact=cred.username)
                    | Q(email_id__iexact=cred.username)
                    | Q(primary_liaison_name__iexact=cred.username)
                )
                user_table = UsersTable.objects.filter(q).filter(
                    user_image__isnull=False
                ).exclude(user_image='').first()
                if user_table and user_table.user_image:
                    base = (settings.MEDIA_URL or '/media/').rstrip('/')
                    path = (user_table.user_image or '').lstrip('/')
                    if path:
                        rel = f"{base}/{path}"
                        data['sidebar_profile_image_url'] = request.build_absolute_uri(rel)
        except Exception:
            pass
    # Django auth: resolve from core_users (liaison_email, email_id, primary_liaison_name) or liaison.profile_image
    if not data['sidebar_profile_image_url'] and request.user.is_authenticated:
        try:
            from .models import UsersTable
            email = (getattr(request.user, 'email', None) or '').strip()
            username = (getattr(request.user, 'username', None) or '').strip()
            full_name = (getattr(request.user, 'get_full_name', lambda: '')() or '').strip()
            q = _user_table_image_q(email, username, full_name)
            if q:
                user_table = UsersTable.objects.filter(q).filter(
                    user_image__isnull=False
                ).exclude(user_image='').first()
                if user_table and user_table.user_image:
                    base = (settings.MEDIA_URL or '/media/').rstrip('/')
                    path = (user_table.user_image or '').lstrip('/')
                    if path:
                        rel = f"{base}/{path}"
                        data['sidebar_profile_image_url'] = request.build_absolute_uri(rel)
            if not data['sidebar_profile_image_url']:
                liaison = getattr(request.user, 'liaison_profile', None)
                if liaison and getattr(liaison, 'profile_image', None):
                    base = (settings.MEDIA_URL or '/media/').rstrip('/')
                    path = (liaison.profile_image or '').lstrip('/')
                    if path:
                        rel = f"{base}/{path}"
                        data['sidebar_profile_image_url'] = request.build_absolute_uri(rel)
        except Exception:
            pass
    return data

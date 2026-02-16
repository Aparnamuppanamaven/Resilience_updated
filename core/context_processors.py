"""Template context processors."""


def auth_context(request):
    """Add is_admin so sidebar can show Admin link only for staff users."""
    is_admin = (
        request.user.is_authenticated
        and getattr(request.user, 'is_staff', False)
    )
    return {'is_admin': is_admin}

from __future__ import annotations

from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.utils import timezone


class DailySessionExpiryMiddleware:
    """
    Enforce a hard 24-hour session window from login_time.

    Works for both:
    - Django auth sessions (request.user.is_authenticated)
    - Legacy sessions (request.session['user_credentials_id'])
    """

    MAX_AGE = timedelta(hours=24)

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path or ""

        # Allow unauthenticated access to login/logout and static/media endpoints.
        if (
            path.startswith("/login")
            or path.startswith("/logout")
            or path.startswith("/static/")
            or path.startswith("/media/")
        ):
            return self.get_response(request)

        has_legacy = bool(request.session.get("user_credentials_id"))
        has_django = bool(getattr(request.user, "is_authenticated", False) and request.user.is_authenticated)

        if has_legacy or has_django:
            raw = request.session.get("login_time")
            login_time = None
            if raw:
                try:
                    # Stored as ISO string
                    login_time = timezone.datetime.fromisoformat(raw)
                    if timezone.is_naive(login_time):
                        login_time = timezone.make_aware(login_time, timezone.get_current_timezone())
                except Exception:
                    login_time = None

            # Backward compatibility: if login_time wasn't set, set it once.
            if login_time is None:
                request.session["login_time"] = timezone.now().isoformat()
            else:
                if timezone.now() - login_time > self.MAX_AGE:
                    # Expire session
                    try:
                        logout(request)
                    except Exception:
                        pass
                    try:
                        request.session.flush()
                    except Exception:
                        # Worst case, clear known keys
                        request.session.pop("user_credentials_id", None)
                        request.session.pop("user_credentials_username", None)
                        request.session.pop("login_time", None)
                    messages.info(request, "Your session expired. Please log in again.")
                    return redirect("login")

        return self.get_response(request)


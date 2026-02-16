"""
Secure token for setup-password link (time-limited, signed).
"""
import time
from django.core.signing import Signer, BadSignature, TimestampSigner


# Token valid for 7 days
MAX_AGE_SECONDS = 7 * 24 * 3600


def make_setup_password_token(user):
    """Generate a signed token for the setup-password URL for this user."""
    signer = TimestampSigner()
    payload = str(user.pk)
    return signer.sign(payload)


def get_user_from_setup_password_token(token):
    """
    Validate token and return the User if valid, else None.
    """
    from django.contrib.auth import get_user_model
    User = get_user_model()
    signer = TimestampSigner()
    try:
        value = signer.unsign(token, max_age=MAX_AGE_SECONDS)
        user_id = int(value)
        return User.objects.get(pk=user_id)
    except (BadSignature, ValueError, User.DoesNotExist):
        return None

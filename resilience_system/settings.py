"""
Django settings for resilience_system project.
Enterprise-level configuration.
"""

from pathlib import Path
import os
from dotenv import load_dotenv
import pymysql

# --------------------------------------------------
# BASE DIR
# --------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent

# --------------------------------------------------
# LOAD .env
# Try project root (one level above BASE_DIR), then BASE_DIR, then app folder
# --------------------------------------------------
env_path = BASE_DIR.parent / ".env"
if not env_path.exists():
    env_path = BASE_DIR / ".env"
if not env_path.exists():
    env_path = Path(__file__).resolve().parent / ".env"

load_dotenv(env_path)

# --------------------------------------------------
# MySQL support for Windows (PyMySQL)
# --------------------------------------------------
pymysql.install_as_MySQLdb()

# --------------------------------------------------
# SECURITY
# --------------------------------------------------
SECRET_KEY = os.getenv("SECRET_KEY", "unsafe-dev-secret-key")

DEBUG = os.getenv("DEBUG", "False").lower() == "true"

# ✅ REQUIRED: Fix DisallowedHost
ALLOWED_HOSTS = [
    "20.157.93.134",
    "resilience.mavensoft.com",
    "localhost",
    "127.0.0.1",
]
CSRF_TRUSTED_ORIGINS = [
    "https://resilience.mavensoft.com",
]

# Behind IIS reverse proxy
USE_X_FORWARDED_HOST = True
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# ✅ REQUIRED: Allow iframe embedding (DEV ONLY)
X_FRAME_OPTIONS = "ALLOWALL"

# --------------------------------------------------
# APPLICATIONS
# --------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core",
]

# --------------------------------------------------
# MIDDLEWARE
# --------------------------------------------------
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "core.middleware.DailySessionExpiryMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    # ❌ REMOVED: XFrameOptionsMiddleware (this was blocking iframe)
]

# --------------------------------------------------
# URL / WSGI
# --------------------------------------------------
ROOT_URLCONF = "resilience_system.urls"
WSGI_APPLICATION = "resilience_system.wsgi.application"

# --------------------------------------------------
# TEMPLATES
# --------------------------------------------------
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.auth_context",
            ],
        },
    },
]

# --------------------------------------------------
# DATABASE (MySQL from .env)
# --------------------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": os.getenv("DB_NAME", ""),
        "USER": os.getenv("DB_USER", ""),
        "PASSWORD": os.getenv("DB_PASSWORD", ""),
        # Django's MySQL backend expects a string for HOST, not None
        "HOST": os.getenv("DB_HOST", ""),
        "PORT": os.getenv("DB_PORT", "3306"),
    }
}

# --------------------------------------------------
# PASSWORD VALIDATORS
# --------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --------------------------------------------------
# INTERNATIONALIZATION
# --------------------------------------------------
LANGUAGE_CODE = os.getenv("LANGUAGE_CODE", "en-us")
TIME_ZONE = os.getenv("TIME_ZONE", "UTC")

USE_I18N = True
USE_TZ = True

# --------------------------------------------------
# STATIC & MEDIA
# --------------------------------------------------
STATIC_URL = os.getenv("STATIC_URL", "/static/")
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

MEDIA_URL = os.getenv("MEDIA_URL", "/media/")
MEDIA_ROOT = BASE_DIR / "media"

# --------------------------------------------------
# AUTH REDIRECTS
# --------------------------------------------------
LOGIN_URL = os.getenv("LOGIN_URL", "/login/")
LOGIN_REDIRECT_URL = os.getenv("LOGIN_REDIRECT_URL", "/dashboard/")
LOGOUT_REDIRECT_URL = os.getenv("LOGOUT_REDIRECT_URL", "/")

# --------------------------------------------------
# SESSION: hard 24-hour login window
# --------------------------------------------------
# Cookie expiry default (24 hours). We also enforce login_time in middleware.
SESSION_COOKIE_AGE = int(os.getenv("SESSION_COOKIE_AGE", "86400"))

# --------------------------------------------------
# EMAIL CONFIGURATION
# --------------------------------------------------
EMAIL_BACKEND = os.getenv(
    "EMAIL_BACKEND",
    "django.core.mail.backends.console.EmailBackend"
)

DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL")

EMAIL_HOST = os.getenv("EMAIL_HOST")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", 587))
EMAIL_USE_TLS = os.getenv("EMAIL_USE_TLS", "true").lower() == "true"
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD")

# --------------------------------------------------
# STRIPE CONFIG
# --------------------------------------------------
STRIPE_PUBLIC_KEY = os.getenv("STRIPE_PUBLIC_KEY")
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

# --------------------------------------------------
# AZURE EMAIL CONFIG (Microsoft Graph API)
# --------------------------------------------------
AZURE_TENANT_ID = os.getenv("AZURE_TENANT_ID")
AZURE_CLIENT_ID = os.getenv("AZURE_CLIENT_ID")
AZURE_CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET")
MAIL_SENDER = os.getenv("MAIL_SENDER")

# Admin/Notification email for new user signups
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL") or os.getenv("NOTIFICATION_EMAIL")

# --------------------------------------------------
# ENTERPRISE SECURITY
# --------------------------------------------------
if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = "ALLOWALL"  # Allow iframe embedding as required

# --------------------------------------------------
# SCHEDULER
# --------------------------------------------------
RUN_APSCHEDULER = os.getenv("RUN_APSCHEDULER", "True").lower() in ("true", "1", "yes")

# --------------------------------------------------
# DEFAULT PK FIELD
# --------------------------------------------------
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

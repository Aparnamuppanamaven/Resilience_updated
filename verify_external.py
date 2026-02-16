"""
Quick verification that external access settings work.
Run: python verify_external.py
"""
import os
import sys

# Simulate what RUN_EXTERNAL.bat sets
os.environ['ALLOW_EXTERNAL'] = 'True'
os.environ['ALLOWED_HOSTS'] = '*'
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'resilience_system.settings')

try:
    import django
    django.setup()
    from django.conf import settings
    hosts = settings.ALLOWED_HOSTS
    if '*' in hosts or (hosts and hosts != ['localhost', '127.0.0.1']):
        print("[OK] ALLOWED_HOSTS allows external access:", hosts)
    else:
        print("[FAIL] ALLOWED_HOSTS not set for external:", hosts)
        sys.exit(1)
    print("[OK] Django settings load correctly.")
    print("\nTo test the server:")
    print("  1. Run: RUN_EXTERNAL.bat")
    print("  2. Open browser: http://localhost:8080")
    print("  3. For public URL, use ngrok: ngrok http 8080")
except Exception as e:
    print("[FAIL]", e)
    sys.exit(1)

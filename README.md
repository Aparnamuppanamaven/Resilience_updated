# Resilience System - Django Enterprise Application

Enterprise-level Django application for operational resilience management, shift packet generation, and incident tracking.

## Features

- **Foundation License Management**: Purchase and setup workflow
- **Operational Updates**: Capture, normalize, and track incidents
- **Shift Packet Generation**: Automated shift packet creation and distribution
- **Decision Logging**: Track operational decisions with rationale
- **Multi-Organization Support**: Isolated data per organization
- **User Authentication**: Secure user management with Django auth
- **Admin Interface**: Full Django admin for data management

## Project Structure

```
Resilience_project/
├── manage.py
├── requirements.txt
├── resilience_system/          # Main Django project
│   ├── settings.py
│   ├── urls.py
│   ├── wsgi.py
│   └── asgi.py
├── core/                       # Main application
│   ├── models.py              # Data models
│   ├── views.py               # View logic
│   ├── forms.py               # Form definitions
│   ├── admin.py               # Admin configuration
│   └── templates/core/        # HTML templates
└── static/                     # Static files
    └── css/
        └── styles.css
```

## Installation

### Prerequisites

- Python 3.8 or higher
- pip (Python package manager)

### Setup Steps

1. **Navigate to project directory:**
   ```bash
   cd Resilience_project
   ```

2. **Create virtual environment (recommended):**
   ```bash
   python -m venv venv
   
   # On Windows:
   venv\Scripts\activate
   
   # On macOS/Linux:
   source venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Run migrations:**
   ```bash
   python manage.py makemigrations
   python manage.py migrate
   ```

5. **Create superuser (optional, for admin access):**
   ```bash
   python manage.py createsuperuser
   ```

6. **Run development server:**
   ```bash
   python manage.py runserver
   ```

7. **Access the application:**
   - Landing page: http://127.0.0.1:8000/
   - Admin panel: http://127.0.0.1:8000/admin/

## Usage

### Initial Setup

1. **Purchase Foundation License:**
   - Navigate to the landing page
   - Click "Get Started" or "Initialize System"
   - Complete the checkout form with:
     - Agency/Organization name
     - Primary Liaison details
     - Incident types of concern
     - Communication preferences

2. **Complete Onboarding:**
   - After checkout, you'll be redirected to onboarding
   - Set shift packet cadence (8, 12, or 24 hours)
   - Configure stakeholder distribution list
   - Launch dashboard

### Using the Dashboard

- **Dashboard**: Overview of system status, pending updates, and quick actions
- **Capture**: Create new operational updates with severity levels
- **Normalize**: View and manage all incoming updates
- **Distribute**: Generate and send shift packets
- **Decision Log**: Track operational decisions
- **Coverage**: View resilience scope and communication channels

### Alert Management

- Click "Activate Alert" to escalate to High Alert status
- System automatically adjusts cadence to 4 hours during alerts
- All alert activations are logged in Decision Log

## Models

### Organization
- Represents agencies/organizations using the system
- Tracks license type (Foundation/Enterprise)
- Purchase dates for credit tracking

### Liaison
- Extends Django User model
- Links users to organizations
- Stores communication preferences

### OperationalUpdate
- Tracks incidents and updates
- Severity levels: Low, Medium, High
- Links to organization and owner

### Decision
- Logs operational decisions
- Tracks rationale and status
- Links to organization and owner

### SystemSettings
- Per-organization configuration
- Cadence hours, distribution lists
- Current status and phase

### ShiftPacket
- Generated shift packets
- Contains executive summary, risks, actions
- Tracks sent timestamps

## Production Deployment

### Environment Variables

Set these environment variables for production:

```bash
SECRET_KEY=your-secret-key-here
DEBUG=False
ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com
DB_NAME=resilience_db
DB_USER=resilience_user
DB_PASSWORD=your-db-password
DB_HOST=localhost
DB_PORT=5432
```

### Database

For production, update `settings.py` to use PostgreSQL:

```python
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('DB_NAME'),
        'USER': os.environ.get('DB_USER'),
        'PASSWORD': os.environ.get('DB_PASSWORD'),
        'HOST': os.environ.get('DB_HOST', 'localhost'),
        'PORT': os.environ.get('DB_PORT', '5432'),
    }
}
```

### Static Files

Collect static files for production:

```bash
python manage.py collectstatic
```

### Security Settings

Production security settings are automatically enabled when `DEBUG=False`:
- SSL redirect
- Secure cookies
- XSS protection
- Content type nosniff
- X-Frame-Options: DENY

## API Endpoints

- `GET /` - Landing page
- `GET /checkout/` - Checkout form
- `POST /checkout/` - Process checkout
- `GET /onboarding/` - Onboarding form
- `POST /onboarding/` - Complete onboarding
- `GET /dashboard/` - Main dashboard (requires login)
- `GET /capture/` - Create update form (requires login)
- `POST /capture/` - Submit update (requires login)
- `GET /normalize/` - View all updates (requires login)
- `GET /distribute/` - Generate shift packet (requires login)
- `POST /distribute/` - Send shift packet (requires login)
- `GET /decision-log/` - View decision log (requires login)
- `GET /coverage/` - Coverage & communications (requires login)
- `POST /api/toggle-alert/` - Toggle alert status (AJAX, requires login)

## Default Credentials

After checkout, users are created with:
- **Username**: Email prefix (before @)
- **Password**: `resilience2024!`

**Important**: Users should change their password after first login in production.

## Enterprise Features

The system is designed to support:
- Multi-department workflows
- Custom integrations
- Automated dispatch
- RBAC (Role-Based Access Control)
- Audit-grade immutability
- Prescriptive recommendations

## License

Copyright © 2026 Resilience Systems. All rights reserved.

## Support

For support, contact via email/tickets as configured during onboarding.


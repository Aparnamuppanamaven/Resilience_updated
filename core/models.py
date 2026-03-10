"""
Core models for Resilience System
Enterprise-level data models
"""
from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator, MaxValueValidator


class Organization(models.Model):
    """Organization/Agency model"""
    tenant_id = models.BigAutoField(primary_key=True, db_column='tenant_id')
    name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)
    license_type = models.CharField(
        max_length=20,
        choices=[
            ('foundation', 'Foundation'),
            ('enterprise', 'Enterprise'),
        ],
        default='foundation'
    )
    foundation_purchase_date = models.DateTimeField(null=True, blank=True)
    enterprise_upgrade_date = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        db_table = 'core_organization'
        ordering = ['-created_at']
    
    def __str__(self):
        return self.name


class Liaison(models.Model):
    """Designated Liaison model - extends User"""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='liaison_profile')
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='liaisons')
    phone = models.CharField(max_length=20, blank=True)
    profile_image = models.CharField(max_length=255, blank=True, null=True, help_text="Path to profile photo in MEDIA")
    preferred_channels = models.CharField(
        max_length=50,
        choices=[
            ('email', 'Email Only'),
            ('email_sms', 'Email + SMS'),
            ('slack', 'Slack / Teams Webhook'),
        ],
        default='email'
    )
    incident_types = models.TextField(help_text="Key incident types of concern")
    role = models.CharField(max_length=100, blank=True, help_text="User role")
    dept = models.CharField(max_length=100, blank=True, help_text="Department")
    countee = models.CharField(max_length=100, blank=True, help_text="Countee")
    created_at = models.DateTimeField(auto_now_add=True)
    tenant_id = models.BigIntegerField(null=True, blank=True, db_column='tenant_id')
    
    def __str__(self):
        return f"{self.user.get_full_name()} - {self.organization.name}"


class IncidentAssignedUser(models.Model):
    """Mapping table for Incident assigned users - tracks assignment history with who assigned and when"""
    id = models.AutoField(primary_key=True)
    user_id = models.ForeignKey(Liaison, on_delete=models.CASCADE, db_column='user_id', related_name='incident_assignments')
    incident_id = models.ForeignKey('Incident', on_delete=models.CASCADE, db_column='incident_id', related_name='user_assignments')
    mapped_user_id = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, db_column='mapped_user_id', related_name='assignments_made', help_text="Logged-in user who made this assignment")
    is_active = models.BooleanField(default=True, db_column='is_active')  # True for current assignments, False for historical
    created_at = models.DateTimeField(auto_now_add=True, db_column='created_at')
    tenant_id = models.BigIntegerField(null=True, blank=True, db_column='tenant_id')
    
    class Meta:
        db_table = 'core_incident_user_mapping'
        ordering = ['-created_at']
        managed = False  # Django should NOT manage this table
    
    def __str__(self):
        return f"Incident {self.incident_id_id} - User {self.user_id_id} (assigned by {self.mapped_user_id_id if self.mapped_user_id else 'System'})"


class Incident(models.Model):
    """Incidents - maps to existing core_operationalupdate table"""
    SEVERITY_CHOICES = [
        ('LOW', 'Low - Informational'),
        ('MEDIUM', 'Medium - Potential Impact'),
        ('HIGH', 'High - Critical Incident'),
        ('CRITICAL', 'Critical'),
    ]
    
    id = models.BigAutoField(primary_key=True)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='incidents', db_column='organization_id')
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES, default='LOW')
    impact = models.TextField(blank=True, help_text="Why it matters - operational impact analysis")
    next_action = models.CharField(max_length=255, blank=True)
    status = models.CharField(
        max_length=20,
        default='Open',
        choices=[
            ('Open', 'Open'),
            ('Investigating', 'Investigating'),
            ('Resolved', 'Resolved'),
        ],
    )
    timestamp = models.DateTimeField(auto_now_add=True)
    owner = models.ForeignKey(Liaison, on_delete=models.SET_NULL, null=True, blank=True, db_column='owner_id')
    assigned_users = models.ManyToManyField(Liaison, through='IncidentAssignedUser', related_name='assigned_incidents', blank=True)
    is_synthesized = models.BooleanField(default=False)
    tenant_id = models.BigIntegerField(null=True, blank=True, db_column='tenant_id')
    
    class Meta:
        db_table = 'core_operationalupdate'
        ordering = ['-timestamp']
        managed = False  # Don't let Django manage this table - it already exists
    
    def __str__(self):
        return f"{self.title} ({self.severity})"


class IncidentCapture(models.Model):
    """Incidents captured from Capture form - maps to core_incidents table"""
    SEVERITY_CHOICES = [
        ('LOW', 'Low - Informational'),
        ('MEDIUM', 'Medium - Potential Impact'),
        ('HIGH', 'High - Critical Incident'),
        ('CRITICAL', 'Critical'),
    ]
    
    id = models.BigAutoField(primary_key=True)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='captured_incidents', db_column='organization_id')
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES, default='LOW')
    impact = models.TextField(blank=True, help_text="Why it matters - operational impact analysis")
    start_time = models.DateTimeField(null=True, blank=True, db_column='start_time')
    end_time = models.DateTimeField(null=True, blank=True, db_column='end_time')
    status = models.CharField(
        max_length=20,
        default='Open',
        choices=[
            ('Open', 'Open'),
            ('Investigating', 'Investigating'),
            ('Resolved', 'Resolved'),
        ],
    )
    resolved_at = models.DateTimeField(null=True, blank=True, db_column='resolved_at')
    created_at = models.DateTimeField(db_column='Created_at')
    created_by = models.ForeignKey(Liaison, on_delete=models.SET_NULL, null=True, blank=True, db_column='Created_by', related_name='created_incidents')
    is_synthesized = models.BooleanField(default=False, db_column='is_synthesized')
    tenant_id = models.BigIntegerField(null=True, blank=True, db_column='tenant_id')
    
    class Meta:
        db_table = 'core_incidents'
        ordering = ['-created_at']
        managed = False  # Don't let Django manage this table - it already exists
    
    def __str__(self):
        return f"{self.title} ({self.severity})"


class IncidentEvent(models.Model):
    """Incident event logs - tracks log entries for incidents"""
    id = models.AutoField(primary_key=True, db_column='id')
    incident = models.ForeignKey(Incident, on_delete=models.CASCADE, db_column='incident_id', related_name='event_logs')
    # Note: underlying DB column was renamed from `event_desc` to `event_description`
    # but we keep the Django field name `event_desc` for backwards compatibility.
    event_desc = models.TextField(db_column='event_description')
    user_log = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, db_column='user_id', related_name='incident_logs_created')
    created_time = models.DateTimeField(auto_now_add=True, db_column='created_time')
    tenant_id = models.BigIntegerField(null=True, blank=True, db_column='tenant_id')
    
    class Meta:
        db_table = 'core_incident_events'
        ordering = ['-created_time']
        managed = False  # Django should NOT manage this table
    
    def __str__(self):
        return f"Event #{self.id} - Incident {self.incident_id} - {self.created_time}"


class OperationalUpdate(models.Model):
    """Operational updates/incidents - maps to existing core_operationalupdate table"""
    SEVERITY_CHOICES = [
        ('LOW', 'Low - Informational'),
        ('MEDIUM', 'Medium - Potential Impact'),
        ('HIGH', 'High - Critical Incident'),
        ('CRITICAL', 'Critical'),
    ]
    
    id = models.BigAutoField(primary_key=True)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='updates', db_column='organization_id')
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES, default='LOW')
    owner = models.ForeignKey(Liaison, on_delete=models.SET_NULL, null=True, blank=True, related_name='owned_updates', db_column='owner_id')
    impact = models.TextField(blank=True, help_text="Why it matters - operational impact analysis")
    next_action = models.CharField(max_length=255, blank=True)
    status = models.CharField(
        max_length=20,
        default='Open',
        choices=[
            ('Open', 'Open'),
            ('Investigating', 'Investigating'),
            ('Resolved', 'Resolved'),
        ],
    )
    timestamp = models.DateTimeField(auto_now_add=True)
    is_synthesized = models.BooleanField(default=False)
    tenant_id = models.BigIntegerField(null=True, blank=True, db_column='tenant_id')
    
    class Meta:
        db_table = 'core_operationalupdate'
        ordering = ['-timestamp']
        managed = False  # Don't let Django manage this table - it already exists
    
    def __str__(self):
        return f"{self.title} ({self.severity})"


class Decision(models.Model):
    """Decision log entries"""
    STATUS_CHOICES = [
        ('Open', 'Open'),
        ('Closed', 'Closed'),
    ]
    
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='decisions')
    decision = models.CharField(max_length=255)
    rationale = models.TextField()
    owner = models.ForeignKey(Liaison, on_delete=models.SET_NULL, null=True, related_name='owned_decisions')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='Open')
    timestamp = models.DateTimeField(auto_now_add=True)
    tenant_id = models.BigIntegerField(null=True, blank=True, db_column='tenant_id')
    
    class Meta:
        db_table = 'core_decision'
        ordering = ['-timestamp']
    
    def __str__(self):
        return f"{self.decision} - {self.status}"


class SystemSettings(models.Model):
    """System-wide settings per organization"""
    organization = models.OneToOneField(Organization, on_delete=models.CASCADE, related_name='settings')
    cadence_hours = models.IntegerField(
        default=24,
        validators=[MinValueValidator(1), MaxValueValidator(168)],
        help_text="Shift packet cadence in hours"
    )
    distribution_list = models.TextField(
        blank=True,
        help_text="Comma-separated email addresses for shift packet distribution"
    )
    current_status = models.CharField(
        max_length=20,
        choices=[
            ('Normal', 'Normal'),
            ('Emergency Watch', 'Emergency Watch'),
            ('High Alert', 'High Alert'),
        ],
        default='Normal'
    )
    current_phase = models.IntegerField(
        default=0,
        choices=[(0, 'Standard Operations'), (1, 'Escalation Protocol')]
    )
    last_sync = models.DateTimeField(auto_now=True)
    tenant_id = models.BigIntegerField(null=True, blank=True, db_column='tenant_id')
    
    def __str__(self):
        return f"Settings for {self.organization.name}"


class ShiftPacket(models.Model):
    """Generated shift packets"""
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='shift_packets')
    packet_number = models.CharField(max_length=50, unique=True)
    generated_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20)
    executive_summary = models.TextField()
    key_risks = models.TextField()
    next_actions = models.TextField()
    previous_shift_info = models.TextField(blank=True)
    what_happened = models.TextField(blank=True)
    next_steps = models.TextField(blank=True)
    tx_type = models.CharField(
        max_length=20,
        blank=True,
        choices=[
            ('AI', 'AI'),
            ('Manual', 'Manual'),
        ],
    )
    sent_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    tenant_id = models.BigIntegerField(null=True, blank=True, db_column='tenant_id')
    
    class Meta:
        ordering = ['-generated_at']
    
    def __str__(self):
        return f"Packet #{self.packet_number} - {self.organization.name}"


class IncidentShiftSchedule(models.Model):
    """Scheduler configuration for incident shift generation"""
    id = models.BigAutoField(primary_key=True)
    incident = models.ForeignKey(
        Incident,
        on_delete=models.CASCADE,
        db_column='incident_id',
        related_name='shift_schedules',
    )
    shift_hours = models.IntegerField()
    created_by = models.BigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    tenant_id = models.BigIntegerField(null=True, blank=True, db_column='tenant_id')

    class Meta:
        db_table = 'core_incident_shift_schedule'
        ordering = ['-created_at']


class ShiftPacketHistory(models.Model):
    """History of edits to shift packets"""
    id = models.BigAutoField(primary_key=True)
    shiftpacket = models.ForeignKey(
        ShiftPacket,
        on_delete=models.CASCADE,
        db_column='shiftpacket_id',
        related_name='history',
    )
    incident = models.ForeignKey(
        Incident,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column='incident_id',
        related_name='shiftpacket_history',
    )
    shift = models.BigIntegerField(
        null=True,
        blank=True,
        db_column='shift_id',
        help_text="Reference to legacy core_shifts.shift_id",
    )
    input = models.TextField(blank=True)
    what_happened = models.TextField(blank=True)
    next_steps = models.TextField(blank=True)
    tx_type = models.CharField(max_length=20)
    created_by = models.BigIntegerField(null=True, blank=True)
    updated_by = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    tenant_id = models.BigIntegerField(null=True, blank=True, db_column='tenant_id')

    class Meta:
        db_table = 'core_shiftpacket_history'
        ordering = ['-created_at']


class AgencyUserCounter(models.Model):
    """License/seat usage per agency/organization"""
    id = models.BigAutoField(primary_key=True)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        db_column='organization_id',
        related_name='user_counters',
    )
    admin_user_id = models.BigIntegerField()
    cnt_allowed = models.IntegerField(default=2)
    current_cnt = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    tenant_id = models.BigIntegerField(null=True, blank=True, db_column='tenant_id')

    class Meta:
        db_table = 'core_agency_user_counter'
        ordering = ['-created_at']


class Payment(models.Model):
    """Payment model for Foundation/Enterprise purchases"""
    PAYMENT_METHOD_CHOICES = [
        ('INVOICE', 'Invoice - Net 30'),
        ('ACH', 'ACH (Bank Transfer)'),
        ('CARD', 'Credit Card'),
    ]
    
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('PAID', 'Paid'),
        ('INVOICED', 'Invoiced'),
        ('PROCESSING', 'Processing'),
    ]
    
    id = models.AutoField(primary_key=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES, default='INVOICE')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    invoice_id = models.CharField(max_length=50, blank=True, null=True, unique=True)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='payments', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    tenant_id = models.BigIntegerField(null=True, blank=True, db_column='tenant_id')
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Payment #{self.id} - {self.payment_method} - ${self.amount}"


class Invoice(models.Model):
    """Invoice model for Net 30 payments"""
    PAYMENT_TERMS_CHOICES = [
        ('NET_30', 'Net 30'),
    ]
    
    invoice_id = models.CharField(max_length=50, unique=True, primary_key=True)
    payment = models.OneToOneField(Payment, on_delete=models.CASCADE, related_name='invoice')
    billing_entity_name = models.CharField(max_length=255)
    billing_email = models.EmailField()
    po_number = models.CharField(max_length=100, blank=True)
    payment_terms = models.CharField(max_length=20, choices=PAYMENT_TERMS_CHOICES, default='NET_30')
    early_pay_terms = models.CharField(max_length=50, default='2% / 10, Net 30')
    due_date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)
    tenant_id = models.BigIntegerField(null=True, blank=True, db_column='tenant_id')
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Invoice {self.invoice_id} - {self.billing_entity_name}"


class ExternalUser(models.Model):
    """Mapping to legacy Users table"""
    id = models.AutoField(primary_key=True)
    agency_name = models.CharField(max_length=150)
    primary_liaison_name = models.CharField(max_length=100)
    liaison_email = models.CharField(max_length=150)
    key_incident_types = models.CharField(max_length=255, blank=True, null=True)
    preferred_communication_channels = models.CharField(max_length=100, blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)
    tenant_id = models.BigIntegerField(null=True, blank=True, db_column='tenant_id')

    class Meta:
        managed = False
        db_table = 'core_users'
        
    def __str__(self):
        return self.agency_name


class ExternalPayment(models.Model):
    """Mapping to legacy payments table"""
    payment_id = models.AutoField(primary_key=True)
    username = models.CharField(max_length=100)
    payment_status = models.CharField(max_length=50)
    payment_method = models.CharField(max_length=50)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_time = models.DateTimeField(blank=True, null=True)
    tenant_id = models.BigIntegerField(null=True, blank=True, db_column='tenant_id')

    class Meta:
        managed = False
        db_table = 'payments'
        
    def __str__(self):
        return f"Payment #{self.payment_id} - {self.amount}"


class ExternalSubscription(models.Model):
    """Mapping to core_subscriptions table"""
    id = models.AutoField(primary_key=True)
    subscription_id = models.CharField(max_length=64, unique=True, db_column='subscription_id')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    paid_status = models.CharField(max_length=20, db_column='paid_status')
    created_at = models.DateTimeField(db_column='created_at')
    updated_at = models.DateTimeField(db_column='updated_at')
    stripe_payment = models.ForeignKey('StripePayment', on_delete=models.SET_NULL, null=True, blank=True, db_column='stripe_payment_id')
    user = models.ForeignKey('auth.User', on_delete=models.CASCADE, db_column='user_id')
    tenant_id = models.BigIntegerField(null=True, blank=True, db_column='tenant_id')

    class Meta:
        managed = False
        db_table = 'core_subscriptions'
        
    def __str__(self):
        return f"Subscription {self.subscription_id} - {self.user.username if self.user else 'N/A'}"


class UserCredentials(models.Model):
    """Mapping to MySQL table user_credentials (resilience_uat DB)"""
    user_id = models.AutoField(primary_key=True)
    username = models.CharField(max_length=100, unique=True)
    # Plain text password stored in password_hash column
    password_hash = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    tenant_id = models.BigIntegerField(null=True, blank=True, db_column='tenant_id')

    class Meta:
        managed = False
        db_table = 'user_credentials'

    def __str__(self):
        return self.username


class Shift(models.Model):
    """Shift model - maps to existing core_shifts table"""
    shift_id = models.AutoField(primary_key=True, db_column='shift_id')
    tenant_id = models.BigIntegerField(db_column='tenant_id')
    shift_type = models.CharField(max_length=20, db_column='shift_type')  # morning, afternoon, evening, flexible
    shift_start_time = models.TimeField(db_column='shift_start_time')
    shift_end_time = models.TimeField(db_column='shift_end_time')
    shift_incharge = models.IntegerField(blank=True, null=True, db_column='shift_incharge')
    created_at = models.DateTimeField(auto_now_add=False, db_column='created_at')
    
    class Meta:
        db_table = 'core_shifts'
        managed = False  # Don't let Django manage this table - it already exists
    
    def __str__(self):
        return f"{self.shift_type.title()} Shift ({self.shift_start_time} - {self.shift_end_time})"


class Department(models.Model):
    """Department model - maps to existing core_department table"""
    id = models.BigIntegerField(primary_key=True, db_column='id')
    category = models.CharField(max_length=100, db_column='category')
    service_name = models.CharField(max_length=255, db_column='service_name')
    organization_id = models.BigIntegerField(db_column='organization_id')
    tenant_id = models.BigIntegerField(null=True, blank=True, db_column='tenant_id')
    
    class Meta:
        db_table = 'core_department'
        managed = False  # Don't let Django manage this table - it already exists
    
    def __str__(self):
        return f"{self.category} - {self.service_name}"


class TenantDomain(models.Model):
    """Tenant Domain model - maps to existing tenant_domains table"""
    tenant_id = models.BigIntegerField(primary_key=True, db_column='tenant_id')
    org_name = models.CharField(max_length=255, db_column='org_name')
    department = models.CharField(max_length=255, null=True, blank=True, db_column='department')
    location = models.CharField(max_length=255, null=True, blank=True, db_column='location')
    contact_person = models.CharField(max_length=255, null=True, blank=True, db_column='contact_person')
    mobile = models.CharField(max_length=20, null=True, blank=True, db_column='mobile')
    is_active = models.BooleanField(default=True, db_column='is_active')
    created_at = models.DateTimeField(null=True, blank=True, db_column='created_at')
    
    class Meta:
        db_table = 'tenant_domains'
        managed = False  # Don't let Django manage this table - it already exists
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.org_name} (Tenant ID: {self.tenant_id})"


class UsersTable(models.Model):
    """Users table from database - maps to existing users table"""
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=150, blank=True, null=True)
    mobile_no = models.CharField(max_length=20, blank=True, null=True)
    email_id = models.CharField(max_length=150, blank=True, null=True)
    department = models.CharField(max_length=200, blank=True, null=True)
    sub_department = models.CharField(max_length=200, blank=True, null=True)
    shift_start_time = models.TimeField(blank=True, null=True)
    agency_name = models.CharField(max_length=150)
    primary_liaison_name = models.CharField(max_length=100)
    liaison_email = models.CharField(max_length=150)
    # Optional profile picture path stored in new User_image column
    user_image = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        db_column='User_image',
    )
    key_incident_types = models.CharField(max_length=255, blank=True, null=True)
    preferred_communication_channels = models.CharField(max_length=100, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=False, null=True, blank=True)
    shift_id = models.IntegerField(blank=True, null=True)
    role = models.CharField(max_length=20, blank=True, null=True, db_column='role')
    tenant_id = models.BigIntegerField(null=True, blank=True, db_column='tenant_id')
    
    class Meta:
        db_table = 'core_users'
        managed = False  # Don't let Django manage this table - it already exists
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.primary_liaison_name} ({self.agency_name})"


class UserProfile(models.Model):
    """Extended user profile with additional fields"""
    ROLE_CHOICES = [
        ('admin', 'Administrator'),
        ('manager', 'Manager'),
        ('operator', 'Operator'),
        ('analyst', 'Analyst'),
        ('liaison', 'Liaison'),
        ('viewer', 'Viewer'),
    ]
    
    user_credential = models.OneToOneField(
        UserCredentials,
        on_delete=models.CASCADE,
        related_name='profile',
        primary_key=True
    )
    full_name = models.CharField(max_length=255)
    mobile = models.CharField(max_length=20, blank=True)
    email = models.EmailField()
    role = models.CharField(max_length=50, choices=ROLE_CHOICES, default='viewer')
    department = models.CharField(max_length=255, blank=True)
    shift_start_time = models.TimeField(null=True, blank=True, help_text="Shift start time (HH:MM format)")
    shift_end_time = models.TimeField(null=True, blank=True, help_text="Shift end time (HH:MM format)")
    designated_manager = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='subordinates',
        help_text="Manager assigned to this user"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    tenant_id = models.BigIntegerField(null=True, blank=True, db_column='tenant_id')
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.full_name} ({self.user_credential.username})"


class Payment(models.Model):
    """Enterprise payment model with Invoice/ACH/Card support"""
    PAYMENT_METHOD_CHOICES = [
        ('INVOICE', 'Invoice - Net 30'),
        ('ACH', 'ACH (Bank Transfer)'),
        ('CARD', 'Credit Card'),
    ]
    
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('PAID', 'Paid'),
        ('INVOICED', 'Invoiced'),
        ('PROCESSING', 'Processing'),
    ]
    
    id = models.AutoField(primary_key=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES, default='INVOICE')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    invoice_id = models.CharField(max_length=100, blank=True, null=True, unique=True)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='payments', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    tenant_id = models.BigIntegerField(null=True, blank=True, db_column='tenant_id')
    
    # PCI-safe: store only tokenized card data (last 4 digits, token)
    card_last4 = models.CharField(max_length=4, blank=True)
    card_token = models.CharField(max_length=255, blank=True)  # Token from payment processor
    
    class Meta:
        ordering = ['-created_at']
        
    def __str__(self):
        return f"Payment #{self.id} - {self.payment_method} - ${self.amount}"
    
    def generate_invoice_id(self):
        """Generate unique invoice ID"""
        if not self.invoice_id:
            from datetime import datetime
            timestamp = datetime.now().strftime('%Y%m%d')
            count = Payment.objects.filter(invoice_id__startswith=f'INV-{timestamp}').count()
            self.invoice_id = f'INV-{timestamp}-{count + 1:04d}'
        return self.invoice_id


class Invoice(models.Model):
    """Invoice model for Net 30 and payment records"""
    PAYMENT_TERMS_CHOICES = [
        ('NET_30', 'Net 30'),
    ]
    
    invoice_id = models.CharField(max_length=100, primary_key=True)
    payment = models.OneToOneField(Payment, on_delete=models.CASCADE, related_name='invoice')
    billing_entity_name = models.CharField(max_length=255)
    billing_email = models.EmailField()
    po_number = models.CharField(max_length=100, blank=True)  # Required for Invoice method
    payment_terms = models.CharField(max_length=20, choices=PAYMENT_TERMS_CHOICES, default='NET_30')
    early_pay_terms = models.CharField(max_length=50, default='2% / 10, Net 30')
    due_date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)
    tenant_id = models.BigIntegerField(null=True, blank=True, db_column='tenant_id')
    
    class Meta:
        ordering = ['-created_at']
        
    def __str__(self):
        return f"Invoice {self.invoice_id} - {self.billing_entity_name}"


class StripePayment(models.Model):
    """Stripe payment model - tracks payment intents and webhook events"""
    user_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    stripe_payment_intent_id = models.CharField(max_length=255, unique=True, db_index=True)
    stripe_charge_id = models.CharField(max_length=255, blank=True, null=True)
    amount = models.IntegerField()  # Amount in cents
    currency = models.CharField(max_length=10, default='usd')
    status = models.CharField(max_length=50, default='pending')
    payment_method = models.CharField(max_length=50, blank=True, null=True)
    receipt_url = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    tenant_id = models.BigIntegerField(null=True, blank=True, db_column='tenant_id')
    
    class Meta:
        db_table = 'core_stripepayments'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['stripe_payment_intent_id']),
            models.Index(fields=['status']),
            models.Index(fields=['user_id']),
        ]
    
    def __str__(self):
        return f"Stripe Payment {self.stripe_payment_intent_id} - {self.status} - ${self.amount / 100}"


class TxLog(models.Model):
    """
    System log / audit trail for important activities.
    Tracks user login, user creation, incident creation, situation updates, etc.
    """
    ACTION_CHOICES = [
        ('Create', 'Create'),
        ('Update', 'Update'),
        ('Delete', 'Delete'),
        ('Login', 'Login'),
    ]

    id = models.BigAutoField(primary_key=True, auto_created=True)
    tenant_id = models.BigIntegerField(null=True, blank=True, db_column='tenant_id')
    entity = models.CharField(
        max_length=100,
        help_text="Module or object affected, e.g. User, Incident, SituationUpdate",
    )
    actionby = models.BigIntegerField(
        null=True,
        blank=True,
        db_column='actionby',
        help_text="User ID who performed the action (auth User or UserCredentials)",
    )
    actionon = models.CharField(
        max_length=255,
        blank=True,
        db_column='actionon',
        help_text="ID or name of the entity on which action was performed",
    )
    action = models.CharField(max_length=50, choices=ACTION_CHOICES)
    created_date = models.DateTimeField(auto_now_add=True, db_column='created_date')

    class Meta:
        db_table = 'tx_log'
        ordering = ['-created_date']
        verbose_name = 'System log'
        verbose_name_plural = 'System logs'

    def __str__(self):
        return f"{self.action} {self.entity} by {self.actionby} on {self.actionon}"


def log_system_action(tenant_id=None, entity=None, actionby=None, actionon=None, action='Create'):
    """
    Create a system log entry for audit trail.
    All arguments except entity and action are optional to support legacy/anonymous flows.
    """
    import logging
    logger = logging.getLogger(__name__)
    try:
        TxLog.objects.create(
            tenant_id=tenant_id,
            entity=entity or 'Unknown',
            actionby=actionby,
            actionon=str(actionon) if actionon is not None else '',
            action=action,
        )
    except Exception as e:
        logger.warning("TxLog audit write failed: %s", e, exc_info=True)


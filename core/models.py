"""
Core models for Resilience System
Enterprise-level data models
"""
from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator, MaxValueValidator


class Organization(models.Model):
    """Organization/Agency model"""
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
        ordering = ['-created_at']
    
    def __str__(self):
        return self.name


class Liaison(models.Model):
    """Designated Liaison model - extends User"""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='liaison_profile')
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='liaisons')
    phone = models.CharField(max_length=20, blank=True)
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
    
    class Meta:
        db_table = 'core_incidents_mapping'
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
    severity = models.CharField(max_length=10, choices=SEVERITY_CHOICES, default='LOW')
    impact = models.TextField(blank=True, help_text="Why it matters - operational impact analysis")
    next_action = models.CharField(max_length=255, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    owner = models.ForeignKey(Liaison, on_delete=models.SET_NULL, null=True, blank=True, db_column='owner_id')
    assigned_users = models.ManyToManyField(Liaison, through='IncidentAssignedUser', related_name='assigned_incidents', blank=True)
    is_synthesized = models.BooleanField(default=False)
    
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
    severity = models.CharField(max_length=10, choices=SEVERITY_CHOICES, default='LOW')
    impact = models.TextField(blank=True, help_text="Why it matters - operational impact analysis")
    next_action = models.CharField(max_length=255, blank=True)
    start_time = models.DateTimeField(null=True, blank=True, db_column='start_time')
    end_time = models.DateTimeField(null=True, blank=True, db_column='end_time')
    timestamp = models.DateTimeField(db_column='timestamp')
    owner = models.ForeignKey(Liaison, on_delete=models.SET_NULL, null=True, blank=True, db_column='owner_id')
    is_synthesized = models.BooleanField(default=False, db_column='is_synthesized')
    
    class Meta:
        db_table = 'core_incidents'
        ordering = ['-timestamp']
        managed = False  # Don't let Django manage this table - it already exists
    
    def __str__(self):
        return f"{self.title} ({self.severity})"


class IncidentEvent(models.Model):
    """Incident event logs - tracks log entries for incidents"""
    log_id = models.AutoField(primary_key=True, db_column='log_id')
    incident = models.ForeignKey(Incident, on_delete=models.CASCADE, db_column='incident_id', related_name='event_logs')
    log_description = models.TextField(db_column='log_description')
    user_log = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, db_column='user_log_id', related_name='incident_logs_created')
    created_time = models.DateTimeField(auto_now_add=True, db_column='created_time')
    
    class Meta:
        db_table = 'core_incident_event'
        ordering = ['-created_time']
        managed = False  # Django should NOT manage this table
    
    def __str__(self):
        return f"Log #{self.log_id} - Incident {self.incident_id} - {self.created_time}"


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
    severity = models.CharField(max_length=10, choices=SEVERITY_CHOICES, default='LOW')
    owner = models.ForeignKey(Liaison, on_delete=models.SET_NULL, null=True, blank=True, related_name='owned_updates', db_column='owner_id')
    impact = models.TextField(blank=True, help_text="Why it matters - operational impact analysis")
    next_action = models.CharField(max_length=255, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    is_synthesized = models.BooleanField(default=False)
    
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
    
    class Meta:
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
    sent_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-generated_at']
    
    def __str__(self):
        return f"Packet #{self.packet_number} - {self.organization.name}"


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

    class Meta:
        managed = False
        db_table = 'users'
        
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

    class Meta:
        managed = False
        db_table = 'payments'
        
    def __str__(self):
        return f"Payment #{self.payment_id} - {self.amount}"


class ExternalSubscription(models.Model):
    """Mapping to legacy subscriptions table"""
    subscription_id = models.AutoField(primary_key=True)
    username = models.CharField(max_length=100)
    payment = models.ForeignKey(ExternalPayment, models.DO_NOTHING)
    subscription_type = models.CharField(max_length=50)
    duration = models.IntegerField(null=True, blank=True)  # set when user pays
    subscription_start_date = models.DateField(null=True, blank=True)  # set when user pays
    subscription_end_date = models.DateField(null=True, blank=True)  # set when user pays
    subscription_status = models.CharField(max_length=30)
    created_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'subscriptions'
        
    def __str__(self):
        return self.subscription_type


class UserCredentials(models.Model):
    """Mapping to MySQL table user_credentials (resilience_uat DB)"""
    user_id = models.AutoField(primary_key=True)
    username = models.CharField(max_length=100, unique=True)
    # Plain text password stored in password_hash column
    password_hash = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

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
    
    class Meta:
        db_table = 'core_department'
        managed = False  # Don't let Django manage this table - it already exists
    
    def __str__(self):
        return f"{self.category} - {self.service_name}"


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
    key_incident_types = models.CharField(max_length=255, blank=True, null=True)
    preferred_communication_channels = models.CharField(max_length=100, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=False, null=True, blank=True)
    shift_id = models.IntegerField(blank=True, null=True)
    role = models.CharField(max_length=20, blank=True, null=True, db_column='role')
    
    class Meta:
        db_table = 'users'
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
    
    class Meta:
        db_table = 'stripepayments'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['stripe_payment_intent_id']),
            models.Index(fields=['status']),
            models.Index(fields=['user_id']),
        ]
    
    def __str__(self):
        return f"Stripe Payment {self.stripe_payment_intent_id} - {self.status} - ${self.amount / 100}"

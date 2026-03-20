"""
Forms for Resilience System
"""
from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.utils import timezone
from datetime import datetime, timedelta
import re
from .models import (
    OperationalUpdate,
    SystemSettings,
    UserCredentials,
    Payment,
    Invoice,
    UserProfile,
    Department,
    State,
    Counties,
)


PASSWORD_REGEX = re.compile(
    r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[^A-Za-z0-9]).{6,}$"
)


class CheckoutForm(forms.Form):
    """Checkout form for Foundation purchase"""
    agency = forms.CharField(
        max_length=255,
        label="Organization Name",
        required=True,
        strip=True,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'eg: [County Name] Emergency Management',
            'required': 'required',
        })
    )
    liaison_name = forms.CharField(
        max_length=255,
        label="Primary Liaison Name",
        required=True,
        strip=True,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Full Name',
            'required': 'required',
        })
    )
    liaison_email = forms.EmailField(
        label="Liaison Email (Primary Contact)",
        required=True,
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'email@agency.com',
            'required': 'required',
        })
    )
    mobile_number = forms.CharField(
        max_length=20,
        required=False,
        label="Mobile Number",
        strip=True,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Mobile number',
        })
    )
    password = forms.CharField(
        label="Password",
        required=True,
        strip=False,
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter password',
            'id': 'id_password',
            'required': 'required',
        }),
        help_text="Must contain uppercase, lowercase, number, special character, and be at least 6 characters"
    )
    confirm_password = forms.CharField(
        label="Confirm Password",
        required=True,
        strip=False,
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Confirm password',
            'id': 'id_confirm_password',
            'required': 'required',
        })
    )
    role = forms.CharField(
        max_length=100,
        label="Role",
        required=True,
        strip=True,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'e.g. Operations Manager',
            # 'required': 'required',
        })
    )
    dept = forms.ChoiceField(
        label="Department",
        required=True,
        choices=[('', 'Select department')],
        widget=forms.Select(attrs={
            'class': 'form-control',
            'required': 'required',
        })
    )
    sub_department = forms.ChoiceField(
        label="Sub Department",
        required=True,
        choices=[('', 'Select sub department')],
        widget=forms.Select(attrs={
            'class': 'form-control',
            'required': 'required',
        })
    )
    state = forms.ChoiceField(
        label="State",
        required=True,
        choices=[('', 'Select state')],
        widget=forms.Select(attrs={
            'class': 'form-control',
            'required': 'required',
        })
    )
    county = forms.ChoiceField(
        label="County",
        required=True,
        choices=[('', 'Select county')],
        widget=forms.Select(attrs={
            'class': 'form-control',
            'required': 'required',
        })
    )
    incidents = forms.CharField(
        label="Key Incident Types of Concern",
        required=True,
        strip=True,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'e.g. Flooding, Cyber, Power Outage',
            # 'required': 'required',
        })
    )
    channels = forms.ChoiceField(
        label="Preferred Communication Channels",
        required=True,
        choices=[
            ('', 'Select a channel'),
            ('email', 'Email Only'),
            ('email_sms', 'Email + SMS'),
            ('slack', 'Slack / Teams Webhook'),
        ],
        widget=forms.Select(attrs={
            'class': 'form-control',
            'required': 'required',
        })
    )
    number_of_users = forms.IntegerField(
        label="Number of Users",
        min_value=1,
        initial=1,
        required=True,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'e.g. 10',
            'min': '1',
            # 'required': 'required',
        })
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Department dropdown: core_department.category
        departments = (
            Department.objects.values_list("category", flat=True)
            .distinct()
            .order_by("category")
        )
        self.fields["dept"].choices = [("", "Select department")] + [(d, d) for d in departments if d]

        # Cascading Sub Department dropdown: core_department.service_name filtered by selected category
        if self.is_bound:
            selected_dept = (self.data.get("dept") or "").strip()
        else:
            selected_dept = (self.initial.get("dept") or "").strip()

        services = []
        if selected_dept:
            services = (
                Department.objects.filter(category=selected_dept)
                .values_list("service_name", flat=True)
                .distinct()
                .order_by("service_name")
            )

        self.fields["sub_department"].choices = [("", "Select sub department")] + [
            (s, s) for s in services if s
        ]

        # State dropdown: core states table
        states = (
            State.objects.values_list("state_id", "state_name")
            .order_by("state_name")
        )
        self.fields["state"].choices = [("", "Select state")] + [
            (str(state_id), state_name) for state_id, state_name in states if state_id
        ]

        # County dropdown: core counties filtered by selected state_id
        if self.is_bound:
            selected_state_id = (self.data.get("state") or "").strip()
        else:
            selected_state_id = (self.initial.get("state") or "").strip()

        county_choices = [("", "Select county")]
        if selected_state_id:
            counties = (
                Counties.objects.filter(state_id=selected_state_id)
                .values_list("county_id", "county_name")
                .order_by("county_name")
            )
            county_choices += [
                (str(county_id), county_name) for county_id, county_name in counties if county_id
            ]
        self.fields["county"].choices = county_choices
    
    def clean_password(self):
        """Validate password requirements"""
        password = self.cleaned_data.get('password')
        if password:
            if not PASSWORD_REGEX.match(password):
                raise ValidationError(
                    'Password must be at least 6 characters and include '
                    'uppercase, lowercase, number, and special character.'
                )
        
        return password

    def clean_agency(self):
        value = (self.cleaned_data.get('agency') or '').strip()
        if not value:
            raise ValidationError('Please enter your agency or organization name.')
        if value.isdigit():
            raise ValidationError('Agency / Organization name cannot be only numbers. Please include letters.')
        return value

    def clean_liaison_name(self):
        value = (self.cleaned_data.get('liaison_name') or '').strip()
        if not value:
            raise ValidationError("Please enter the primary liaison's name.")
        return value

    def clean_role(self):
        value = (self.cleaned_data.get('role') or '').strip()
        if not value:
            raise ValidationError("Please enter the liaison's role.")
        return value

    def clean_dept(self):
        value = (self.cleaned_data.get('dept') or '').strip()
        if not value:
            raise ValidationError('Please select the department.')
        return value

    def clean_sub_department(self):
        dept = (self.cleaned_data.get("dept") or "").strip()
        value = (self.cleaned_data.get("sub_department") or "").strip()
        if not value:
            raise ValidationError("Please select the sub department.")
        # Ensure chosen sub_department belongs to chosen department
        if dept and not Department.objects.filter(category=dept, service_name=value).exists():
            raise ValidationError("Selected sub department is not valid for the chosen department.")
        return value

    def clean_state(self):
        value = (self.cleaned_data.get('state') or '').strip()
        if not value:
            raise ValidationError('Please select the state.')
        if not State.objects.filter(state_id=value).exists():
            raise ValidationError('Selected state is invalid.')
        return value

    def clean_county(self):
        county_id = (self.cleaned_data.get('county') or '').strip()
        if not county_id:
            raise ValidationError('Please select the county.')

        state_id = (self.cleaned_data.get('state') or '').strip()
        if state_id and not Counties.objects.filter(state_id=state_id, county_id=county_id).exists():
            raise ValidationError('Selected county is not valid for the chosen state.')

        return county_id

    def clean_incidents(self):
        value = (self.cleaned_data.get('incidents') or '').strip()
        if not value:
            raise ValidationError('Please list your key incident types of concern.')
        return value

    def clean_number_of_users(self):
        num = self.cleaned_data.get('number_of_users')
        if num is None or num <= 0:
            raise ValidationError('Number of users must be greater than 0.')
        return num

    def clean(self):
        cleaned = super().clean()
        password = cleaned.get('password') or ''
        confirm = cleaned.get('confirm_password') or ''

        if password and confirm and password != confirm:
            self.add_error('confirm_password', 'Passwords do not match.')

        return cleaned
    
    def clean(self):
        """Validate that passwords match"""
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        confirm_password = cleaned_data.get('confirm_password')
        
        if password and confirm_password:
            if password != confirm_password:
                raise ValidationError({'confirm_password': 'Passwords do not match.'})
        
        return cleaned_data


def luhn_algorithm(card_number):
    """Validate credit card number using Luhn algorithm"""
    card_number = re.sub(r'\D', '', card_number)
    if not card_number:
        return False
    
    def luhn_check(card_num):
        def digits_of(n):
            return [int(d) for d in str(n)]
        digits = digits_of(card_num)
        odd_digits = digits[-1::-2]
        even_digits = digits[-2::-2]
        checksum = sum(odd_digits)
        for d in even_digits:
            checksum += sum(digits_of(d * 2))
        return checksum % 10 == 0
    
    return luhn_check(card_number)


class PaymentForm(forms.Form):
    """Payment form with dynamic validation for Invoice, ACH, and Credit Card"""
    PAYMENT_METHOD_CHOICES = [
        ('INVOICE', 'Invoice - Net 30'),
        ('ACH', 'ACH (Bank Transfer)'),
        ('CARD', 'Credit Card'),
    ]
    
    payment_method = forms.ChoiceField(
        label="Payment Method",
        choices=PAYMENT_METHOD_CHOICES,
        initial='INVOICE',
        widget=forms.Select(attrs={'class': 'form-control', 'id': 'id_payment_method'})
    )
    
    # Common fields
    billing_email = forms.EmailField(
        label="Billing Email",
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'billing@agency.com'
        })
    )
    
    # Invoice fields
    billing_entity_name = forms.CharField(
        label="Billing Entity Name",
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Organization or Company Name'
        })
    )
    po_number = forms.CharField(
        label="PO Number",
        required=False,
        max_length=100,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Purchase Order Number'
        })
    )
    
    # ACH fields
    account_holder_name = forms.CharField(
        label="Account Holder Name",
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Name on Account'
        })
    )
    bank_name = forms.CharField(
        label="Bank Name",
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Bank Name'
        })
    )
    routing_number = forms.CharField(
        label="Routing Number",
        required=False,
        max_length=9,
        min_length=9,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': '9-digit routing number',
            'pattern': '[0-9]{9}'
        })
    )
    account_number = forms.CharField(
        label="Account Number",
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Account Number'
        })
    )
    
    # Credit Card fields
    cardholder_name = forms.CharField(
        label="Cardholder Name",
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Name on Card'
        })
    )
    card_number = forms.CharField(
        label="Card Number",
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': '0000 0000 0000 0000',
            'maxlength': '19'
        })
    )
    expiry_date = forms.CharField(
        label="Expiry Date",
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'MM/YY',
            'maxlength': '5'
        })
    )
    cvv = forms.CharField(
        label="CVV",
        required=False,
        max_length=4,
        min_length=3,
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': '123',
            'maxlength': '4'
        })
    )
    billing_address = forms.CharField(
        label="Billing Address",
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 2,
            'placeholder': 'Street Address, City, State, ZIP'
        })
    )
    
    def clean_routing_number(self):
        """Validate routing number"""
        routing_number = self.cleaned_data.get('routing_number', '').strip()
        if routing_number:
            if not routing_number.isdigit():
                raise ValidationError('Routing number must contain only digits.')
            if len(routing_number) != 9:
                raise ValidationError('Routing number must be exactly 9 digits.')
        return routing_number
    
    def clean_account_number(self):
        """Validate account number"""
        account_number = self.cleaned_data.get('account_number', '').strip()
        if account_number:
            if not account_number.isdigit():
                raise ValidationError('Account number must contain only digits.')
            if len(account_number) < 4 or len(account_number) > 17:
                raise ValidationError('Account number must be between 4 and 17 digits.')
        return account_number
    
    def clean_card_number(self):
        """Validate card number using Luhn algorithm"""
        card_number = self.cleaned_data.get('card_number', '').strip()
        if card_number:
            if not luhn_algorithm(card_number):
                raise ValidationError('Invalid card number. Please check and try again.')
        return card_number
    
    def clean_expiry_date(self):
        """Validate expiry date is in the future"""
        expiry_date = self.cleaned_data.get('expiry_date', '').strip()
        if expiry_date:
            try:
                month, year = expiry_date.split('/')
                month = int(month)
                year = int(year)
                if year < 100:
                    year += 2000
                
                expiry = datetime(year, month, 1)
                # Get last day of month
                if month == 12:
                    expiry = expiry.replace(day=31)
                else:
                    next_month = expiry.replace(month=month + 1)
                    expiry = (next_month - timedelta(days=1))
                
                if expiry < datetime.now():
                    raise ValidationError('Card has expired. Please use a valid card.')
            except (ValueError, IndexError):
                raise ValidationError('Invalid date format. Please use MM/YY format.')
        return expiry_date
    
    def clean_cvv(self):
        """Validate CVV length"""
        cvv = self.cleaned_data.get('cvv', '').strip()
        if cvv:
            if not cvv.isdigit():
                raise ValidationError('CVV must contain only digits.')
            if len(cvv) not in [3, 4]:
                raise ValidationError('CVV must be 3 or 4 digits.')
        return cvv
    
    def clean(self):
        """Dynamic validation based on payment method"""
        cleaned_data = super().clean()
        payment_method = cleaned_data.get('payment_method')
        
        if payment_method == 'INVOICE':
            # Invoice requires: billing_entity_name, po_number, billing_email
            if not cleaned_data.get('billing_entity_name'):
                self.add_error('billing_entity_name', 'Billing entity name is required for invoice payments.')
            if not cleaned_data.get('po_number'):
                self.add_error('po_number', 'PO number is required for invoice payments.')
            if not cleaned_data.get('billing_email'):
                self.add_error('billing_email', 'Billing email is required.')
        
        elif payment_method == 'ACH':
            # ACH requires: account_holder_name, bank_name, routing_number, account_number, billing_email
            if not cleaned_data.get('account_holder_name'):
                self.add_error('account_holder_name', 'Account holder name is required for ACH payments.')
            if not cleaned_data.get('bank_name'):
                self.add_error('bank_name', 'Bank name is required for ACH payments.')
            if not cleaned_data.get('routing_number'):
                self.add_error('routing_number', 'Routing number is required for ACH payments.')
            if not cleaned_data.get('account_number'):
                self.add_error('account_number', 'Account number is required for ACH payments.')
            if not cleaned_data.get('billing_email'):
                self.add_error('billing_email', 'Billing email is required.')
        
        elif payment_method == 'CARD':
            # Credit Card requires: cardholder_name, card_number, expiry_date, cvv, billing_address, billing_email
            if not cleaned_data.get('cardholder_name'):
                self.add_error('cardholder_name', 'Cardholder name is required for credit card payments.')
            if not cleaned_data.get('card_number'):
                self.add_error('card_number', 'Card number is required for credit card payments.')
            if not cleaned_data.get('expiry_date'):
                self.add_error('expiry_date', 'Expiry date is required for credit card payments.')
            if not cleaned_data.get('cvv'):
                self.add_error('cvv', 'CVV is required for credit card payments.')
            if not cleaned_data.get('billing_address'):
                self.add_error('billing_address', 'Billing address is required for credit card payments.')
            if not cleaned_data.get('billing_email'):
                self.add_error('billing_email', 'Billing email is required.')
        
        return cleaned_data


class OnboardingForm(forms.ModelForm):
    """Onboarding form for initial setup"""
    distribution_list = forms.CharField(
        label="Stakeholder Distribution List",
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'Enter emails separated by commas...'
        }),
        help_text="Comma-separated email addresses"
    )
    
    cadence_hours = forms.ChoiceField(
        label='Shift Packet Cadence (Hours)',
        choices=[(24, 'Every 24 Hours (Standard)'), (12, 'Every 12 Hours'), (8, 'Every 8 Hours (High Tempo)')],
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    
    class Meta:
        model = SystemSettings
        fields = ['cadence_hours']


class OperationalUpdateForm(forms.ModelForm):
    """Form for creating operational updates"""
    start_time = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(attrs={
            'class': 'form-control',
            'type': 'datetime-local',
            'placeholder': 'mm/dd/yyyy'
        }),
        label='Start Time'
    )
    end_time = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(attrs={
            'class': 'form-control',
            'type': 'datetime-local',
            'placeholder': 'mm/dd/yyyy'
        }),
        label='End Time'
    )
    shift = forms.ChoiceField(
        required=False,
        choices=[
            ('', 'Select Shift'),
            ('1', '1'),
            ('2', '2'),
            ('3', '3'),
            ('4', '4'),
            ('6', '6'),
            ('8', '8'),
            ('10', '10'),
            ('12', '12'),
            ('16', '16'),
            ('18', '18'),
            ('24', '24'),
            ('48', '48'),
            ('72', '72'),
        ],
        widget=forms.Select(attrs={
            'class': 'form-control',
            'style': 'width: auto; min-width: 120px; display: inline-block;',
        }),
        label='Shift'
    )
    
    class Meta:
        model = OperationalUpdate
        fields = ['title', 'severity', 'description', 'impact', 'next_action']
        labels = {
            'title': 'Update Title',
            'severity': 'Severity',
            'description': 'What Changed?',
            'impact': 'Why it Matters (Impact)',
            'next_action': 'Next Action',
        }
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., Road Closure at Sector 4'
            }),
            'severity': forms.Select(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Describe the situation...'
            }),
            'impact': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'Operational impact analysis...'
            }),
            'next_action': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'e.g., Dispatch team, Monitor sensors'
            }),
        }


class CreateIncidentForm(forms.Form):
    """Form for new incident creation - maps to incident management DB columns."""
    title = forms.CharField(
        required=True,
        label='Title',
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'e.g., WannaCry Ransomware Attack',
        }),
    )
    description = forms.CharField(
        required=False,
        label='Description',
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'Describe the incident...',
        }),
    )
    category = forms.ChoiceField(
        required=False,
        label="Category",
        choices=[("", "Select category")],
        widget=forms.Select(
            attrs={
                "class": "form-control",
                "id": "incidentCategorySelect",
            }
        ),
    )
    sub_category = forms.ChoiceField(
        required=False,
        label="Sub Category",
        choices=[("", "Select sub category")],
        widget=forms.Select(
            attrs={
                "class": "form-control",
                "id": "incidentSubCategorySelect",
            }
        ),
    )
    severity = forms.ChoiceField(
        required=True,
        label='Severity',
        choices=[
            ('LOW', 'Low '),
            ('MEDIUM', 'Medium '),
            ('HIGH', 'High '),
            ('CRITICAL', 'Critical'),
        ],
        widget=forms.Select(attrs={'class': 'form-control'}),
    )
    status = forms.ChoiceField(
        required=True,
        label='Status',
        choices=[
            ('new', 'New'),
            ('open', 'Open'),
            ('in_progress', 'In Progress'),
            ('investigating', 'Investigating'),
            ('on_hold', 'On Hold'),
            ('resolved', 'Resolved'),
            ('closed', 'Closed'),
            ('reopened', 'Reopened'),
            ('escalated', 'Escalated'),
            ('cancelled', 'Cancelled'),
        ],
        initial='open',
        widget=forms.Select(attrs={'class': 'form-control'}),
    )
    reported_time = forms.DateTimeField(
        required=False,
        label='Reported Time',
        widget=forms.DateTimeInput(attrs={
            'class': 'form-control',
            'type': 'datetime-local',
        }),
    )
    reported_by = forms.CharField(
        required=False,
        label='Reported By',
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Name or designation',
            'readonly': 'readonly',
        }),
    )
    location = forms.CharField(
        required=False,
        label='Location',
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'e.g., County-wide',
        }),
    )
    zipcode = forms.CharField(
        required=False,
        label='Zipcode',
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'e.g., 12345',
        }),
    )
    impact = forms.CharField(
        required=False,
        label='Impact',
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 2,
            'placeholder': 'Why it matters - operational impact...',
        }),
    )
    casualties = forms.CharField(
        required=False,
        label='Casualties',
        initial='0',
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'If applicable',
        }),
    )
    source = forms.ChoiceField(
        required=False,
        label='Source',
        choices=[
            ('', 'Select source'),
            ('police', 'Police Station'),
            ('control_room', 'Control Room'),
            ('fire', 'Fire Department'),
            ('ambulance', 'Ambulance Service'),
            ('public', 'Public'),
            ('witness', 'Witness'),
            ('internal', 'Internal Staff'),
            ('security', 'Security Team'),
            ('ngo', 'NGO'),
            ('media', 'Media'),
            ('other', 'Other'),
        ],
        widget=forms.Select(attrs={'class': 'form-control'}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        categories = (
            Department.objects.values_list("category", flat=True)
            .distinct()
            .order_by("category")
        )
        self.fields["category"].choices = [("", "Select category")] + [
            (c, c) for c in categories if c
        ]

        if self.is_bound:
            selected_category = (self.data.get("category") or "").strip()
        else:
            selected_category = (self.initial.get("category") or "").strip()

        services = []
        if selected_category:
            services = (
                Department.objects.filter(category=selected_category)
                .values_list("service_name", flat=True)
                .distinct()
                .order_by("service_name")
            )

        self.fields["sub_category"].choices = [("", "Select sub category")] + [
            (s, s) for s in services if s
        ]

    shift_cadence_hours = forms.ChoiceField(
        required=False,
        label='Shift Packet (hours)',
        choices=[(h, f"{h}") for h in [1, 2, 3, 4, 6, 8, 10, 12, 18, 24, 48, 72]],
        initial="8",
        widget=forms.Select(attrs={'class': 'form-control'}),
    )


class UserSignupForm(forms.ModelForm):
    """Form for user registration: username, password, confirm password only."""
    password = forms.CharField(
        label='Password',
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Password'
        })
    )
    confirm_password = forms.CharField(
        label='Confirm password',
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Confirm Password'
        })
    )

    class Meta:
        model = UserCredentials
        fields = ['username']
        widgets = {
            'username': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Username'
            }),
        }

    def clean_username(self):
        """Ensure only one account per username."""
        username = self.cleaned_data.get('username', '').strip()
        if not username:
            raise forms.ValidationError('Username is required.')
        if UserCredentials.objects.filter(username=username).exists():
            raise forms.ValidationError(
                'This username is already registered. Please sign in or choose a different username.'
            )
        return username

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        confirm_password = cleaned_data.get("confirm_password")

        if password != confirm_password:
            raise forms.ValidationError("Passwords do not match")
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.password_hash = self.cleaned_data["password"] # Store plain text
        if commit:
            user.save()
        return user


class UserLoginForm(forms.Form):
    """Form for user login"""
    username = forms.CharField(widget=forms.TextInput(attrs={
        'class': 'form-control',
        'placeholder': 'Username'
    }))
    password = forms.CharField(widget=forms.PasswordInput(attrs={
        'class': 'form-control',
        'placeholder': 'Password'
    }))


class ProfileEditForm(forms.Form):
    """Edit profile for Django auth users: photo, username, email, organization, mobile. No password."""
    profile_photo = forms.ImageField(
        label="Profile photo",
        required=False,
        widget=forms.FileInput(attrs={
            'class': 'form-control',
            'accept': 'image/jpeg,image/png,image/gif,image/webp',
        })
    )
    username = forms.CharField(
        max_length=150,
        label="Username",
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Username',
        })
    )
    email = forms.EmailField(
        label="Email",
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'email@example.com',
        })
    )
    organization_name = forms.CharField(
        max_length=255,
        label="Organization name",
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Organization / Agency name',
        })
    )
    mobile_number = forms.CharField(
        max_length=20,
        required=False,
        label="Mobile number",
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Mobile number',
        })
    )


class LegacyProfileEditForm(forms.Form):
    """Edit profile for legacy UserCredentials users: photo, username, email, organization, mobile. No password."""
    profile_photo = forms.ImageField(
        label="Profile photo",
        required=False,
        widget=forms.FileInput(attrs={
            'class': 'form-control',
            'accept': 'image/jpeg,image/png,image/gif,image/webp',
        })
    )
    username = forms.CharField(
        max_length=100,
        label="Username",
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Username / email',
        })
    )
    email = forms.EmailField(
        label="Email",
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'email@example.com',
        })
    )
    organization_name = forms.CharField(
        max_length=255,
        required=False,
        label="Organization name",
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Organization / Agency name',
        })
    )
    mobile_number = forms.CharField(
        max_length=20,
        required=False,
        label="Mobile number",
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Mobile number',
        })
    )


class UserCreateForm(forms.ModelForm):
    """Form for creating users with full profile information"""
    password = forms.CharField(
        label='Password',
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter password'
        }),
        required=True
    )
    confirm_password = forms.CharField(
        label='Confirm Password',
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Confirm password'
        }),
        required=True
    )
    
    class Meta:
        model = UserProfile
        fields = ['full_name', 'mobile', 'email', 'role', 'department', 'shift_start_time', 'shift_end_time', 'designated_manager']
        widgets = {
            'full_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Full Name'
            }),
            'mobile': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Mobile Number'
            }),
            'email': forms.EmailInput(attrs={
                'class': 'form-control',
                'placeholder': 'Email Address'
            }),
            'role': forms.Select(attrs={
                'class': 'form-control'
            }),
            'department': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Department'
            }),
            'shift_start_time': forms.TimeInput(attrs={
                'class': 'form-control',
                'type': 'time'
            }),
            'shift_end_time': forms.TimeInput(attrs={
                'class': 'form-control',
                'type': 'time'
            }),
            'designated_manager': forms.Select(attrs={
                'class': 'form-control'
            }),
        }
        labels = {
            'full_name': 'Full Name',
            'mobile': 'Mobile',
            'email': 'Email',
            'role': 'Role',
            'department': 'Department',
            'shift_start_time': 'Shift Start Time',
            'shift_end_time': 'Shift End Time',
            'designated_manager': 'Designated Manager',
        }
    
    username = forms.CharField(
        label='Username',
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Username'
        }),
        required=True
    )
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Filter managers for designated_manager field
        manager_queryset = UserProfile.objects.filter(role__in=['admin', 'manager'])
        if self.instance and self.instance.pk:
            manager_queryset = manager_queryset.exclude(pk=self.instance.pk)
        self.fields['designated_manager'].queryset = manager_queryset
        self.fields['designated_manager'].required = False
        self.fields['designated_manager'].empty_label = "— No Manager —"
    
    def clean_username(self):
        username = self.cleaned_data.get('username', '').strip()
        if not username:
            raise forms.ValidationError('Username is required.')
        if UserCredentials.objects.filter(username=username).exists():
            raise forms.ValidationError('This username is already taken.')
        return username
    
    def clean_email(self):
        email = self.cleaned_data.get('email', '').strip()
        if not email:
            raise forms.ValidationError('Email is required.')
        if UserProfile.objects.filter(email=email).exists():
            raise forms.ValidationError('This email is already registered.')
        return email
    
    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        confirm_password = cleaned_data.get("confirm_password")
        
        if password != confirm_password:
            raise forms.ValidationError("Passwords do not match")
        
        shift_start = cleaned_data.get('shift_start_time')
        shift_end = cleaned_data.get('shift_end_time')
        
        if shift_start and shift_end and shift_start >= shift_end:
            raise forms.ValidationError("Shift end time must be after shift start time")
        
        return cleaned_data
    
    def save(self, commit=True):
        # Create UserCredentials first
        username = self.cleaned_data['username']
        password = self.cleaned_data['password']
        
        user_credential = UserCredentials.objects.create(
            username=username,
            password_hash=password  # Store plain text as per existing pattern
        )
        
        # Create UserProfile
        profile = super().save(commit=False)
        profile.user_credential = user_credential
        
        if commit:
            profile.save()
        
        return profile


class SetupPasswordForm(forms.Form):
    """Form for setting password from email link"""
    new_password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'New password',
            'autocomplete': 'new-password',
        }),
        min_length=8,
        label='New password',
    )
    confirm_password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Confirm password',
            'autocomplete': 'new-password',
        }),
        label='Confirm password',
    )

    def clean(self):
        data = super().clean()
        if data.get('new_password') != data.get('confirm_password'):
            raise forms.ValidationError('Passwords do not match.')
        return data


class CompleteRegistrationForm(forms.Form):
    """Form shown after onboarding: set username and password (with validation)."""
    username = forms.CharField(
        max_length=150,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Choose a username',
            'autocomplete': 'username',
        }),
        label='Username',
    )
    new_password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'New password',
            'autocomplete': 'new-password',
        }),
        label='New password',
        help_text='At least 8 characters With at least one uppercase letter, one lowercase letter, and one number.',
    )
    confirm_password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Confirm password',
            'autocomplete': 'new-password',
        }),
        label='Confirm password',
    )

    def __init__(self, *args, current_user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.current_user = current_user
        if current_user and not (args and args[0]):
            self.fields['username'].initial = getattr(current_user, 'username', '')

    def clean_username(self):
        data = self.cleaned_data.get('username', '').strip()
        if not data:
            raise forms.ValidationError('Username is required.')
        if not all(c.isalnum() or c in '@.+-_' for c in data):
            raise forms.ValidationError('Username can only contain letters, digits, and @/./+/-/_.')
        if User.objects.filter(username=data).exclude(pk=getattr(self.current_user, 'pk', None)).exists():
            raise forms.ValidationError('This username is already taken.')
        return data

    def clean_new_password(self):
        data = self.cleaned_data.get('new_password')
        if data:
            validate_password(data, self.current_user)
        return data

    def clean(self):
        data = super().clean()
        if data.get('new_password') != data.get('confirm_password'):
            raise forms.ValidationError('Passwords do not match.')
        return data


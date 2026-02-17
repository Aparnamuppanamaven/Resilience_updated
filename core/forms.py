"""
Forms for Resilience System
"""
from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
<<<<<<< HEAD
from django.utils import timezone
from datetime import datetime, timedelta
import re
from .models import OperationalUpdate, SystemSettings, UserCredentials, Payment, Invoice
=======
from datetime import datetime, timedelta
from .models import OperationalUpdate, SystemSettings, UserCredentials
import re
>>>>>>> 0d956f9 (Latest changes)


class CheckoutForm(forms.Form):
    """Checkout form for Foundation purchase"""
    agency = forms.CharField(
        max_length=255,
        label="Agency / Organization Name",
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'e.g. North District Ops'
        })
    )
    liaison_name = forms.CharField(
        max_length=255,
        label="Primary Liaison Name",
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Full Name'
        })
    )
    liaison_email = forms.EmailField(
        label="Liaison Email (Primary Contact)",
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'email@agency.com'
        })
    )
    incidents = forms.CharField(
        label="Key Incident Types of Concern",
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'e.g. Flooding, Cyber, Power Outage'
        })
    )
    channels = forms.ChoiceField(
        label="Preferred Communication Channels",
        choices=[
            ('email', 'Email Only'),
            ('email_sms', 'Email + SMS'),
            ('slack', 'Slack / Teams Webhook'),
        ],
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    number_of_users = forms.IntegerField(
        label="Number of Users",
        min_value=0,
        initial=0,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'e.g. 10'
        })
    )


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
    class Meta:
        model = OperationalUpdate
        fields = ['title', 'severity', 'description', 'impact', 'next_action']
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
            'next_action': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., Dispatch team, Monitor sensors'
            }),
        }


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


"""
Forms for Resilience System
"""
from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from .models import OperationalUpdate, SystemSettings, UserCredentials


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


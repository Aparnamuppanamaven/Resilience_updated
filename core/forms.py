"""
Forms for Resilience System
"""
from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
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
    """Form for user registration"""
    password = forms.CharField(widget=forms.PasswordInput(attrs={
        'class': 'form-control',
        'placeholder': 'Password'
    }))
    confirm_password = forms.CharField(widget=forms.PasswordInput(attrs={
        'class': 'form-control',
        'placeholder': 'Confirm Password'
    }))

    class Meta:
        model = UserCredentials
        fields = ['username', 'password_hash']
        widgets = {
            'username': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Username'
            }),
        }
        labels = {
            'password_hash': 'Password'
        }

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


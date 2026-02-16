"""
Views for Resilience System
Enterprise-level views
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.utils import timezone
from django.db.models import Q
from django.http import JsonResponse
from datetime import timedelta
import random

from django.core.mail import send_mail
from django.conf import settings as django_settings

from .models import (
    Organization, Liaison, OperationalUpdate, 
    Decision, SystemSettings, ShiftPacket,
    ExternalUser, ExternalPayment, ExternalSubscription, UserCredentials
)
from .forms import CheckoutForm, OnboardingForm, OperationalUpdateForm, UserSignupForm, UserLoginForm, SetupPasswordForm, CompleteRegistrationForm
from .password_token import make_setup_password_token, get_user_from_setup_password_token


def index(request):
    """Landing page"""
    return render(request, 'core/index.html')


def checkout(request):
    """Checkout page for Foundation purchase"""
    if request.method == 'POST':
        form = CheckoutForm(request.POST)
        if form.is_valid():
            # Store data in session
            request.session['checkout_data'] = form.cleaned_data
            # Convert UUIDs/Models to strings/IDs if necessary (Django forms clean data usually returns objects)
            # However, for CharFields/ChoiceFields it's fine. 
            # Check if any fields need serialization. Warning: valid form data might contain custom objects.
            # Here it seems standard.
            
            # Simple direct redirect to payment
            return redirect('payment')
    else:
        form = CheckoutForm()
    
    return render(request, 'core/checkout.html', {'form': form})


def payment(request):
    """Payment page with dummy gateway"""
    checkout_data = request.session.get('checkout_data')
    if not checkout_data:
        messages.error(request, 'Session expired or invalid. Please checkout again.')
        return redirect('checkout')

    if request.method == 'POST':
        # Simulate payment success
        # Retrieve form data
        agency = checkout_data['agency']
        liaison_name = checkout_data['liaison_name']
        liaison_email = checkout_data['liaison_email']
        channels = checkout_data['channels']
        incidents = checkout_data['incidents']

        # Create organization
        org = Organization.objects.create(
            name=agency,
            license_type='foundation',
            foundation_purchase_date=timezone.now()
        )
        
        # Create user account
        username = liaison_email.split('@')[0]  # Use email prefix as username
        
        # Check if user already exists
        user, created = User.objects.get_or_create(
            username=username,
            defaults={
                'email': liaison_email,
                'first_name': liaison_name.split()[0] if liaison_name.split() else '',
                'last_name': ' '.join(liaison_name.split()[1:]) if len(liaison_name.split()) > 1 else '',
            }
        )
        
        if not created:
            # User exists, update email
            user.email = liaison_email
            user.save()
        
        # Set a default password (in production, send password reset email)
        user.set_password('resilience2024!')
        user.save()
        
        # Create or update liaison profile
        Liaison.objects.update_or_create(
            user=user,
            defaults={
                'organization': org,
                'preferred_channels': channels,
                'incident_types': incidents
            }
        )
        
        # Create default settings
        SystemSettings.objects.get_or_create(
            organization=org,
            defaults={'cadence_hours': 24}
        )
        
        # --- Populate Legacy Tables ---
        try:
            # 1. Users
            ext_user = ExternalUser.objects.create(
                agency_name=agency,
                primary_liaison_name=liaison_name,
                liaison_email=liaison_email,
                key_incident_types=incidents,
                preferred_communication_channels=channels,
                created_at=timezone.now()
            )
            
            # 2. Payments
            payment_method_selected = request.POST.get('payment_method', 'Credit Card')
            ext_payment = ExternalPayment.objects.create(
                username=username,
                payment_status='Completed',
                payment_method=payment_method_selected,
                amount=7500.00,
                payment_time=timezone.now()
            )
            
            # 3. Subscriptions
            ExternalSubscription.objects.create(
                username=username,
                payment=ext_payment,
                subscription_type='Foundation',
                duration=365,
                subscription_start_date=timezone.now().date(),
                subscription_end_date=timezone.now().date() + timedelta(days=365),
                subscription_status='Active',
                created_at=timezone.now()
            )
        except Exception as e:
            # Log error but don't fail the main flow
            print(f"Error populating legacy tables: {e}") 
        # -----------------------------
        
        # Auto-login user
        user = authenticate(username=username, password='resilience2024!')
        if user:
            login(request, user)
            # Clear session
            request.session.pop('checkout_data', None)
            messages.success(request, 'Payment successful! Account created.')
            return redirect('onboarding')

    return render(request, 'core/payment.html')


@login_required
def onboarding(request):
    """Onboarding page for initial setup"""
    try:
        liaison = request.user.liaison_profile
        organization = liaison.organization
        settings_obj = organization.settings
    except Liaison.DoesNotExist:
        messages.error(request, 'Please complete checkout first.')
        return redirect('checkout')
    
    if request.method == 'POST':
        form = OnboardingForm(request.POST, instance=settings_obj)
        if form.is_valid():
            settings_obj.cadence_hours = int(form.cleaned_data['cadence_hours'])
            settings_obj.distribution_list = form.cleaned_data.get('distribution_list', '')
            settings_obj.save()
            # Send "registration completed" email to checkout email with setup-password link
            user = request.user
            to_email = user.email or getattr(liaison.user, 'email', None)
            if to_email:
                token = make_setup_password_token(user)
                setup_url = request.build_absolute_uri(reverse('setup_password', kwargs={'token': token}))
                try:
                    send_mail(
                        subject='Resilience – Registration completed – set up your password',
                        message=(
                            f'Hi {user.get_full_name() or user.username},\n\n'
                            'Your Resilience Foundation registration is complete.\n\n'
                            'Set up your password using the link below (valid for 7 days):\n\n'
                            f'{setup_url}\n\n'
                            'If you did not request this, you can ignore this email.\n\n'
                            '— Resilience Team'
                        ),
                        from_email=getattr(django_settings, 'DEFAULT_FROM_EMAIL', 'noreply@resilience.example.com'),
                        recipient_list=[to_email],
                        fail_silently=True,
                    )
                except Exception:
                    pass
            messages.success(request, 'Onboarding completed! Set up your username and password below.')
            return redirect('complete_registration')
    else:
        form = OnboardingForm(instance=settings_obj)
        form.fields['cadence_hours'].initial = str(settings_obj.cadence_hours)
        form.fields['distribution_list'].initial = settings_obj.distribution_list
    
    return render(request, 'core/onboarding.html', {
        'form': form,
        'liaison': liaison
    })


def registration_success(request):
    """Registration success page"""
    return render(request, 'core/registration_success.html')


@login_required
def complete_registration(request):
    """Page after onboarding: set username and password (with validation)."""
    user = request.user
    try:
        request.user.liaison_profile
    except Liaison.DoesNotExist:
        messages.error(request, 'Please complete checkout and onboarding first.')
        return redirect('checkout')
    form = CompleteRegistrationForm(request.POST or None, current_user=user)
    if request.method == 'POST' and form.is_valid():
        user.username = form.cleaned_data['username'].strip()
        user.set_password(form.cleaned_data['new_password'])
        user.save()
        logout(request)
        messages.success(request, 'Account set up successfully. Please log in with your new username and password.')
        return redirect('login')
    return render(request, 'core/complete_registration.html', {'form': form})


def payment_failed(request):
    """Payment failed page"""
    return render(request, 'core/payment_failed.html')


def dashboard(request):
    """Main dashboard"""
    
    context = {}
    
    # Pathway 1: Standard Django Auth (Liaison)
    if request.user.is_authenticated:
        try:
            liaison = request.user.liaison_profile
            organization = liaison.organization
            settings_obj = organization.settings
        except Liaison.DoesNotExist:
            messages.error(request, 'Please complete checkout first.')
            return redirect('checkout')

    # Pathway 2: Legacy Session Auth (UserCredentials)
    elif 'user_credentials_id' in request.session:
        try:
            organization = Organization.objects.first()
            if not organization:
                organization = Organization.objects.create(name="Demo Agency")
                SystemSettings.objects.create(organization=organization)
            settings_obj, _ = SystemSettings.objects.get_or_create(
                organization=organization,
                defaults={'cadence_hours': 24}
            )
            # Mock user for template (avoid closure in nested class)
            org_for_mock = organization
            class MockProfile:
                organization = None
            MockProfile.organization = org_for_mock
            class MockUser:
                username = request.session.get('user_credentials_username', 'Guest')
                first_name = request.session.get('user_credentials_username', 'Guest')
                last_name = ""
                is_authenticated = True
                is_staff = False  # so Admin module is hidden for UserCredentials users
                liaison_profile = MockProfile()
                def get_full_name(self):
                    return self.username
            request.user = MockUser()
        except Exception as e:
            messages.error(request, f'Error loading dashboard: {e}')
            return redirect('login')

    # Pathway 3: Not Authenticated
    else:
        return redirect('login')
    
    # Common Dashboard Logic (runs for both pathways)
    
    # Calculate next packet due
    last_sync = settings_obj.last_sync
    next_packet_due = last_sync + timedelta(hours=settings_obj.cadence_hours)
    time_remaining = max(0, (next_packet_due - timezone.now()).total_seconds() / 3600)
    
    # Get recent updates
    recent_updates = OperationalUpdate.objects.filter(
        organization=organization
    ).order_by('-timestamp')[:3]
    
    context = {
        'organization': organization,
        'settings': settings_obj,
        'time_remaining': round(time_remaining, 1),
        'recent_updates': recent_updates,
        'pending_updates_count': OperationalUpdate.objects.filter(
            organization=organization,
            timestamp__gte=last_sync
        ).count(),
    }
    
    return render(request, 'core/dashboard.html', context)


@login_required
def capture(request):
    """Capture new operational update"""
    try:
        liaison = request.user.liaison_profile
        organization = liaison.organization
    except Liaison.DoesNotExist:
        messages.error(request, 'Please complete checkout first.')
        return redirect('checkout')
    
    if request.method == 'POST':
        form = OperationalUpdateForm(request.POST)
        if form.is_valid():
            update = form.save(commit=False)
            update.organization = organization
            update.owner = liaison
            update.save()
            messages.success(request, 'Update captured successfully!')
            return redirect('dashboard')
    else:
        form = OperationalUpdateForm()
    
    return render(request, 'core/capture.html', {'form': form})


@login_required
def normalize(request):
    """Normalize view - show all updates"""
    try:
        liaison = request.user.liaison_profile
        organization = liaison.organization
    except Liaison.DoesNotExist:
        messages.error(request, 'Please complete checkout first.')
        return redirect('checkout')
    
    updates = OperationalUpdate.objects.filter(
        organization=organization
    ).order_by('-timestamp')
    
    return render(request, 'core/normalize.html', {'updates': updates})


@login_required
def distribute(request):
    """Distribute shift packet"""
    try:
        liaison = request.user.liaison_profile
        organization = liaison.organization
        settings_obj = organization.settings
    except Liaison.DoesNotExist:
        messages.error(request, 'Please complete checkout first.')
        return redirect('checkout')
    
    # Get updates since last sync
    updates = OperationalUpdate.objects.filter(
        organization=organization,
        timestamp__gte=settings_obj.last_sync
    ).order_by('-severity', '-timestamp')
    
    # Generate packet preview
    high_risk_updates = updates.exclude(severity='Low')
    
    if request.method == 'POST':
        # Generate and save shift packet
        packet_number = f"PKT-{random.randint(1000, 9999)}-{timezone.now().strftime('%Y%m%d')}"
        
        executive_summary = f"Operations remain stable. {updates.count()} new updates processed in the last cycle."
        
        key_risks = "\n".join([
            f"[{u.severity}] {u.title}: {u.description}"
            for u in high_risk_updates
        ]) if high_risk_updates.exists() else "No high risks identified."
        
        next_actions = f"Continue routine monitoring (Cadence: {settings_obj.cadence_hours}h)."
        
        packet = ShiftPacket.objects.create(
            organization=organization,
            packet_number=packet_number,
            status=settings_obj.current_status,
            executive_summary=executive_summary,
            key_risks=key_risks,
            next_actions=next_actions,
            sent_at=timezone.now()
        )
        
        # Update last sync
        settings_obj.last_sync = timezone.now()
        settings_obj.save()
        
        messages.success(request, f'Shift Packet #{packet_number} sent successfully!')
        return redirect('dashboard')
    
    context = {
        'organization': organization,
        'settings': settings_obj,
        'updates': updates,
        'high_risk_updates': high_risk_updates,
        'packet_number': f"PKT-{random.randint(1000, 9999)}-{timezone.now().strftime('%Y%m%d')}",
    }
    
    return render(request, 'core/distribute.html', context)


@login_required
def decision_log(request):
    """Decision log view"""
    try:
        liaison = request.user.liaison_profile
        organization = liaison.organization
    except Liaison.DoesNotExist:
        messages.error(request, 'Please complete checkout first.')
        return redirect('checkout')
    
    decisions = Decision.objects.filter(
        organization=organization
    ).order_by('-timestamp')
    
    return render(request, 'core/decision_log.html', {'decisions': decisions})


@login_required
def coverage(request):
    """Coverage & Communications view"""
    try:
        liaison = request.user.liaison_profile
        organization = liaison.organization
    except Liaison.DoesNotExist:
        messages.error(request, 'Please complete checkout first.')
        return redirect('checkout')
    
    return render(request, 'core/coverage.html', {
        'organization': organization,
        'liaison': liaison
    })


@login_required
def toggle_alert(request):
    """Toggle alert status (AJAX endpoint)"""
    try:
        liaison = request.user.liaison_profile
        organization = liaison.organization
        settings_obj = organization.settings
    except Liaison.DoesNotExist:
        return JsonResponse({'error': 'Unauthorized'}, status=403)
    
    if request.method == 'POST':
        if settings_obj.current_status == 'Normal':
            settings_obj.current_status = 'High Alert'
            settings_obj.current_phase = 1
            settings_obj.cadence_hours = 4
            
            # Log decision
            Decision.objects.create(
                organization=organization,
                decision="Activate Escalation Protocol",
                rationale="User manual activation mechanism triggered.",
                owner=liaison,
                status="Open"
            )
        else:
            settings_obj.current_status = 'Normal'
            settings_obj.current_phase = 0
            settings_obj.cadence_hours = 24
            
            # Log decision
            Decision.objects.create(
                organization=organization,
                decision="Deactivate Alert - Return to Normal",
                rationale="Manual deactivation.",
                owner=liaison,
                status="Closed"
            )
        
        settings_obj.save()
        
        return JsonResponse({
            'status': settings_obj.current_status,
            'phase': settings_obj.current_phase,
            'cadence': settings_obj.cadence_hours
        })
    
    return JsonResponse({'error': 'Invalid method'}, status=405)


def register_view(request):
    """User registration view for UserCredentials. One account per username only."""
    if request.method == 'POST':
        form = UserSignupForm(request.POST)
        if form.is_valid():
            try:
                form.save()
                messages.success(request, 'Registration successful! Please login.')
                return redirect('login')
            except Exception as e:
                if 'unique' in str(e).lower() or 'duplicate' in str(e).lower():
                    messages.error(request, 'This username is already registered. Please sign in or choose a different username.')
                else:
                    messages.error(request, 'Registration failed. Please try again.')
    else:
        form = UserSignupForm()
    return render(request, 'core/register.html', {'form': form})


def login_view(request):
    """User login: UserCredentials (legacy) or Django auth (Liaison after setup password)."""
    # Already logged in: do not show Sign In page; redirect so UI reflects logged-in status
    if request.user.is_authenticated or request.session.get('user_credentials_id'):
        return redirect('dashboard')
    if request.method == 'POST':
        form = UserLoginForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data['username']
            password = form.cleaned_data['password']
            # 1) Try UserCredentials (legacy table)
            try:
                user_cred = UserCredentials.objects.get(username=username, password_hash=password)
                request.session['user_credentials_id'] = user_cred.user_id
                request.session['user_credentials_username'] = user_cred.username
                messages.success(request, f'Welcome back, {user_cred.username}!')
                return redirect('dashboard')
            except UserCredentials.DoesNotExist:
                pass
            # 2) Try Django auth (Liaison users who set password via email link)
            user = authenticate(request, username=username, password=password)
            if user is not None:
                login(request, user)
                messages.success(request, f'Welcome back, {user.get_full_name() or user.username}!')
                return redirect('dashboard')
            messages.error(request, 'Invalid username or password.')
    else:
        form = UserLoginForm()
    return render(request, 'core/login.html', {'form': form})


def user_dashboard(request):
    """Simple dashboard for UserCredentials users"""
    user_id = request.session.get('user_credentials_id')
    username = request.session.get('user_credentials_username')
    
    if not user_id:
        messages.error(request, 'Please login first.')
        return redirect('login')
        
    return render(request, 'core/user_dashboard.html', {'username': username})


def _staff_required(user):
    return user.is_authenticated and user.is_staff


@login_required
@user_passes_test(_staff_required, login_url='/login/')
def admin_module(request):
    """Admin page: add and list users (UserCredentials). Staff only."""
    users_list = UserCredentials.objects.all().order_by('username')
    form = UserSignupForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, f'User "{form.cleaned_data["username"]}" added successfully.')
        return redirect('admin_module')
    return render(request, 'core/admin_module.html', {
        'users_list': users_list,
        'form': form,
    })


def logout_view(request):
    """Logout: clear auth and session, redirect to index (default state). No message displayed."""
    logout(request)
    request.session.flush()
    return redirect('index')


def setup_password(request, token):
    """Set password from email link (after registration completed)."""
    user = get_user_from_setup_password_token(token)
    if not user:
        messages.error(request, 'This link is invalid or has expired. Request a new one or contact support.')
        return redirect('login')
    form = SetupPasswordForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user.set_password(form.cleaned_data['new_password'])
        user.save()
        messages.success(request, 'Password set successfully. You can now log in.')
        return redirect('login')
    return render(request, 'core/setup_password.html', {'form': form})


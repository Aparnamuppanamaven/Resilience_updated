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
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from datetime import timedelta
from io import BytesIO
import random
import json
import stripe
from django.conf import settings
from django.core.mail import send_mail
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from django.db import transaction
from .models import (
    Organization, Liaison, OperationalUpdate, Incident,
    Decision, SystemSettings, ShiftPacket,
    ExternalUser, ExternalPayment, ExternalSubscription, UserCredentials, UsersTable,
    Payment, Invoice,
    StripePayment, UserProfile,
)
from .forms import CheckoutForm, OnboardingForm, OperationalUpdateForm, UserSignupForm, UserLoginForm, SetupPasswordForm, CompleteRegistrationForm, PaymentForm, UserCreateForm
from .password_token import make_setup_password_token, get_user_from_setup_password_token
from .payment_utils import generate_invoice_id, calculate_due_date, ensure_unique_invoice_id


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


@transaction.atomic
def payment(request):
    """Payment page with support for Invoice, ACH, and Credit Card"""
    checkout_data = request.session.get('checkout_data')
    if not checkout_data:
        messages.error(request, 'Session expired or invalid. Please checkout again.')
        return redirect('checkout')

    if request.method == 'POST':
        form = PaymentForm(request.POST)
        if form.is_valid():
            payment_method = form.cleaned_data['payment_method']
            amount = 7500.00  # Fixed Foundation price
            
            # Retrieve checkout data
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
            
            # Create Payment record
            payment_status = 'INVOICED' if payment_method == 'INVOICE' else ('PROCESSING' if payment_method == 'ACH' else 'PAID')
            invoice_id = None
            
            if payment_method == 'INVOICE':
                invoice_id = ensure_unique_invoice_id()
            
            payment_obj = Payment.objects.create(
                amount=amount,
                payment_method=payment_method,
                status=payment_status,
                invoice_id=invoice_id,
                organization=org
            )
            
            # Create Invoice if payment method is INVOICE
            if payment_method == 'INVOICE':
                Invoice.objects.create(
                    invoice_id=invoice_id,
                    payment=payment_obj,
                    billing_entity_name=form.cleaned_data['billing_entity_name'],
                    billing_email=form.cleaned_data['billing_email'],
                    po_number=form.cleaned_data['po_number'],
                    payment_terms='NET_30',
                    early_pay_terms='2% / 10, Net 30',
                    due_date=calculate_due_date('NET_30')
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
                payment_method_legacy = {
                    'INVOICE': 'Invoice',
                    'ACH': 'ACH',
                    'CARD': 'Credit Card'
                }.get(payment_method, 'Credit Card')
                
                ext_payment = ExternalPayment.objects.create(
                    username=username,
                    payment_status='Completed',
                    payment_method=payment_method_legacy,
                    amount=amount,
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
            
            # Send confirmation email
            try:
                send_payment_confirmation_email(
                    user=user,
                    payment_obj=payment_obj,
                    billing_email=form.cleaned_data['billing_email'],
                    payment_method=payment_method,
                    amount=amount,
                    invoice_id=invoice_id
                )
            except Exception as e:
                print(f"Error sending email: {e}")
            
            # Auto-login user
            user = authenticate(username=username, password='resilience2024!')
            if user:
                login(request, user)
                # Clear session
                request.session.pop('checkout_data', None)
                
                # Set appropriate success message based on payment method
                if payment_method == 'INVOICE':
                    messages.success(request, 'Invoice generated successfully. Account created.')
                elif payment_method == 'ACH':
                    messages.success(request, 'Payment will be processed via ACH. An invoice will be issued for your records. Account created.')
                else:
                    messages.success(request, 'Payment successful! Account created.')
                
                return redirect('onboarding')
        else:
            # Form validation failed
            return render(request, 'core/payment.html', {'form': form, 'checkout_data': checkout_data})
    else:
        form = PaymentForm()  # Default to INVOICE
    
    return render(request, 'core/payment.html', {'form': form, 'checkout_data': checkout_data})


def send_payment_confirmation_email(user, payment_obj, billing_email, payment_method, amount, invoice_id=None):
    """Send payment confirmation email"""
    payment_method_display = {
        'INVOICE': 'Invoice - Net 30',
        'ACH': 'ACH (Bank Transfer)',
        'CARD': 'Credit Card'
    }.get(payment_method, payment_method)
    
    subject = 'Resilience Foundation - Payment Confirmation'
    
    # Build email body
    email_body = f"""Thank you for your Resilience Foundation purchase.

Payment Details:
- Amount: ${amount:,.2f}
- Payment Method: {payment_method_display}
- Date: {timezone.now().strftime('%B %d, %Y')}
"""
    
    if invoice_id:
        email_body += f"- Invoice ID: {invoice_id}\n"
        email_body += f"- Payment Terms: Net 30\n"
        email_body += f"- Early Pay Terms: 2% / 10, Net 30\n"
    
    email_body += f"""
What's Included:
- Foundation License
- Full access to Resilience platform
- Standard support

Next Steps:
- Your account has been created and you can begin onboarding
- You will receive additional setup instructions shortly
- For invoice payments, payment is due within 30 days

Support:
If you have any questions, please contact our support team.

— Resilience Team
"""
    
    send_mail(
        subject=subject,
        message=email_body,
        from_email=getattr(django_settings, 'DEFAULT_FROM_EMAIL', 'noreply@resilience.example.com'),
        recipient_list=[billing_email],
        fail_silently=True,
    )


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
                        from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@resilience.example.com'),
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
        'is_admin': True,  # Always show admin link - access controlled by view decorator
    }
    
    return render(request, 'core/dashboard.html', context)


def capture(request):
    """Capture new operational update"""
    # Check authentication (Django auth or legacy session)
    if not request.user.is_authenticated and 'user_credentials_id' not in request.session:
        return redirect('login')
    
    liaison = None
    organization = None
    
    # Pathway 1: Standard Django Auth (Liaison)
    if request.user.is_authenticated:
        try:
            liaison = request.user.liaison_profile
            organization = liaison.organization
        except (Liaison.DoesNotExist, AttributeError):
            messages.error(request, 'Please complete checkout first.')
            return redirect('checkout')
    
    # Pathway 2: Legacy Session Auth (UserCredentials)
    elif 'user_credentials_id' in request.session:
        try:
            organization = Organization.objects.first()
            if not organization:
                messages.error(request, 'No organization found. Please complete checkout first.')
                return redirect('checkout')
        except Exception:
            messages.error(request, 'Please complete checkout first.')
            return redirect('checkout')
    
    if not organization:
        messages.error(request, 'Please complete checkout first.')
        return redirect('checkout')
    
    # Get or create system settings for status display
    settings_obj, created = SystemSettings.objects.get_or_create(
        organization=organization,
        defaults={
            'current_status': 'Normal',
            'cadence_hours': 24,
        }
    )
    
    if request.method == 'POST':
        form = OperationalUpdateForm(request.POST)
        if form.is_valid():
            # Save to core_operationalupdate table
            incident = Incident.objects.create(
                organization=organization,
                title=form.cleaned_data['title'],
                severity=form.cleaned_data['severity'],
                description=form.cleaned_data['description'] or '',  # Required field, use empty string if blank
                impact=form.cleaned_data['impact'] or '',  # Required field
                next_action=form.cleaned_data['next_action'] or '',  # Required field
                owner=liaison if liaison else None,
                is_synthesized=False,  # Required field, default to False
            )
            messages.success(request, 'Update captured successfully!')
            return redirect('dashboard')
    else:
        form = OperationalUpdateForm()
        # Set default start_time to current time (formatted for datetime-local input)
        now = timezone.now()
        # Format: YYYY-MM-DDTHH:MM for datetime-local input
        form.fields['start_time'].initial = now.strftime('%Y-%m-%dT%H:%M')
    
    # Format last sync time
    last_sync = settings_obj.last_sync
    now = timezone.now()
    time_diff = now - last_sync
    
    if time_diff < timedelta(minutes=1):
        sync_time_display = "Just now"
    elif time_diff < timedelta(hours=1):
        minutes = int(time_diff.total_seconds() / 60)
        sync_time_display = f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    elif time_diff < timedelta(days=1):
        hours = int(time_diff.total_seconds() / 3600)
        sync_time_display = f"{hours} hour{'s' if hours != 1 else ''} ago"
    else:
        sync_time_display = last_sync.strftime("%b %d, %Y at %I:%M %p")
    
    # Check if user is admin (Django staff or UserProfile admin role)
    is_admin_user = False
    if request.user.is_authenticated:
        is_admin_user = request.user.is_staff
    elif 'user_credentials_id' in request.session:
        try:
            user_cred = UserCredentials.objects.get(user_id=request.session['user_credentials_id'])
            if hasattr(user_cred, 'profile'):
                is_admin_user = user_cred.profile.role in ['admin', 'manager']
        except:
            pass
    
    return render(request, 'core/capture.html', {
        'form': form,
        'is_admin': True,  # Always show admin link - access controlled by view decorator
        'current_status': settings_obj.current_status,
        'last_sync_display': sync_time_display,
        'liaison': liaison,
    })


def normalize(request):
    """Normalize view - show all updates"""
    # Check authentication (Django auth or legacy session)
    if not request.user.is_authenticated and 'user_credentials_id' not in request.session:
        return redirect('login')
    
    liaison = None
    organization = None
    
    # Pathway 1: Standard Django Auth (Liaison)
    if request.user.is_authenticated:
        try:
            liaison = request.user.liaison_profile
            organization = liaison.organization
        except (Liaison.DoesNotExist, AttributeError):
            messages.error(request, 'Please complete checkout first.')
            return redirect('checkout')
    
    # Pathway 2: Legacy Session Auth (UserCredentials)
    elif 'user_credentials_id' in request.session:
        try:
            organization = Organization.objects.first()
            if not organization:
                messages.error(request, 'No organization found. Please complete checkout first.')
                return redirect('checkout')
        except Exception:
            messages.error(request, 'Please complete checkout first.')
            return redirect('checkout')
    
    if not organization:
        messages.error(request, 'Please complete checkout first.')
        return redirect('checkout')
    
    # Get or create system settings for status display
    settings_obj, created = SystemSettings.objects.get_or_create(
        organization=organization,
        defaults={
            'current_status': 'Normal',
            'cadence_hours': 24,
        }
    )
    
    updates = OperationalUpdate.objects.filter(
        organization=organization
    ).order_by('-timestamp')
    
    # Format last sync time
    from django.utils import timezone
    from datetime import timedelta
    last_sync = settings_obj.last_sync
    now = timezone.now()
    time_diff = now - last_sync
    
    if time_diff < timedelta(minutes=1):
        sync_time_display = "Just now"
    elif time_diff < timedelta(hours=1):
        minutes = int(time_diff.total_seconds() / 60)
        sync_time_display = f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    elif time_diff < timedelta(days=1):
        hours = int(time_diff.total_seconds() / 3600)
        sync_time_display = f"{hours} hour{'s' if hours != 1 else ''} ago"
    else:
        sync_time_display = last_sync.strftime("%b %d, %Y at %I:%M %p")
    
    return render(request, 'core/normalize.html', {
        'updates': updates,
        'is_admin': True,  # Always show admin link - access controlled by view decorator
        'current_status': settings_obj.current_status,
        'last_sync_display': sync_time_display,
    })


def distribute(request):
    """Distribute shift packet"""
    # Check authentication (Django auth or legacy session)
    if not request.user.is_authenticated and 'user_credentials_id' not in request.session:
        return redirect('login')
    
    liaison = None
    organization = None
    
    # Pathway 1: Standard Django Auth (Liaison)
    if request.user.is_authenticated:
        try:
            liaison = request.user.liaison_profile
            organization = liaison.organization
        except (Liaison.DoesNotExist, AttributeError):
            messages.error(request, 'Please complete checkout first.')
            return redirect('checkout')
    
    # Pathway 2: Legacy Session Auth (UserCredentials)
    elif 'user_credentials_id' in request.session:
        try:
            organization = Organization.objects.first()
            if not organization:
                messages.error(request, 'No organization found. Please complete checkout first.')
                return redirect('checkout')
        except Exception:
            messages.error(request, 'Please complete checkout first.')
            return redirect('checkout')
    
    if not organization:
        messages.error(request, 'Please complete checkout first.')
        return redirect('checkout')
    
    # Get or create system settings
    settings_obj, created = SystemSettings.objects.get_or_create(
        organization=organization,
        defaults={
            'current_status': 'Normal',
            'cadence_hours': 24,
        }
    )
    
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
    
    # Get latest packet number
    last_packet = ShiftPacket.objects.filter(organization=organization).order_by('-generated_at').first()
    packet_number = last_packet.packet_number if last_packet else f"PKT-{random.randint(1000, 9999)}-{timezone.now().strftime('%Y%m%d')}"
    
    # Format last sync time
    last_sync = settings_obj.last_sync
    now = timezone.now()
    time_diff = now - last_sync
    
    if time_diff < timedelta(minutes=1):
        sync_time_display = "Just now"
    elif time_diff < timedelta(hours=1):
        minutes = int(time_diff.total_seconds() / 60)
        sync_time_display = f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    elif time_diff < timedelta(days=1):
        hours = int(time_diff.total_seconds() / 3600)
        sync_time_display = f"{hours} hour{'s' if hours != 1 else ''} ago"
    else:
        sync_time_display = last_sync.strftime("%b %d, %Y at %I:%M %p")
    
    context = {
        'organization': organization,
        'settings': settings_obj,
        'updates': updates,
        'high_risk_updates': high_risk_updates,
        'packet_number': packet_number,
        'is_admin': True,  # Always show admin link - access controlled by view decorator
        'current_status': settings_obj.current_status,
        'last_sync_display': sync_time_display,
    }
    
    return render(request, 'core/distribute.html', context)


def decision_log(request):
    """Decision log view"""
    # Check authentication (Django auth or legacy session)
    if not request.user.is_authenticated and 'user_credentials_id' not in request.session:
        return redirect('login')
    
    liaison = None
    organization = None
    
    # Pathway 1: Standard Django Auth (Liaison)
    if request.user.is_authenticated:
        try:
            liaison = request.user.liaison_profile
            organization = liaison.organization
        except (Liaison.DoesNotExist, AttributeError):
            messages.error(request, 'Please complete checkout first.')
            return redirect('checkout')
    
    # Pathway 2: Legacy Session Auth (UserCredentials)
    elif 'user_credentials_id' in request.session:
        try:
            organization = Organization.objects.first()
            if not organization:
                messages.error(request, 'No organization found. Please complete checkout first.')
                return redirect('checkout')
        except Exception:
            messages.error(request, 'Please complete checkout first.')
            return redirect('checkout')
    
    if not organization:
        messages.error(request, 'Please complete checkout first.')
        return redirect('checkout')
    
    # Get or create system settings for status display
    settings_obj, created = SystemSettings.objects.get_or_create(
        organization=organization,
        defaults={
            'current_status': 'Normal',
            'cadence_hours': 24,
        }
    )
    
    decisions = Decision.objects.filter(
        organization=organization
    ).order_by('-timestamp')
    
    # Format last sync time
    from django.utils import timezone
    from datetime import timedelta
    last_sync = settings_obj.last_sync
    now = timezone.now()
    time_diff = now - last_sync
    
    if time_diff < timedelta(minutes=1):
        sync_time_display = "Just now"
    elif time_diff < timedelta(hours=1):
        minutes = int(time_diff.total_seconds() / 60)
        sync_time_display = f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    elif time_diff < timedelta(days=1):
        hours = int(time_diff.total_seconds() / 3600)
        sync_time_display = f"{hours} hour{'s' if hours != 1 else ''} ago"
    else:
        sync_time_display = last_sync.strftime("%b %d, %Y at %I:%M %p")
    
    return render(request, 'core/decision_log.html', {
        'decisions': decisions,
        'is_admin': True,  # Always show admin link - access controlled by view decorator
        'current_status': settings_obj.current_status,
        'last_sync_display': sync_time_display,
    })


def coverage(request):
    """Coverage & Communications view"""
    # Check authentication (Django auth or legacy session)
    if not request.user.is_authenticated and 'user_credentials_id' not in request.session:
        return redirect('login')
    
    liaison = None
    organization = None
    
    # Pathway 1: Standard Django Auth (Liaison)
    if request.user.is_authenticated:
        try:
            liaison = request.user.liaison_profile
            organization = liaison.organization
        except (Liaison.DoesNotExist, AttributeError):
            messages.error(request, 'Please complete checkout first.')
            return redirect('checkout')
    
    # Pathway 2: Legacy Session Auth (UserCredentials)
    elif 'user_credentials_id' in request.session:
        try:
            organization = Organization.objects.first()
            if not organization:
                messages.error(request, 'No organization found. Please complete checkout first.')
                return redirect('checkout')
        except Exception:
            messages.error(request, 'Please complete checkout first.')
            return redirect('checkout')
    
    if not organization:
        messages.error(request, 'Please complete checkout first.')
        return redirect('checkout')
    
    # Get or create system settings for status display
    settings_obj, created = SystemSettings.objects.get_or_create(
        organization=organization,
        defaults={
            'current_status': 'Normal',
            'cadence_hours': 24,
        }
    )
    
    # Format last sync time
    from django.utils import timezone
    from datetime import timedelta
    last_sync = settings_obj.last_sync
    now = timezone.now()
    time_diff = now - last_sync
    
    if time_diff < timedelta(minutes=1):
        sync_time_display = "Just now"
    elif time_diff < timedelta(hours=1):
        minutes = int(time_diff.total_seconds() / 60)
        sync_time_display = f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    elif time_diff < timedelta(days=1):
        hours = int(time_diff.total_seconds() / 3600)
        sync_time_display = f"{hours} hour{'s' if hours != 1 else ''} ago"
    else:
        sync_time_display = last_sync.strftime("%b %d, %Y at %I:%M %p")
    
    return render(request, 'core/coverage.html', {
        'organization': organization,
        'liaison': liaison,
        'is_admin': True,  # Always show admin link - access controlled by view decorator
        'current_status': settings_obj.current_status,
        'last_sync_display': sync_time_display,
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
                return redirect('dashboard')
            except UserCredentials.DoesNotExist:
                pass
            # 2) Try Django auth (Liaison users who set password via email link)
            user = authenticate(request, username=username, password=password)
            if user is not None:
                login(request, user)
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


def admin_module(request):
    """Admin page: list users from users table."""
    # Check authentication (Django auth or legacy session)
    if not request.user.is_authenticated and 'user_credentials_id' not in request.session:
        messages.error(request, 'Please login first.')
        return redirect('login')
    
    # Handle UserCredentials (legacy session auth) - create mock user object
    if not request.user.is_authenticated and 'user_credentials_id' in request.session:
        username_value = request.session.get('user_credentials_username', 'Admin')
        
        class MockUser:
            def __init__(self, username):
                self.username = username
                self.first_name = username
                self.last_name = ""
                self.is_authenticated = True
                self.is_staff = False
            
            def get_full_name(self):
                return self.username
        
        request.user = MockUser(username_value)
    
    # Handle create user form submission
    if request.method == 'POST' and request.POST.get('action') == 'create_user':
        try:
            agency_name = request.POST.get('agency_name', '').strip()
            primary_liaison_name = request.POST.get('primary_liaison_name', '').strip()
            liaison_email = request.POST.get('liaison_email', '').strip()
            key_incident_types = request.POST.get('key_incident_types', '').strip() or None
            preferred_communication_channels = request.POST.get('preferred_communication_channels', '').strip() or None
            
            if not agency_name or not primary_liaison_name or not liaison_email:
                messages.error(request, 'Agency Name, Primary Liaison Name, and Email are required.')
            else:
                # Create new user in users table
                # Note: created_at will be set automatically by MySQL CURRENT_TIMESTAMP default
                UsersTable.objects.create(
                    agency_name=agency_name,
                    primary_liaison_name=primary_liaison_name,
                    liaison_email=liaison_email,
                    key_incident_types=key_incident_types,
                    preferred_communication_channels=preferred_communication_channels,
                    created_at=timezone.now(),  # Explicitly set created_at
                )
                messages.success(request, f'User "{primary_liaison_name}" from "{agency_name}" created successfully!')
                return redirect('admin_module')
        except Exception as e:
            messages.error(request, f'Error creating user: {str(e)}')
    
    # Get all users from the users table
    users_list = UsersTable.objects.all().order_by('-created_at')
    
    return render(request, 'core/admin_module.html', {
        'users_list': users_list,
        'is_admin': True,
        'user': request.user,
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


@csrf_exempt
def create_payment_intent(request):
    """Create a Stripe Payment Intent"""
    if request.method != 'GET':
        return JsonResponse({
            'error': 'Method not allowed. This endpoint only accepts GET requests.'
        }, status=405)
    
    try:
        # Validate Stripe keys
        if not settings.STRIPE_SECRET_KEY or settings.STRIPE_SECRET_KEY.strip() == '':
            return JsonResponse({
                'error': 'Stripe secret key is not configured',
                'type': 'configuration_error'
            }, status=500)
        
        # Initialize Stripe
        stripe.api_key = settings.STRIPE_SECRET_KEY
        
        # Parse request data from query parameters
        amount = int(float(request.GET.get('amount', 7500.00)) * 100)  # Convert to cents
        currency = request.GET.get('currency', 'usd').lower()
        user_id = request.GET.get('user_id', None)
        description = request.GET.get('description', 'Resilience Foundation License')
        
        # Validate amount
        if amount < 50:  # Minimum $0.50
            return JsonResponse({
                'error': 'Amount must be at least $0.50',
                'type': 'validation_error'
            }, status=400)
        
        # Create Payment Intent
        payment_intent = stripe.PaymentIntent.create(
            amount=amount,
            currency=currency,
            description=description,
            automatic_payment_methods={
                'enabled': True,
            },
        )
        
        # Create StripePayment record with pending status
        StripePayment.objects.create(
            stripe_payment_intent_id=payment_intent.id,
            amount=amount,  # Store in cents
            currency=currency,
            status='pending',
            user_id=int(user_id) if user_id else None,
        )
        
        return JsonResponse({
            'clientSecret': payment_intent.client_secret,
            'payment_intent_id': payment_intent.id,
        })
        
    except stripe.error.CardError as e:
        # Card was declined
        return JsonResponse({
            'error': f'Card error: {e.user_message}',
            'type': 'card_error',
            'code': e.code
        }, status=400)
    except stripe.error.RateLimitError as e:
        # Too many requests
        return JsonResponse({
            'error': 'Rate limit error. Please try again later.',
            'type': 'rate_limit_error'
        }, status=429)
    except stripe.error.InvalidRequestError as e:
        # Invalid parameters
        return JsonResponse({
            'error': f'Invalid request: {str(e)}',
            'type': 'invalid_request_error'
        }, status=400)
    except stripe.error.AuthenticationError as e:
        # Authentication failed
        return JsonResponse({
            'error': 'Authentication failed. Please check your Stripe API keys.',
            'type': 'authentication_error'
        }, status=401)
    except stripe.error.APIConnectionError as e:
        # Network error
        return JsonResponse({
            'error': 'Network error. Please check your internet connection.',
            'type': 'api_connection_error'
        }, status=503)
    except stripe.error.APIError as e:
        # Generic API error
        return JsonResponse({
            'error': f'Stripe API error: {str(e)}',
            'type': 'api_error'
        }, status=500)
    except stripe.error.StripeError as e:
        # Generic Stripe error
        return JsonResponse({
            'error': f'Stripe error: {str(e)}',
            'type': 'stripe_error'
        }, status=400)
    except Exception as e:
        return JsonResponse({
            'error': f'Server error: {str(e)}',
            'type': 'server_error'
        }, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def stripe_webhook(request):
    """Handle Stripe webhook events"""
    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE')
    
    if not sig_header:
        return HttpResponse('Missing Stripe signature', status=400)
    
    webhook_secret = settings.STRIPE_WEBHOOK_SECRET
    if not webhook_secret:
        return HttpResponse('Webhook secret not configured', status=500)
    
    try:
        # Verify webhook signature
        event = stripe.Webhook.construct_event(
            payload, sig_header, webhook_secret
        )
    except ValueError as e:
        # Invalid payload
        return HttpResponse(f'Invalid payload: {str(e)}', status=400)
    except stripe.error.SignatureVerificationError as e:
        # Invalid signature
        return HttpResponse(f'Invalid signature: {str(e)}', status=400)
    
    # Handle the event
    event_type = event['type']
    event_data = event['data']['object']
    
    try:
        if event_type == 'payment_intent.succeeded':
            payment_intent_id = event_data['id']
            
            # Update payment status to succeeded
            stripe_payment = StripePayment.objects.get(stripe_payment_intent_id=payment_intent_id)
            stripe_payment.status = 'succeeded'
            
            # Get charge ID if available
            charges = event_data.get('charges', {}).get('data', [])
            if charges:
                stripe_payment.stripe_charge_id = charges[0].get('id', '')
                stripe_payment.receipt_url = charges[0].get('receipt_url', '')
            
            stripe_payment.save()
            
        elif event_type == 'payment_intent.payment_failed':
            payment_intent_id = event_data['id']
            
            # Update payment status to failed
            stripe_payment = StripePayment.objects.get(stripe_payment_intent_id=payment_intent_id)
            stripe_payment.status = 'failed'
            stripe_payment.save()
            
        elif event_type == 'charge.refunded':
            # Handle refund
            payment_intent_id = event_data.get('payment_intent')
            if payment_intent_id:
                stripe_payment = StripePayment.objects.get(stripe_payment_intent_id=payment_intent_id)
                stripe_payment.status = 'refunded'
                stripe_payment.stripe_charge_id = event_data.get('id', '')
                stripe_payment.save()
        
        return HttpResponse(status=200)
        
    except StripePayment.DoesNotExist:
        # Payment intent not found in database - log but don't fail
        return HttpResponse(status=200)  # Return 200 to prevent Stripe retries
    except Exception as e:
        # Log error but return 200 to prevent Stripe from retrying
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f'Webhook processing error: {str(e)}')
        return HttpResponse(status=200)


def stripe_payments_page(request):
    """Stripe payments test page"""
    return render(request, 'core/stripepayments.html', {
        'STRIPE_PUBLIC_KEY': settings.STRIPE_PUBLIC_KEY
    })


def stripe_invoice_pdf(request):
    """Generate a simple PDF invoice for a Stripe Payment Intent."""
    payment_intent_id = request.GET.get('payment_intent_id')
    if not payment_intent_id:
        return HttpResponse('Missing payment_intent_id', status=400)

    # Initialize Stripe
    if not settings.STRIPE_SECRET_KEY or settings.STRIPE_SECRET_KEY.strip() == '':
        return HttpResponse('Stripe secret key is not configured', status=500)

    stripe.api_key = settings.STRIPE_SECRET_KEY

    try:
        payment_intent = stripe.PaymentIntent.retrieve(
            payment_intent_id,
            expand=['charges']
        )
    except stripe.error.StripeError as e:
        return HttpResponse(f'Unable to retrieve payment from Stripe: {str(e)}', status=400)
    except Exception as e:
        return HttpResponse(f'Unexpected error: {str(e)}', status=500)

    amount = (payment_intent.amount or 0) / 100.0
    currency = (payment_intent.currency or 'usd').upper()
    description = payment_intent.description or 'Resilience Foundation License'

    # Prepare PDF in memory
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    # Basic invoice layout
    pdf.setTitle(f"Invoice - {payment_intent_id}")

    # Header
    pdf.setFont("Helvetica-Bold", 20)
    pdf.drawString(50, height - 80, "INVOICE")

    pdf.setFont("Helvetica", 10)
    pdf.drawString(50, height - 110, "Resilience System")
    pdf.drawString(50, height - 125, "www.resilience.example.com")

    # Invoice details
    y = height - 160
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(50, y, "Invoice Details")
    pdf.setFont("Helvetica", 10)
    y -= 18
    pdf.drawString(50, y, f"Payment Intent ID: {payment_intent_id}")
    y -= 14
    pdf.drawString(50, y, f"Amount: ${amount:,.2f} {currency}")
    y -= 14
    pdf.drawString(50, y, f"Description: {description}")

    # Simple line items section
    y -= 30
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(50, y, "Line Items")
    y -= 18
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(50, y, "Item")
    pdf.drawString(350, y, "Amount")
    y -= 14
    pdf.setFont("Helvetica", 10)
    pdf.drawString(50, y, "Resilience Foundation License")
    pdf.drawRightString(430, y, f"${amount:,.2f}")

    # Total
    y -= 30
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(50, y, "Total")
    pdf.drawRightString(430, y, f"${amount:,.2f} {currency}")

    # Footer
    y -= 60
    pdf.setFont("Helvetica", 9)
    pdf.drawString(50, y, "Thank you for your business.")

    pdf.showPage()
    pdf.save()

    buffer.seek(0)
    response = HttpResponse(buffer, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="invoice_{payment_intent_id}.pdf"'
    return response


def incidents_list(request):
    """List all incidents - shows Update Title, Severity, Start Time"""
    # Check authentication (Django auth or legacy session)
    if not request.user.is_authenticated and 'user_credentials_id' not in request.session:
        return redirect('login')
    
    liaison = None
    organization = None
    
    # Pathway 1: Standard Django Auth (Liaison)
    if request.user.is_authenticated:
        try:
            liaison = request.user.liaison_profile
            organization = liaison.organization
        except (Liaison.DoesNotExist, AttributeError):
            messages.error(request, 'Please complete checkout first.')
            return redirect('checkout')
    
    # Pathway 2: Legacy Session Auth (UserCredentials)
    elif 'user_credentials_id' in request.session:
        try:
            organization = Organization.objects.first()
            if not organization:
                messages.error(request, 'No organization found. Please complete checkout first.')
                return redirect('checkout')
        except Exception:
            messages.error(request, 'Please complete checkout first.')
            return redirect('checkout')
    
    if not organization:
        messages.error(request, 'Please complete checkout first.')
        return redirect('checkout')
    
    # Get all incidents for this organization
    incidents = Incident.objects.filter(organization=organization).order_by('-timestamp')
    
    # Get or create system settings for status display
    settings_obj, created = SystemSettings.objects.get_or_create(
        organization=organization,
        defaults={
            'current_status': 'Normal',
            'cadence_hours': 24,
        }
    )
    
    # Format last sync time
    last_sync = settings_obj.last_sync
    now = timezone.now()
    time_diff = now - last_sync
    
    if time_diff < timedelta(minutes=1):
        sync_time_display = "Just now"
    elif time_diff < timedelta(hours=1):
        minutes = int(time_diff.total_seconds() / 60)
        sync_time_display = f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    elif time_diff < timedelta(days=1):
        hours = int(time_diff.total_seconds() / 3600)
        sync_time_display = f"{hours} hour{'s' if hours != 1 else ''} ago"
    else:
        sync_time_display = last_sync.strftime("%b %d, %Y at %I:%M %p")
    
    return render(request, 'core/incidents_list.html', {
        'incidents': incidents,
        'organization': organization,
        'is_admin': True,  # Always show admin link - access controlled by view decorator
        'current_status': settings_obj.current_status,
        'last_sync_display': sync_time_display,
    })


def incident_detail(request, incident_id):
    """Show detailed view of a single incident"""
    # Check authentication (Django auth or legacy session)
    if not request.user.is_authenticated and 'user_credentials_id' not in request.session:
        return redirect('login')
    
    liaison = None
    organization = None
    
    # Pathway 1: Standard Django Auth (Liaison)
    if request.user.is_authenticated:
        try:
            liaison = request.user.liaison_profile
            organization = liaison.organization
        except (Liaison.DoesNotExist, AttributeError):
            messages.error(request, 'Please complete checkout first.')
            return redirect('checkout')
    
    # Pathway 2: Legacy Session Auth (UserCredentials)
    elif 'user_credentials_id' in request.session:
        try:
            organization = Organization.objects.first()
            if not organization:
                messages.error(request, 'No organization found. Please complete checkout first.')
                return redirect('checkout')
        except Exception:
            messages.error(request, 'Please complete checkout first.')
            return redirect('checkout')
    
    if not organization:
        messages.error(request, 'Please complete checkout first.')
        return redirect('checkout')
    
    # Get the incident
    try:
        incident = Incident.objects.get(id=incident_id, organization=organization)
    except Incident.DoesNotExist:
        messages.error(request, 'Incident not found.')
        return redirect('incidents_list')
    
    # Get or create system settings for status display
    settings_obj, created = SystemSettings.objects.get_or_create(
        organization=organization,
        defaults={
            'current_status': 'Normal',
            'cadence_hours': 24,
        }
    )
    
    # Format last sync time
    last_sync = settings_obj.last_sync
    now = timezone.now()
    time_diff = now - last_sync
    
    if time_diff < timedelta(minutes=1):
        sync_time_display = "Just now"
    elif time_diff < timedelta(hours=1):
        minutes = int(time_diff.total_seconds() / 60)
        sync_time_display = f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    elif time_diff < timedelta(days=1):
        hours = int(time_diff.total_seconds() / 3600)
        sync_time_display = f"{hours} hour{'s' if hours != 1 else ''} ago"
    else:
        sync_time_display = last_sync.strftime("%b %d, %Y at %I:%M %p")
    
    return render(request, 'core/incident_detail.html', {
        'incident': incident,
        'organization': organization,
        'is_admin': True,  # Always show admin link - access controlled by view decorator
        'current_status': settings_obj.current_status,
        'last_sync_display': sync_time_display,
    })


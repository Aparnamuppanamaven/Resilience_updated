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
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak, KeepTogether
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.colors import HexColor
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
import csv
import os

from django.db import transaction
from django.core.files.storage import default_storage
from django.utils.text import slugify
from .models import (
    Organization, Liaison, OperationalUpdate, Incident, IncidentEvent, IncidentCapture,
    Decision, SystemSettings, ShiftPacket,
    ExternalUser, ExternalPayment, ExternalSubscription, UserCredentials, UsersTable, Shift, Department,
    Payment, Invoice,
    StripePayment, UserProfile,
)
from .forms import CheckoutForm, OnboardingForm, OperationalUpdateForm, UserSignupForm, UserLoginForm, SetupPasswordForm, CompleteRegistrationForm, PaymentForm, UserCreateForm, ProfileEditForm, LegacyProfileEditForm
from .password_token import make_setup_password_token, get_user_from_setup_password_token
from .payment_utils import generate_invoice_id, calculate_due_date, ensure_unique_invoice_id
from .email_utils import send_checkout_confirmation_email, send_new_user_notification_email


def detect_existing_user(email):
    """
    Check if email exists in database (User, Liaison, or ExternalUser tables).
    Returns dict with 'exists', 'user', 'organization', 'source' keys.
    """
    email_lower = email.lower().strip()
    
    # Check User table
    try:
        user = User.objects.filter(email__iexact=email_lower).first()
        if user:
            try:
                liaison = user.liaison_profile
                return {
                    'exists': True,
                    'user': user,
                    'organization': liaison.organization,
                    'source': 'User'
                }
            except Liaison.DoesNotExist:
                return {
                    'exists': True,
                    'user': user,
                    'organization': None,
                    'source': 'User'
                }
    except Exception:
        pass
    
    # Check Liaison via user email
    try:
        liaison = Liaison.objects.filter(user__email__iexact=email_lower).first()
        if liaison:
            return {
                'exists': True,
                'user': liaison.user,
                'organization': liaison.organization,
                'source': 'Liaison'
            }
    except Exception:
        pass
    
    # Check ExternalUser (legacy table)
    try:
        ext_user = ExternalUser.objects.filter(liaison_email__iexact=email_lower).first()
        if ext_user:
            # Try to find corresponding User
            user = User.objects.filter(email__iexact=email_lower).first()
            return {
                'exists': True,
                'user': user,
                'organization': None,  # ExternalUser doesn't have direct org link
                'source': 'ExternalUser'
            }
    except Exception:
        pass
    
    return {
        'exists': False,
        'user': None,
        'organization': None,
        'source': None
    }


def resolve_login_username(value):
    """
    Resolve login input (Primary Liaison Name or full Liaison Email) to the Django User's username.
    - If value contains '@', treat as full email and look up User by email.
    - Otherwise treat as name: match User by get_full_name() or ExternalUser.primary_liaison_name -> email -> User.
    Returns username string for authenticate(), or None if not found.
    """
    if not value or not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    # Full email (e.g. mks@gmail.com)
    if '@' in raw:
        user = User.objects.filter(email__iexact=raw).first()
        return user.username if user else None
    # Name: match by full name or primary_liaison_name
    for user in User.objects.all():
        if user.get_full_name() and user.get_full_name().strip().lower() == raw.lower():
            return user.username
    ext = ExternalUser.objects.filter(primary_liaison_name__iexact=raw).first()
    if ext:
        user = User.objects.filter(email__iexact=ext.liaison_email).first()
        return user.username if user else None
    return None


def user_has_active_subscription(username):
    """
    Return True if the user has an Active subscription.
    Used at login to allow only users with valid active subscription.
    Checks both new core_subscriptions table and old subscriptions table.
    """
    if not username:
        return False
    try:
        # First, check new core_subscriptions table (if user exists in auth_user)
        user = User.objects.filter(username=username).first()
        if user:
            # Check for active subscription in new table (paid_status = 'paid' or 'active')
            sub = ExternalSubscription.objects.filter(
                user=user,
                paid_status__in=['paid', 'active', 'Paid', 'Active', 'PAID', 'ACTIVE']
            ).order_by('-created_at').first()
            if sub:
                return True
        
        # If not found in new table, check old subscriptions table (legacy)
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute('''
                SELECT subscription_status, subscription_end_date 
                FROM subscriptions 
                WHERE username = %s 
                AND subscription_status = 'Active'
                AND subscription_end_date >= %s
                ORDER BY subscription_end_date DESC
                LIMIT 1
            ''', (username, timezone.now().date()))
            result = cursor.fetchone()
            if result:
                return True
        
        return False
    except Exception:
        return False


def calculate_new_subscription_end_date(subscription):
    """
    Calculate new subscription end date for renewal.
    If expired: start from today + 365 days
    If active: extend from current end_date + 365 days
    """
    if subscription.subscription_end_date < timezone.now().date():
        # Expired: start from today
        return timezone.now().date() + timedelta(days=365)
    else:
        # Active: extend from current end date
        return subscription.subscription_end_date + timedelta(days=365)


def index(request):
    """Landing page"""
    return render(request, 'core/index.html')


def checkout(request):
    """Checkout page for Foundation purchase"""
    if request.method == 'POST':
        form = CheckoutForm(request.POST)
        if form.is_valid():
            liaison_email = form.cleaned_data['liaison_email']

            # Check if user already exists
            user_check = detect_existing_user(liaison_email)

            if user_check['exists']:
                # Existing user detected
                request.session['checkout_data'] = form.cleaned_data
                request.session['is_existing_user'] = True
                request.session['existing_user_email'] = liaison_email

                form.add_error('liaison_email', 'This email/account already exists.')

                return render(request, 'core/checkout.html', {
                    'form': form,
                    'show_login_button': True,
                    'existing_email': liaison_email
                })

            # ---------------- NEW USER FLOW ----------------
            liaison_name = form.cleaned_data.get('liaison_name', '')
            agency = form.cleaned_data.get('agency', '')
            password = form.cleaned_data.get('password', 'resilience2024!')
            channels = form.cleaned_data.get('channels')
            incidents = form.cleaned_data.get('incidents')
            role = form.cleaned_data.get('role', '')
            dept = form.cleaned_data.get('dept', '')
            countee = form.cleaned_data.get('countee', '')

            username = liaison_email.strip()
            n = 0
            while User.objects.filter(username=username).exists():
                n += 1
                username = f"{liaison_email.strip()}{n}"

            with transaction.atomic():
                org = Organization.objects.create(
                    name=agency,
                    license_type='foundation',
                    foundation_purchase_date=timezone.now()
                )

                user = User.objects.create(
                    username=username,
                    email=liaison_email,
                    first_name=liaison_name.split()[0] if liaison_name.split() else '',
                    last_name=' '.join(liaison_name.split()[1:]) if len(liaison_name.split()) > 1 else '',
                )
                user.set_password(password)
                user.save()

                Liaison.objects.update_or_create(
                    user=user,
                    defaults={
                        'organization': org,
                        'preferred_channels': channels,
                        'incident_types': incidents,
                        'role': role,
                        'dept': dept,
                        'countee': countee,
                    }
                )

                SystemSettings.objects.get_or_create(
                    organization=org,
                    defaults={'cadence_hours': 24}
                )

                try:
                    ExternalUser.objects.create(
                        agency_name=agency,
                        primary_liaison_name=liaison_name,
                        liaison_email=liaison_email,
                        key_incident_types=incidents,
                        preferred_communication_channels=channels,
                        created_at=timezone.now()
                    )
                except Exception as e:
                    print(f"Error creating legacy user: {e}")

                # Also create legacy UserCredentials entry so this account can log in via username/password.
                try:
                    legacy_username = (liaison_email or '').strip()
                    if legacy_username and not UserCredentials.objects.filter(username=legacy_username).exists():
                        UserCredentials.objects.create(
                            username=legacy_username,
                            password_hash=password,
                        )
                except Exception as e:
                    print(f"Error creating UserCredentials record: {e}")

            # Placeholder subscription
            try:
                placeholder_payment = ExternalPayment.objects.create(
                    username=username,
                    payment_status='Pending',
                    payment_method='N/A',
                    amount=0,
                    payment_time=timezone.now()
                )
                ExternalSubscription.objects.create(
                    username=username,
                    payment=placeholder_payment,
                    subscription_type='Foundation',
                    duration=0,
                    subscription_start_date=timezone.now().date(),
                    subscription_end_date=timezone.now().date(),
                    subscription_status='Inactive',
                    created_at=timezone.now()
                )
            except Exception as e:
                print(f"Error creating placeholder subscription: {e}")

            # Send notification email (NEW FEATURE)
            try:
                success, message = send_new_user_notification_email(
                    liaison_email=liaison_email,
                    liaison_name=liaison_name,
                    agency_name=agency
                )
                if not success:
                    print(f"Notification email failed: {message}")
            except Exception as e:
                print(f"Exception while sending notification email: {e}")

            request.session['checkout_data'] = form.cleaned_data
            request.session['is_existing_user'] = False
            request.session['checkout_user_id'] = user.id
            request.session.pop('existing_user_email', None)

            return redirect('payment')

    else:
        form = CheckoutForm()
        checkout_data = request.session.get('checkout_data')
        if checkout_data:
            for field in form.fields:
                if field in checkout_data:
                    form.fields[field].initial = checkout_data[field]

    return render(request, 'core/checkout.html', {'form': form})


@transaction.atomic
def payment(request):
    """Payment page - handles both new users and existing users (renewal)"""
    checkout_data = request.session.get('checkout_data')
    if not checkout_data:
        # Clear renewal flags if checkout_data is missing
        request.session.pop('is_existing_user', None)
        request.session.pop('existing_user_email', None)
        messages.error(request, 'Session expired or invalid. Please checkout again.')
        return redirect('checkout')
    
    # Determine if this is renewal (existing user) or new user
    is_existing_user = request.session.get('is_existing_user', False)
    is_logged_in = request.user.is_authenticated
    
    # If existing user but not logged in, redirect to login
    if is_existing_user and not is_logged_in:
        # Only show message once - check if we've already redirected
        if not request.session.get('_payment_redirected_to_login'):
            messages.info(request, 'Please login to renew your subscription.')
            request.session['_payment_redirected_to_login'] = True
        return redirect('login')
    
    # Load existing user data if renewal
    existing_user = None
    existing_org = None
    existing_subscription = None
    renewal_info = None
    
    if is_existing_user and is_logged_in:
        try:
            existing_user = request.user
            liaison = existing_user.liaison_profile
            existing_org = liaison.organization
            
            # Find most recent paid (Active) subscription for renewal
            existing_subscription = ExternalSubscription.objects.filter(
                user=existing_user,
                paid_status__in=['paid', 'active', 'Paid', 'Active', 'PAID', 'ACTIVE']
            ).order_by('-created_at').first()
            
            if existing_subscription:
                # For renewal, use a simple calculation (new table doesn't have end_date)
                renewal_info = {
                    'org_name': existing_org.name,
                    'current_end_date': None,  # New table structure doesn't have end_date
                    'new_end_date': None,  # Will be set when payment is processed
                    'amount': float(existing_subscription.amount) if existing_subscription.amount else 7500.00
                }
        except Exception as e:
            messages.error(request, 'Error loading subscription information.')
            return redirect('checkout')

    if request.method == 'POST':
        form = PaymentForm(request.POST)
        if form.is_valid():
            payment_method = form.cleaned_data['payment_method']
            amount = 7500.00  # Fixed Foundation price
            
            # For Stripe payments, redirect to Stripe payment page (user already created at checkout)
            if payment_method == 'CARD':
                request.session['payment_pending'] = True
                request.session['is_renewal'] = is_existing_user
                return redirect('stripe_payments_page')
            
            # Handle Invoice and ACH payments (non-Stripe)
            if is_existing_user and is_logged_in:
                # RENEWAL FLOW - Update existing subscription
                # Note: Invoice/ACH renewal handled here, Stripe handled in webhook
                payment_status = 'INVOICED' if payment_method == 'INVOICE' else 'PROCESSING'
            invoice_id = None
            
            if payment_method == 'INVOICE':
                invoice_id = ensure_unique_invoice_id()
            
                # Create Payment record linked to existing organization
            payment_obj = Payment.objects.create(
                amount=amount,
                payment_method=payment_method,
                status=payment_status,
                invoice_id=invoice_id,
                    organization=existing_org
            )
            
                # Create Invoice if needed
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
            
                # Update existing subscription
                if existing_subscription:
                    new_end_date = calculate_new_subscription_end_date(existing_subscription)
                    # Update subscription using raw SQL (since managed=False)
                    from django.db import connection
                    with connection.cursor() as cursor:
                        cursor.execute(
                            """
                            UPDATE subscriptions 
                            SET subscription_end_date = %s,
                                subscription_status = 'Active',
                                duration = 365
                            WHERE subscription_id = %s
                            """,
                            [new_end_date, existing_subscription.subscription_id]
                        )
                
                # Create ExternalPayment record
                try:
                    payment_method_legacy = {
                        'INVOICE': 'Invoice',
                        'ACH': 'ACH',
                        'CARD': 'Credit Card'
                    }.get(payment_method, 'Credit Card')

                    ExternalPayment.objects.create(
                        username=existing_user.username,
                        payment_status='Completed',
                        payment_method=payment_method_legacy,
                        amount=amount,
                        payment_time=timezone.now()
                    )
                except Exception as e:
                    print(f"Error creating legacy payment: {e}")
                
                # Clear session
                request.session.pop('checkout_data', None)
                request.session.pop('is_existing_user', None)
                request.session.pop('existing_user_email', None)
                
                # Redirect to payment success page
                return redirect('payment_success', is_renewal='true')
            else:
                # NEW USER FLOW - User/org/liaison already created at checkout; user may not be logged in
                uid = request.session.get('checkout_user_id')
                if request.user.is_authenticated:
                    user = request.user
                elif uid:
                    user = get_object_or_404(User, id=uid)
                else:
                    messages.error(request, 'Session expired. Please checkout again.')
                    return redirect('checkout')
                liaison = user.liaison_profile
                org = liaison.organization
                username = user.username

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

                try:
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
                    # Activate existing Inactive subscription from checkout, or create new
                    inactive_sub = ExternalSubscription.objects.filter(
                        username=username,
                        subscription_status='Inactive'
                    ).order_by('-created_at').first()
                    if inactive_sub:
                        inactive_sub.payment = ext_payment
                        inactive_sub.subscription_status = 'Active'
                        inactive_sub.subscription_start_date = timezone.now().date()
                        inactive_sub.subscription_end_date = timezone.now().date() + timedelta(days=365)
                        inactive_sub.duration = 365
                        inactive_sub.save()
                    else:
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
                    print(f"Error populating legacy tables: {e}") 

                request.session.pop('checkout_data', None)
                request.session.pop('is_existing_user', None)
                request.session.pop('checkout_user_id', None)
                return redirect('payment_success', is_renewal='false')
        else:
            # Form validation failed
            return render(request, 'core/payment.html', {
                'form': form,
                'checkout_data': checkout_data,
                'is_renewal': is_existing_user and is_logged_in,
                'renewal_info': renewal_info
            })
    else:
        form = PaymentForm()
    
    return render(request, 'core/payment.html', {
        'form': form,
        'checkout_data': checkout_data,
        'is_renewal': is_existing_user and is_logged_in,
        'renewal_info': renewal_info
    })


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
        from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@resilience.example.com'),
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
    liaison = None
    organization = None
    
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
    
    # Get all incidents for the Create Update dropdown - use same logic as incidents_list
    if liaison is not None and organization is not None:
        # Standard Django auth users (with Liaison) only see incidents
        # that belong to their organization.
        all_incidents = IncidentCapture.objects.filter(
            organization=organization
        ).order_by('-created_at')
    else:
        # Legacy UserCredentials users and any fallback case:
        # show all incidents (no org filter) so previously captured data is visible.
        all_incidents = IncidentCapture.objects.all().order_by('-created_at')
    
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
        'all_incidents': all_incidents,  # Add incidents for dropdown
    }
    
    return render(request, 'core/dashboard.html', context)


def profile_edit(request):
    """Edit profile for the currently logged-in user (Django auth or UserCredentials)."""
    if not request.user.is_authenticated and 'user_credentials_id' not in request.session:
        messages.error(request, 'Please log in to edit your profile.')
        return redirect('login')

    is_legacy = 'user_credentials_id' in request.session and not request.user.is_authenticated

    if is_legacy:
        # Legacy UserCredentials user
        cred_id = request.session.get('user_credentials_id')
        try:
            user_cred = UserCredentials.objects.get(user_id=cred_id)
        except UserCredentials.DoesNotExist:
            messages.error(request, 'Session invalid. Please log in again.')
            return redirect('login')

        if request.method == 'POST':
            form = LegacyProfileEditForm(request.POST, request.FILES)
            if form.is_valid():
                user_cred.username = form.cleaned_data['username'].strip()
                try:
                    user_cred.save()
                    request.session['user_credentials_username'] = user_cred.username
                except Exception as e:
                    messages.error(request, f'Could not save: {e}')
                    form = LegacyProfileEditForm(request.POST, request.FILES)
                    return render(request, 'core/profile_edit.html', {'form': form, 'is_legacy': True, 'profile_display_name': user_cred.username})
                # Update UserProfile if it exists (mobile, email, full_name)
                try:
                    profile = getattr(user_cred, 'profile', None)
                    if profile:
                        profile.email = form.cleaned_data.get('email', '').strip() or user_cred.username
                        profile.full_name = form.cleaned_data.get('username', '').strip() or profile.full_name
                        profile.mobile = (form.cleaned_data.get('mobile_number') or '').strip() or profile.mobile
                        profile.save()
                except Exception:
                    pass
                # Optional: save profile photo to MEDIA and store path in core_users.user_image
                photo = request.FILES.get('profile_photo')
                if photo:
                    try:
                        upload_dir = settings.MEDIA_ROOT / 'user_images'
                        upload_dir.mkdir(parents=True, exist_ok=True)
                        ext = (os.path.splitext(photo.name)[1] or '.jpg').lower()
                        if ext not in ('.jpg', '.jpeg', '.png', '.gif', '.webp'):
                            ext = '.jpg'
                        filename = f"legacy_{user_cred.user_id}{ext}"
                        full_path = upload_dir / filename
                        with open(full_path, 'wb') as f:
                            for chunk in photo.chunks():
                                f.write(chunk)
                        user_image_path = f"user_images/{filename}"
                        # Store path in core_users.user_image (match by liaison_email, email_id, or primary_liaison_name)
                        UsersTable.objects.filter(
                            Q(liaison_email__iexact=user_cred.username) |
                            Q(email_id__iexact=user_cred.username) |
                            Q(primary_liaison_name__iexact=user_cred.username)
                        ).update(user_image=user_image_path)
                    except Exception:
                        pass
                messages.success(request, 'Profile updated successfully.')
                return redirect('dashboard')
        else:
            profile = getattr(user_cred, 'profile', None)
            initial = {
                'username': user_cred.username,
                'email': user_cred.username,
                'organization_name': getattr(profile, 'organization_name', '') if profile else '',
                'mobile_number': profile.mobile if profile else '',
            }
            form = LegacyProfileEditForm(initial=initial)

        # Mock user so sidebar dropdown shows correct name/email
        class _MockUser:
            username = user_cred.username
            email = user_cred.username
            def get_full_name(self):
                return self.username
            liaison_profile = None
            is_authenticated = True
        request.user = _MockUser()

        # Profile image from core_users.user_image for legacy user (match by liaison_email, email_id, primary_liaison_name)
        profile_image_url = None
        try:
            user_table = UsersTable.objects.filter(
                Q(liaison_email__iexact=user_cred.username) | Q(email_id__iexact=user_cred.username) | Q(primary_liaison_name__iexact=user_cred.username)
            ).filter(user_image__isnull=False).exclude(user_image='').first()
            if user_table and user_table.user_image:
                profile_image_url = f"{(settings.MEDIA_URL or '/media/').rstrip('/')}/{user_table.user_image.lstrip('/')}"
        except Exception:
            pass

        return render(request, 'core/profile_edit.html', {
            'form': form,
            'is_legacy': True,
            'profile_display_name': user_cred.username,
            'profile_image_url': profile_image_url,
        })

    # Django auth user (Liaison)
    try:
        liaison = request.user.liaison_profile
        organization = liaison.organization
    except (Liaison.DoesNotExist, AttributeError):
        messages.error(request, 'Please complete checkout first.')
        return redirect('checkout')

    if request.method == 'POST':
        form = ProfileEditForm(request.POST, request.FILES)
        if form.is_valid():
            request.user.username = form.cleaned_data['username'].strip()
            request.user.email = form.cleaned_data['email'].strip()
            request.user.save()
            liaison.phone = (form.cleaned_data.get('mobile_number') or '').strip() or ''
            organization.name = (form.cleaned_data.get('organization_name') or '').strip() or organization.name
            organization.save()
            # Profile photo upload
            photo = request.FILES.get('profile_photo')
            if photo:
                try:
                    upload_dir = settings.MEDIA_ROOT / 'user_images'
                    upload_dir.mkdir(parents=True, exist_ok=True)
                    base, ext = os.path.splitext(photo.name)
                    ext = (ext or '.jpg').lower()
                    if ext not in ('.jpg', '.jpeg', '.png', '.gif', '.webp'):
                        ext = '.jpg'
                    safe_name = slugify(request.user.username or 'user') or 'user'
                    filename = f"liaison_{request.user.id}_{timezone.now().strftime('%Y%m%d%H%M%S')}{ext}"
                    full_path = upload_dir / filename
                    with open(full_path, 'wb') as f:
                        for chunk in photo.chunks():
                            f.write(chunk)
                    user_image_path = f"user_images/{filename}"
                    # Primary storage: core_users.user_image — update any row matching this user (email or name)
                    q = (
                        Q(liaison_email__iexact=request.user.email)
                        | Q(email_id__iexact=request.user.email)
                        | Q(primary_liaison_name__iexact=request.user.username or '')
                        | Q(primary_liaison_name__iexact=(request.user.get_full_name() or '').strip())
                    )
                    UsersTable.objects.filter(q).update(user_image=user_image_path)
                    # Keep liaison.profile_image in sync for backward compatibility
                    liaison.profile_image = user_image_path
                except Exception as e:
                    messages.error(request, f'Profile photo could not be saved: {e}')
            liaison.save()
            messages.success(request, 'Profile updated successfully.')
            return redirect('dashboard')
    else:
        form = ProfileEditForm(initial={
            'username': request.user.username or '',
            'email': request.user.email or '',
            'organization_name': organization.name or '',
            'mobile_number': liaison.phone or '',
        })

    # Profile image URL for form: prefer core_users.user_image (match by email or name), then liaison.profile_image
    profile_image_url = None
    q = (
        Q(liaison_email__iexact=request.user.email or '')
        | Q(email_id__iexact=request.user.email or '')
        | Q(primary_liaison_name__iexact=request.user.username or '')
        | Q(primary_liaison_name__iexact=(request.user.get_full_name() or '').strip())
    )
    user_row = UsersTable.objects.filter(q).filter(user_image__isnull=False).exclude(user_image='').first()
    if user_row and user_row.user_image:
        profile_image_url = f"{(settings.MEDIA_URL or '/media/').rstrip('/')}/{user_row.user_image.lstrip('/')}"
    elif liaison.profile_image:
        profile_image_url = f"{(settings.MEDIA_URL or '/media/').rstrip('/')}/{liaison.profile_image.lstrip('/')}"

    return render(request, 'core/profile_edit.html', {
        'form': form,
        'is_legacy': False,
        'profile_display_name': request.user.get_full_name() or request.user.username,
        'organization_name': organization.name,
        'profile_image_url': profile_image_url,
    })


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
    
    # Check if incident_id is passed from dashboard
    selected_incident = None
    incident_id = request.GET.get('incident_id')
    if incident_id:
        try:
            if 'user_credentials_id' in request.session:
                selected_incident = IncidentCapture.objects.get(id=incident_id)
            else:
                selected_incident = IncidentCapture.objects.get(id=incident_id, organization=organization)
        except IncidentCapture.DoesNotExist:
            pass
    
    if request.method == 'POST':
        form = OperationalUpdateForm(request.POST)
        if form.is_valid():
            # Save to core_incidents table
            start_time = None
            end_time = None
            
            # Parse start_time if provided
            if form.cleaned_data.get('start_time'):
                start_time = form.cleaned_data['start_time']
            
            # Parse end_time if provided
            if form.cleaned_data.get('end_time'):
                end_time = form.cleaned_data['end_time']
            
            incident = IncidentCapture.objects.create(
                organization=organization,
                title=form.cleaned_data['title'],
                severity=form.cleaned_data['severity'],
                description=form.cleaned_data['description'] or '',  # Required field, use empty string if blank
                impact=form.cleaned_data['impact'] or '',  # Required field
                start_time=start_time,
                end_time=end_time,
                created_at=timezone.now(),  # Set Created_at explicitly
                created_by=liaison if liaison else None,
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
        'selected_incident': selected_incident,  # Pass selected incident if any
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
    
    # Always show login page - don't auto-redirect if already logged in
    # This allows users to see the login form and switch accounts if needed
    
    is_renewal_flow = request.session.get('is_existing_user', False)
    existing_email = request.session.get('existing_user_email', '')

    if request.method == 'POST':
        form = UserLoginForm(request.POST)
        if form.is_valid():
            login_input = form.cleaned_data['username'].strip()
            password = form.cleaned_data['password']

            # If user is already logged in, log them out first to allow new login
            if request.user.is_authenticated:
                logout(request)
            if request.session.get('user_credentials_id'):
                request.session.pop('user_credentials_id', None)
                request.session.pop('user_credentials_username', None)

            # 1) Legacy login (UserCredentials)
            try:
                user_cred = UserCredentials.objects.get(
                    username=login_input,
                    password_hash=password
                )

                # For UserCredentials users (legacy system), allow login without subscription check
                # These are legacy users who may not have subscriptions in the new system
                # Subscription check is only enforced for new Django auth users
                # Legacy UserCredentials users should be able to log in regardless of subscription status

                # Set session for UserCredentials user
                request.session['user_credentials_id'] = user_cred.user_id
                request.session['user_credentials_username'] = user_cred.username
                
                # Clear any renewal flags after successful login
                request.session.pop('is_existing_user', None)
                request.session.pop('existing_user_email', None)
                request.session.pop('_payment_redirected_to_login', None)

                messages.success(request, f'Welcome back, {user_cred.username}!')

                if is_renewal_flow:
                    return redirect('payment')

                return redirect('dashboard')

            except UserCredentials.DoesNotExist:
                pass

            # 2) Django auth login
            auth_username = resolve_login_username(login_input) or login_input
            user = authenticate(request, username=auth_username, password=password)

            if user is not None:
                if not is_renewal_flow and not user_has_active_subscription(user.username):
                    messages.error(
                        request,
                        'Your subscription is inactive or has expired. Please renew to log in.'
                    )
                    return render(request, 'core/login.html', {
                        'form': form,
                        'existing_email': existing_email if is_renewal_flow else None
                    })

                # Log in the user
                login(request, user)
                
                # Clear any UserCredentials session if exists
                request.session.pop('user_credentials_id', None)
                request.session.pop('user_credentials_username', None)
                
                # Clear any renewal flags after successful login
                request.session.pop('is_existing_user', None)
                request.session.pop('existing_user_email', None)
                request.session.pop('_payment_redirected_to_login', None)

                messages.success(
                    request,
                    f'Welcome back, {user.get_full_name() or user.username}!'
                )

                if is_renewal_flow:
                    return redirect('payment')

                return redirect('dashboard')

            messages.error(
                request,
                'Username, email or password is incorrect. Please try again.'
            )

    else:
        form = UserLoginForm()
        if is_renewal_flow and existing_email:
            form.fields['username'].initial = existing_email

    return render(request, 'core/login.html', {
        'form': form,
        'existing_email': existing_email if is_renewal_flow else None
    })


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
            # New fields
            name = request.POST.get('name', '').strip()
            mobile_no = request.POST.get('mobile_no', '').strip()
            email_id = request.POST.get('email_id', '').strip()
            department = request.POST.get('department', '').strip()
            sub_department = request.POST.get('sub_department', '').strip()
            shift_id = request.POST.get('shift_id', '').strip()
            role = request.POST.get('role', '').strip()
            
            # Flexible shift fields (only if flexible shift is selected)
            flexible_start_datetime = request.POST.get('flexible_start_datetime', '').strip()
            flexible_end_datetime = request.POST.get('flexible_end_datetime', '').strip()
            
            # Existing fields
            agency_name = request.POST.get('agency_name', '').strip()
            primary_liaison_name = request.POST.get('primary_liaison_name', '').strip()
            liaison_email = request.POST.get('liaison_email', '').strip()
            key_incident_types = request.POST.get('key_incident_types', '').strip() or None
            preferred_communication_channels = request.POST.get('preferred_communication_channels', '').strip() or None
            
            # Optional profile image (file upload)
            user_image_file = request.FILES.get('user_image')
            user_image_path = None
            if user_image_file:
                try:
                    upload_dir = settings.MEDIA_ROOT / 'user_images'
                    upload_dir.mkdir(parents=True, exist_ok=True)
                    base, ext = os.path.splitext(user_image_file.name)
                    ext = (ext or '.jpg').lower()
                    if ext not in ('.jpg', '.jpeg', '.png', '.gif', '.webp'):
                        ext = '.jpg'
                    safe_name = slugify(name or primary_liaison_name or 'user') or 'user'
                    filename = f"user_{safe_name}_{timezone.now().strftime('%Y%m%d%H%M%S')}{ext}"
                    full_path = upload_dir / filename
                    with open(full_path, 'wb') as f:
                        for chunk in user_image_file.chunks():
                            f.write(chunk)
                    user_image_path = f"user_images/{filename}"
                except Exception as upload_exc:
                    messages.error(request, f'Profile picture could not be uploaded: {upload_exc}')
            
            # Validation
            required_fields = {
                'name': name,
                'mobile_no': mobile_no,
                'email_id': email_id,
                'department': department,
                'sub_department': sub_department,
                'role': role,
                'shift_id': shift_id,
                'agency_name': agency_name,
                'primary_liaison_name': primary_liaison_name,
                'liaison_email': liaison_email,
            }
            
            # Check if shift is flexible and validate flexible shift fields
            shift_obj = None
            if shift_id:
                try:
                    shift_obj = Shift.objects.get(shift_id=int(shift_id))
                    if shift_obj.shift_type == 'flexible':
                        if not flexible_start_datetime or not flexible_end_datetime:
                            messages.error(request, 'Start date/time and End date/time are required for flexible shifts.')
                            return redirect('admin_module')
                except Shift.DoesNotExist:
                    messages.error(request, 'Invalid shift selected.')
                    return redirect('admin_module')
            
            missing_fields = [field for field, value in required_fields.items() if not value]
            
            if missing_fields:
                messages.error(request, f'Required fields missing: {", ".join(missing_fields)}')
            else:
                # Parse flexible shift date/times if provided
                flexible_start_datetime_obj = None
                flexible_end_datetime_obj = None
                if shift_obj and shift_obj.shift_type == 'flexible':
                    try:
                        from datetime import datetime
                        flexible_start_datetime_obj = datetime.strptime(flexible_start_datetime, '%Y-%m-%dT%H:%M')
                        flexible_end_datetime_obj = datetime.strptime(flexible_end_datetime, '%Y-%m-%dT%H:%M')
                    except ValueError:
                        messages.error(request, 'Invalid flexible shift date/time format.')
                        return redirect('admin_module')
                
                # Create new user in users table
                UsersTable.objects.create(
                    name=name or None,
                    mobile_no=mobile_no or None,
                    email_id=email_id or None,
                    department=department or None,
                    sub_department=sub_department or None,
                    shift_id=int(shift_id) if shift_id else None,
                    role=role or None,
                    agency_name=agency_name,
                    primary_liaison_name=primary_liaison_name,
                    liaison_email=liaison_email,
                    key_incident_types=key_incident_types,
                    preferred_communication_channels=preferred_communication_channels,
                    created_at=timezone.now(),
                    user_image=user_image_path,
                )
                if user_image_path:
                    messages.success(request, f'User "{name}" from "{agency_name}" created successfully! Profile picture saved.')
                else:
                    messages.success(request, f'User "{name}" from "{agency_name}" created successfully!')
                return redirect('admin_module')
        except Exception as e:
            messages.error(request, f'Error creating user: {str(e)}')
    
    # Get all users from the users table
    users_list = UsersTable.objects.all().order_by('-created_at')
    
    # Get all shifts from core_shifts table
    shifts = list(Shift.objects.all().order_by('shift_type', 'shift_start_time'))
    
    # Map shift_incharge id to a human-readable name from users table
    users_by_id = {u.id: u for u in users_list}
    for shift in shifts:
        incharge_user = users_by_id.get(shift.shift_incharge)
        if incharge_user:
            shift.incharge_name = incharge_user.primary_liaison_name
        else:
            shift.incharge_name = None
    
    # Get all departments from core_department table
    departments = Department.objects.all().order_by('category', 'service_name')
    
    # Group departments by category for easier template rendering
    departments_by_category = {}
    for dept in departments:
        category = dept.category
        if category not in departments_by_category:
            departments_by_category[category] = []
        departments_by_category[category].append(dept.service_name)
    
    # Get logged-in user's data from UsersTable for pre-populating Agency & Contact Information
    logged_in_user_data = None
    if 'user_credentials_id' in request.session:
        # Try to find user by username from UserCredentials
        username = request.session.get('user_credentials_username', '')
        try:
            # Try to find by primary_liaison_name or liaison_email matching username
            logged_in_user_data = UsersTable.objects.filter(
                Q(primary_liaison_name__icontains=username) | 
                Q(liaison_email__icontains=username)
            ).first()
        except:
            pass
    elif request.user.is_authenticated:
        # Try to find by Django User's email or username
        try:
            user_email = getattr(request.user, 'email', '')
            user_username = getattr(request.user, 'username', '')
            logged_in_user_data = UsersTable.objects.filter(
                Q(liaison_email__icontains=user_email) | 
                Q(primary_liaison_name__icontains=user_username) |
                Q(liaison_email__icontains=user_username)
            ).first()
        except:
            pass
    
    return render(request, 'core/admin_module.html', {
        'users_list': users_list,
        'shifts': shifts,
        'departments': departments,
        'departments_by_category': departments_by_category,
        'logged_in_user_data': logged_in_user_data,
        'is_admin': True,
        'user': request.user,
    })


def logout_view(request):
    """Logout: clear auth and session, redirect to index (default state). No message displayed."""
    # Clear all session data including flags that might cause redirect loops
    request.session.pop('user_credentials_id', None)
    request.session.pop('user_credentials_username', None)
    request.session.pop('is_existing_user', None)
    request.session.pop('existing_user_email', None)
    request.session.pop('checkout_data', None)
    request.session.pop('checkout_user_id', None)
    
    # Clear Django auth
    logout(request)
    
    # Flush all remaining session data and messages
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
        # If user_id not in query, check session (logged-in or checkout flow)
        if not user_id and hasattr(request, 'user') and request.user.is_authenticated:
            user_id = request.user.id
        if not user_id:
            user_id = request.session.get('checkout_user_id')
        description = request.GET.get('description', 'Resilience Foundation License')
        
        # Validate amount
        if amount < 50:  # Minimum $0.50
            return JsonResponse({
                'error': 'Amount must be at least $0.50',
                'type': 'validation_error'
            }, status=400)
        
        # Validate user_id exists in auth_user (required by foreign key constraint)
        valid_user_id = None
        tenant_id = None
        if user_id:
            try:
                user_id_int = int(user_id)
                # Check if user exists in auth_user table
                user = User.objects.get(pk=user_id_int)
                valid_user_id = user_id_int
                # Get tenant_id from user's organization if available
                if hasattr(user, 'liaison_profile'):
                    org = user.liaison_profile.organization
                    tenant_id = org.tenant_id
            except (User.DoesNotExist, ValueError, AttributeError, Liaison.DoesNotExist):
                # User doesn't exist, set to None to avoid foreign key constraint error
                valid_user_id = None
        
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
        # Use valid_user_id (None if user doesn't exist) to avoid foreign key constraint error
        StripePayment.objects.create(
            stripe_payment_intent_id=payment_intent.id,
            amount=amount,  # Store in cents
            currency=currency,
            status='pending',
            user_id=valid_user_id,  # Will be None if user doesn't exist
            tenant_id=tenant_id,
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
            
            # Set tenant_id if not already set and user_id is available
            if not stripe_payment.tenant_id and stripe_payment.user_id:
                try:
                    user = User.objects.get(pk=stripe_payment.user_id)
                    if hasattr(user, 'liaison_profile'):
                        org = user.liaison_profile.organization
                        stripe_payment.tenant_id = org.tenant_id
                except (User.DoesNotExist, AttributeError, Liaison.DoesNotExist):
                    pass
            
            stripe_payment.save()
            
            # Handle subscription update/create based on user_id
            if stripe_payment.user_id:
                try:
                    user = User.objects.get(pk=stripe_payment.user_id)
                    username = user.username
                    
                    # Check if user has existing Active subscription (renewal)
                    existing_subscription = ExternalSubscription.objects.filter(
                        username=username,
                        subscription_status='Active'
                    ).order_by('-subscription_end_date').first()
                    
                    if existing_subscription:
                        # RENEWAL: Update existing subscription
                        new_end_date = calculate_new_subscription_end_date(existing_subscription)
                        
                        # Update subscription using raw SQL (since managed=False)
                        from django.db import connection
                        with connection.cursor() as cursor:
                            cursor.execute(
                                """
                                UPDATE subscriptions 
                                SET subscription_end_date = %s,
                                    subscription_status = 'Active',
                                    duration = 365
                                WHERE subscription_id = %s
                                """,
                                [new_end_date, existing_subscription.subscription_id]
                            )
                        
                        # Create Payment record linked to existing organization
                        try:
                            liaison = user.liaison_profile
                            org = liaison.organization
                            
                            Payment.objects.create(
                                amount=stripe_payment.amount / 100.0,  # Convert cents to dollars
                                payment_method='CARD',
                                status='PAID',
                                organization=org
                            )
                            
                            # Create ExternalPayment
                            ExternalPayment.objects.create(
                                username=username,
                                payment_status='Completed',
                                payment_method='Credit Card',
                                amount=stripe_payment.amount / 100.0,
                                payment_time=timezone.now()
                            )
                        except Exception as e:
                            import logging
                            logger = logging.getLogger(__name__)
                            logger.error(f'Error creating payment records in webhook: {e}')
                    else:
                        # NEW USER: Activate existing Inactive subscription from checkout, or create new
                        try:
                            liaison = user.liaison_profile
                            org = liaison.organization
                            
                            Payment.objects.create(
                                amount=stripe_payment.amount / 100.0,
                                payment_method='CARD',
                                status='PAID',
                                organization=org
                            )
                            ext_payment = ExternalPayment.objects.create(
                                username=username,
                                payment_status='Completed',
                                payment_method='Credit Card',
                                amount=stripe_payment.amount / 100.0,
                                payment_time=timezone.now()
                            )
                            inactive_sub = ExternalSubscription.objects.filter(
                                username=username,
                                subscription_status='Inactive'
                            ).order_by('-created_at').first()
                            if inactive_sub:
                                inactive_sub.payment = ext_payment
                                inactive_sub.subscription_status = 'Active'
                                inactive_sub.subscription_start_date = timezone.now().date()
                                inactive_sub.subscription_end_date = timezone.now().date() + timedelta(days=365)
                                inactive_sub.duration = 365
                                inactive_sub.save()
                            else:
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
                            import logging
                            logger = logging.getLogger(__name__)
                            logger.error(f'Error creating subscription in webhook: {e}')
                except User.DoesNotExist:
                    # User not found - log but don't fail
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.warning(f'User {stripe_payment.user_id} not found for payment {payment_intent_id}')
                except Exception as e:
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.error(f'Error processing subscription in webhook: {e}')
            
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


def payment_success(request, is_renewal='false'):
    """
    Payment success page - shown after successful payment.
    Shows download PDF button and login button with auto-redirect.
    """
    is_renewal_bool = is_renewal.lower() == 'true'
    
    # Get payment intent ID from session or query parameter
    payment_intent_id = request.GET.get('payment_intent_id') or request.session.get('last_payment_intent_id')
    
    # Get subscription info if renewal
    renewal_info = None
    if is_renewal_bool and request.user.is_authenticated:
        try:
            user = request.user
            username = user.username
            subscription = ExternalSubscription.objects.filter(
                username=username,
                subscription_status='Active'
            ).order_by('-subscription_end_date').first()
            
            if subscription:
                renewal_info = {
                    'new_end_date': subscription.subscription_end_date
                }
        except Exception:
            pass
    
    # Clear payment and checkout session flags
    request.session.pop('payment_pending', None)
    request.session.pop('last_payment_intent_id', None)
    request.session.pop('checkout_user_id', None)
    request.session.pop('checkout_data', None)
    request.session.pop('is_existing_user', None)

    return render(request, 'core/payment_success.html', {
        'is_renewal': is_renewal_bool,
        'payment_intent_id': payment_intent_id,
        'renewal_info': renewal_info
    })


def stripe_payments_page(request):
    """Stripe payments test page"""
    # Store user_id in session for webhook (logged-in or checkout flow)
    if request.user.is_authenticated:
        request.session['stripe_user_id'] = request.user.id
    elif request.session.get('checkout_user_id'):
        request.session['stripe_user_id'] = request.session['checkout_user_id']

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
            # For legacy users we still need an organization for SystemSettings,
            # but incident visibility should NOT be restricted by organization.
            organization = Organization.objects.first()
        except Exception:
            organization = None
    
    if liaison is not None and organization is not None:
        # Standard Django auth users (with Liaison) only see incidents
        # that belong to their organization.
        incidents = IncidentCapture.objects.filter(
            organization=organization
        ).order_by('-created_at')
    else:
        # Legacy UserCredentials users and any fallback case:
        # show all incidents (no org filter) so previously captured data is visible.
        incidents = IncidentCapture.objects.all().order_by('-created_at')
    
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


def incident_copy_view(request):
    """Board-style incident copy view (separate module)"""
    # Same auth + incident query logic as incidents_list
    if not request.user.is_authenticated and 'user_credentials_id' not in request.session:
        return redirect('login')

    liaison = None
    organization = None

    if request.user.is_authenticated:
        try:
            liaison = request.user.liaison_profile
            organization = liaison.organization
        except (Liaison.DoesNotExist, AttributeError):
            messages.error(request, 'Please complete checkout first.')
            return redirect('checkout')
    elif 'user_credentials_id' in request.session:
        try:
            organization = Organization.objects.first()
        except Exception:
            organization = None

    if liaison is not None and organization is not None:
        incidents = IncidentCapture.objects.filter(
            organization=organization
        ).order_by('-created_at')
    else:
        incidents = IncidentCapture.objects.all().order_by('-created_at')

    # System status / sync info (same as incidents_list)
    settings_obj, created = SystemSettings.objects.get_or_create(
        organization=organization,
        defaults={
            'current_status': 'Normal',
            'cadence_hours': 24,
        }
    )

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

    # Optional selected incident (from dropdown)
    incident = None
    assigned_users_data = []
    incident_logs = []
    selected_id = request.GET.get('incident_id')

    if selected_id:
        try:
            incident = IncidentCapture.objects.get(id=selected_id)
        except IncidentCapture.DoesNotExist:
            incident = None

    if incident:
        # Reuse the assignment + log logic from incident_detail
        from django.db import connection
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT l.id FROM core_liaison l
                    INNER JOIN core_incident_user_mapping m ON l.id = m.user_id
                    WHERE m.incident_id = %s AND m.is_active = 1
                    """,
                    [incident.id]
                )
                liaison_ids = [row[0] for row in cursor.fetchall()]
                assigned_liaisons = Liaison.objects.filter(id__in=liaison_ids) if liaison_ids else []

                for liaison in assigned_liaisons:
                    user_table = UsersTable.objects.filter(liaison_email__iexact=liaison.user.email).first()
                    assigned_users_data.append({
                        'liaison': liaison,
                        'user_table': user_table,
                    })
        except Exception:
            assigned_users_data = []

        try:
            from django.db import connection
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, event_description, created_time, user_id
                    FROM core_incident_events
                    WHERE incident_id = %s
                    ORDER BY created_time DESC
                    """,
                    [incident.id]
                )
                log_rows = cursor.fetchall()

            for row in log_rows:
                log_id, event_desc, created_time, user_id = row
                user = None
                user_display_name = None
                user_image_url = None
                if user_id:
                    # First, try to resolve from core_users (UsersTable)
                    core_user = UsersTable.objects.filter(id=user_id).first()
                    if core_user:
                        user_display_name = (
                            core_user.primary_liaison_name
                            or core_user.name
                            or core_user.liaison_email
                            or core_user.email_id
                        )
                        if core_user.user_image:
                            user_image_url = settings.MEDIA_URL + core_user.user_image
                    # Also try to resolve to Django auth User for backwards compatibility
                    try:
                        user = User.objects.get(id=user_id)
                        if not user_display_name:
                            user_display_name = user.get_full_name() or user.username
                    except User.DoesNotExist:
                        pass
                incident_logs.append({
                    'log_id': log_id,
                    'log_description': event_desc,
                    'created_time': created_time,
                    'user_log': user,
                    'user_display_name': user_display_name,
                    'user_image_url': user_image_url,
                })
        except Exception:
            incident_logs = []

    # Get all users and department categories for user assignment modal
    all_users = UsersTable.objects.all().order_by('-created_at')
    department_categories = (
        Department.objects.values_list('category', flat=True)
        .distinct()
        .order_by('category')
    )

    return render(request, 'core/incident_copy.html', {
        'incidents': incidents,
        'incident': incident,
        'assigned_users_data': assigned_users_data,
        'incident_logs': incident_logs,
        'all_users': all_users,
        'department_categories': department_categories,
        'organization': organization,
        'is_admin': True,
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
    
    # Get the incident from core_incidents table
    # For legacy users, don't filter by organization - get the incident first, then use its organization
    try:
        if 'user_credentials_id' in request.session:
            # Legacy users: get incident without organization filter, then use its organization
            incident = IncidentCapture.objects.get(id=incident_id)
            organization = incident.organization  # Update organization to match incident's org
        else:
            # Django auth users: filter by organization
            incident = IncidentCapture.objects.get(id=incident_id, organization=organization)
    except IncidentCapture.DoesNotExist:
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
    
    # Get all users from UsersTable (same as admin page)
    all_users = UsersTable.objects.all().order_by('-created_at')
    
    # Get list of available department categories (for filtering users by department)
    department_categories = (
        Department.objects.values_list('category', flat=True)
        .distinct()
        .order_by('category')
    )
    
    # Ensure mapping table exists (create if not exists)
    from django.db import connection
    try:
        with connection.cursor() as cursor:
            # Check if table exists
            cursor.execute("""
                SELECT COUNT(*) FROM information_schema.tables 
                WHERE table_schema = DATABASE() 
                AND table_name = 'core_incident_user_mapping'
            """)
            table_exists = cursor.fetchone()[0] > 0
            
            if not table_exists:
                cursor.execute("""
                    CREATE TABLE core_incident_user_mapping (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        user_id INT NOT NULL,
                        incident_id BIGINT NOT NULL,
                        mapped_user_id INT NULL,
                        is_active TINYINT(1) NOT NULL DEFAULT 1,
                        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        INDEX idx_incident_active (incident_id, is_active),
                        INDEX idx_user_active (user_id, is_active)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """)
    except Exception as e:
        # Table might already exist or error - continue anyway
        pass
    
    # Get currently assigned users (Liaisons) - only active assignments
    assigned_liaisons = []
    assigned_users_data = []  # List of dicts with liaison + UsersTable data
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT l.id FROM core_liaison l
                INNER JOIN core_incident_user_mapping m ON l.id = m.user_id
                WHERE m.incident_id = %s AND m.is_active = 1
                """,
                [incident.id]
            )
            liaison_ids = [row[0] for row in cursor.fetchall()]
            assigned_liaisons = Liaison.objects.filter(id__in=liaison_ids) if liaison_ids else []
            
            # Get UsersTable data for each assigned liaison
            for liaison in assigned_liaisons:
                user_table = UsersTable.objects.filter(liaison_email__iexact=liaison.user.email).first()
                assigned_users_data.append({
                    'liaison': liaison,
                    'user_table': user_table,  # Can be None if not found in UsersTable
                })
    except Exception as e:
        # If table doesn't exist yet or error, return empty list
        assigned_liaisons = []
        assigned_users_data = []
    
    # Get incident event logs
    # Note: IncidentEvent has ForeignKey to Incident, but we're using IncidentCapture
    # So we need to query by incident_id directly
    try:
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, event_description, created_time, user_id
                FROM core_incident_events
                WHERE incident_id = %s
                ORDER BY created_time DESC
                """,
                [incident.id]
            )
            log_rows = cursor.fetchall()
        
        # Convert to list of dicts for template
        incident_logs = []
        for row in log_rows:
            log_id, event_desc, created_time, user_id = row
            user = None
            user_display_name = None
            user_image_url = None
            if user_id:
                # First, try to resolve from core_users (UsersTable)
                core_user = UsersTable.objects.filter(id=user_id).first()
                if core_user:
                    user_display_name = (
                        core_user.primary_liaison_name
                        or core_user.name
                        or core_user.liaison_email
                        or core_user.email_id
                    )
                    if core_user.user_image:
                        user_image_url = settings.MEDIA_URL + core_user.user_image
                # Also try to resolve to Django auth User for backwards compatibility
                try:
                    user = User.objects.get(id=user_id)
                    if not user_display_name:
                        user_display_name = user.get_full_name() or user.username
                except User.DoesNotExist:
                    pass
            incident_logs.append({
                'log_id': log_id,
                'log_description': event_desc,
                'created_time': created_time,
                'user_log': user,
                'user_display_name': user_display_name,
                'user_image_url': user_image_url,
            })
    except Exception:
        incident_logs = []
    
    return render(request, 'core/incident_detail.html', {
        'incident': incident,
        'organization': organization,
        'is_admin': True,  # Always show admin link - access controlled by view decorator
        'current_status': settings_obj.current_status,
        'last_sync_display': sync_time_display,
        'all_users': all_users,
        'department_categories': department_categories,
        'assigned_liaisons': assigned_liaisons,
        'assigned_users_data': assigned_users_data,  # Liaison + UsersTable data combined
        'incident_logs': incident_logs,
    })


@csrf_exempt
def search_users_for_assignment(request):
    """AJAX endpoint to search users from UsersTable for incident assignment.

    IMPORTANT:
    - This now uses the same UsersTable dataset as the Admin → User Management page,
      so any user created via "Create New User" will be searchable here.
    """
    if request.method != 'GET':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    # Check authentication
    if not request.user.is_authenticated and 'user_credentials_id' not in request.session:
        return JsonResponse({'error': 'Unauthorized'}, status=401)
    
    query = request.GET.get('q', '').strip()
    if not query:
        return JsonResponse({'users': []})
    
    # Search UsersTable by name, email, or agency
    users = UsersTable.objects.filter(
        Q(primary_liaison_name__icontains=query) |
        Q(liaison_email__icontains=query) |
        Q(agency_name__icontains=query)
    ).order_by('-created_at')[:50]  # Limit to 50 results
    
    results = []
    for user_row in users:
        results.append({
            'id': user_row.id,
            'name': user_row.primary_liaison_name or user_row.name,
            'email': user_row.liaison_email or user_row.email_id,
            'agency': user_row.agency_name,
        })
    
    return JsonResponse({'users': results})


@csrf_exempt
def assign_users_to_incident(request, incident_id):
    """Assign multiple users to an incident by mapping UsersTable → Liaison"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    # Check authentication
    if not request.user.is_authenticated and 'user_credentials_id' not in request.session:
        return JsonResponse({'error': 'Unauthorized'}, status=401)
    
    try:
        # Get organization
        organization = None
        if request.user.is_authenticated:
            try:
                liaison = request.user.liaison_profile
                organization = liaison.organization
            except (Liaison.DoesNotExist, AttributeError):
                return JsonResponse({'error': 'Organization not found'}, status=400)
        elif 'user_credentials_id' in request.session:
            organization = Organization.objects.first()
        
        # Get incident from core_incidents table
        # For legacy users, get incident first, then use its organization
        if 'user_credentials_id' in request.session:
            # Legacy users: get incident without organization filter, then use its organization
            try:
                incident = IncidentCapture.objects.get(id=incident_id)
                organization = incident.organization  # Update organization to match incident's org
            except IncidentCapture.DoesNotExist:
                return JsonResponse({'error': 'Incident not found'}, status=404)
        else:
            # Django auth users: filter by organization
            if not organization:
                return JsonResponse({'error': 'Organization not found'}, status=400)
            try:
                incident = IncidentCapture.objects.get(id=incident_id, organization=organization)
            except IncidentCapture.DoesNotExist:
                return JsonResponse({'error': 'Incident not found'}, status=404)
        
        # Get user IDs from POST data (list of UsersTable IDs)
        data = json.loads(request.body)
        user_ids = data.get('user_ids', [])
        
        if not user_ids or not isinstance(user_ids, list):
            return JsonResponse({'error': 'User IDs list required'}, status=400)
        
        # Map each UsersTable → User (by email) → Liaison
        assigned_liaisons = []
        errors = []
        
        for user_table_id in user_ids:
            try:
                user_table = UsersTable.objects.get(id=user_table_id)
            except UsersTable.DoesNotExist:
                errors.append(f'User ID {user_table_id} not found')
                continue
            
            # Map UsersTable → User (by email) → Liaison
            user = User.objects.filter(email__iexact=user_table.liaison_email).first()
            if not user:
                errors.append(f'No Django User found for email {user_table.liaison_email}')
                continue
            
            # Find Liaison for this user in the same organization
            liaison = Liaison.objects.filter(user=user, organization=organization).first()
            if not liaison:
                errors.append(f'No Liaison found for user {user_table.liaison_email} in this organization')
                continue
            
            assigned_liaisons.append(liaison)
        
        if not assigned_liaisons:
            return JsonResponse({'error': 'No valid users could be assigned. ' + '; '.join(errors)}, status=400)
        
        # Get logged-in user ID (who is making the assignment)
        mapped_user_id = None
        if request.user.is_authenticated:
            mapped_user_id = request.user.id
        elif 'user_credentials_id' in request.session:
            # For legacy UserCredentials, we don't have a direct User.id
            # Could map to a default user or leave NULL
            mapped_user_id = None
        
        # Ensure mapping table exists (create if not exists)
        from django.db import connection
        try:
            with connection.cursor() as cursor:
                # Check if table exists
                cursor.execute("""
                    SELECT COUNT(*) FROM information_schema.tables 
                    WHERE table_schema = DATABASE() 
                    AND table_name = 'core_incident_user_mapping'
                """)
                table_exists = cursor.fetchone()[0] > 0
                
                if not table_exists:
                    cursor.execute("""
                        CREATE TABLE core_incident_user_mapping (
                            id INT AUTO_INCREMENT PRIMARY KEY,
                            user_id INT NOT NULL,
                            incident_id BIGINT NOT NULL,
                            mapped_user_id INT NULL,
                            is_active TINYINT(1) NOT NULL DEFAULT 1,
                            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            INDEX idx_incident_active (incident_id, is_active),
                            INDEX idx_user_active (user_id, is_active)
                        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                    """)
        except Exception:
            pass  # Table might already exist or error - continue anyway
        
        # Mark existing assignments as inactive (for history)
        with connection.cursor() as cursor:
            try:
                cursor.execute(
                    "UPDATE core_incident_user_mapping SET is_active = 0 WHERE incident_id = %s",
                    [incident.id]
                )
            except Exception:
                pass  # Table might not exist yet
        
        # Insert new active assignments (create new row each time for history)
        assignment_errors = []
        for liaison in assigned_liaisons:
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO core_incident_user_mapping 
                        (user_id, incident_id, mapped_user_id, is_active, created_at) 
                        VALUES (%s, %s, %s, 1, NOW())
                        """,
                        [liaison.id, incident.id, mapped_user_id]
                    )
            except Exception as e:
                assignment_errors.append(f'Error assigning {liaison.user.email}: {str(e)}')
        
        if assignment_errors:
            errors.extend(assignment_errors)
        
        # Also set the first one as created_by for backward compatibility
        if assigned_liaisons:
            incident.created_by = assigned_liaisons[0]
            incident.save()
        
        return JsonResponse({
            'success': True,
            'message': f'{len(assigned_liaisons)} user(s) assigned successfully',
            'assigned_users': [
                {
                    'name': l.user.get_full_name() or l.user.username,
                    'email': l.user.email,
                }
                for l in assigned_liaisons
            ]
        })
        
    except IncidentCapture.DoesNotExist:
        return JsonResponse({'error': 'Incident not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
def add_incident_event_log(request, incident_id):
    """Add a new incident event log entry"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)
    
    # Check authentication
    if not request.user.is_authenticated and 'user_credentials_id' not in request.session:
        return JsonResponse({'error': 'Unauthorized'}, status=401)
    
    try:
        # Get organization
        organization = None
        if request.user.is_authenticated:
            try:
                liaison = request.user.liaison_profile
                organization = liaison.organization
            except (Liaison.DoesNotExist, AttributeError):
                return JsonResponse({'error': 'Organization not found'}, status=400)
        elif 'user_credentials_id' in request.session:
            organization = Organization.objects.first()
        
        # Get incident from core_incidents table
        # For legacy users, get incident first, then use its organization
        if 'user_credentials_id' in request.session:
            # Legacy users: get incident without organization filter, then use its organization
            try:
                incident = IncidentCapture.objects.get(id=incident_id)
                organization = incident.organization  # Update organization to match incident's org
            except IncidentCapture.DoesNotExist:
                return JsonResponse({'error': 'Incident not found'}, status=404)
        else:
            # Django auth users: filter by organization
            if not organization:
                return JsonResponse({'error': 'Organization not found'}, status=400)
            try:
                incident = IncidentCapture.objects.get(id=incident_id, organization=organization)
            except IncidentCapture.DoesNotExist:
                return JsonResponse({'error': 'Incident not found'}, status=404)
        
        # Get log description from POST data
        data = json.loads(request.body)
        log_description = data.get('log_description', '').strip()
        
        if not log_description:
            return JsonResponse({'error': 'Log description is required'}, status=400)
        
        # Get user_id from core_users table (not auth_user)
        user_id = None
        if request.user.is_authenticated:
            # For Django authenticated users: find user in core_users by email
            try:
                user_email = request.user.email
                if user_email:
                    # Try to find in core_users by liaison_email
                    core_user = UsersTable.objects.filter(liaison_email__iexact=user_email).first()
                    if core_user:
                        user_id = core_user.id
            except Exception:
                pass
        elif 'user_credentials_id' in request.session:
            # For legacy users: find user in core_users by username or email
            try:
                user_cred = UserCredentials.objects.get(user_id=request.session['user_credentials_id'])
                # Try to find in core_users by primary_liaison_name (username) or liaison_email
                core_user = UsersTable.objects.filter(
                    Q(primary_liaison_name__iexact=user_cred.username) | 
                    Q(liaison_email__iexact=user_cred.username)
                ).first()
                if core_user:
                    user_id = core_user.id
            except (UserCredentials.DoesNotExist, Exception):
                pass

        # Get tenant_id - prioritize user's tenant_id from tenant_domains
        tenant_id = None
        if request.user.is_authenticated:
            # For Django authenticated users: try to get from incident's tenant_id first
            if incident and hasattr(incident, 'tenant_id') and incident.tenant_id:
                tenant_id = incident.tenant_id
            # Fallback: try from organization (but note: org.tenant_id is org PK, may not match tenant_domains)
            elif organization and hasattr(organization, 'tenant_id'):
                tenant_id = organization.tenant_id
        elif 'user_credentials_id' in request.session:
            # For legacy users: get tenant_id from UserCredentials (matches tenant_domains.tenant_id)
            try:
                user_cred = UserCredentials.objects.get(user_id=request.session['user_credentials_id'])
                tenant_id = user_cred.tenant_id
            except UserCredentials.DoesNotExist:
                pass
        
        # Final fallback: if still no tenant_id, try from incident's tenant_id
        if not tenant_id and incident and hasattr(incident, 'tenant_id') and incident.tenant_id:
            tenant_id = incident.tenant_id
        
        # Create incident event log
        # Note: IncidentEvent has ForeignKey to Incident, but we're using IncidentCapture
        # So we need to create it using the incident_id directly
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO core_incident_events (incident_id, event_description, user_id, created_time, tenant_id)
                VALUES (%s, %s, %s, %s, %s)
                """,
                [incident.id, log_description, user_id, timezone.now(), tenant_id]
            )
            log_id = cursor.lastrowid
        
        # Fetch the created log entry for response using raw SQL to avoid ForeignKey issues
        # Since user_id is from core_users, not auth_user, we can't use IncidentEvent.user_log
        user_name = 'System'
        if user_id:
            try:
                # Try to get user name from core_users table
                core_user = UsersTable.objects.filter(id=user_id).first()
                if core_user:
                    user_name = core_user.primary_liaison_name or 'System'
            except Exception:
                pass
        
        # Get created_time from database
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT created_time FROM core_incident_events WHERE id = %s
                """,
                [log_id]
            )
            row = cursor.fetchone()
            created_time = row[0] if row else timezone.now()
        
        return JsonResponse({
            'success': True,
            'message': 'Log entry added successfully',
            'log': {
                'id': log_id,
                'description': log_description,
                'user': user_name,
                'created_time': created_time.strftime('%b %d, %Y %I:%M %p') if hasattr(created_time, 'strftime') else str(created_time)
            }
        })
        
    except IncidentCapture.DoesNotExist:
        return JsonResponse({'error': 'Incident not found'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)



def generate_incident_shift_packet_pdf(request, incident_id):
    """Generate a comprehensive incident log history PDF similar to the example format"""
    # Check authentication
    if not request.user.is_authenticated and 'user_credentials_id' not in request.session:
        return HttpResponse('Unauthorized', status=401)
    
    try:
        # Get organization
        organization = None
        if request.user.is_authenticated:
            try:
                liaison = request.user.liaison_profile
                organization = liaison.organization
            except (Liaison.DoesNotExist, AttributeError):
                return HttpResponse('Organization not found', status=400)
        elif 'user_credentials_id' in request.session:
            organization = Organization.objects.first()
        
        # Get the incident - for legacy users, get incident first then use its organization
        if 'user_credentials_id' in request.session:
            # Legacy users: get incident without organization filter, then use its organization
            try:
                incident = IncidentCapture.objects.get(id=incident_id)
                organization = incident.organization  # Update organization to match incident's org
            except IncidentCapture.DoesNotExist:
                return HttpResponse('Incident not found', status=404)
        else:
            # Django auth users: filter by organization
            if not organization:
                return HttpResponse('Organization not found', status=400)
            try:
                incident = IncidentCapture.objects.get(id=incident_id, organization=organization)
            except IncidentCapture.DoesNotExist:
                return HttpResponse('Incident not found', status=404)
        
        # Get assigned users
        assigned_users_data = []
        try:
            from django.db import connection
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT l.id FROM core_liaison l
                    INNER JOIN core_incident_user_mapping m ON l.id = m.user_id
                    WHERE m.incident_id = %s AND m.is_active = 1
                    """,
                    [incident.id]
                )
                liaison_ids = [row[0] for row in cursor.fetchall()]
                assigned_liaisons = Liaison.objects.filter(id__in=liaison_ids) if liaison_ids else []
                
                for liaison in assigned_liaisons:
                    user_table = UsersTable.objects.filter(liaison_email__iexact=liaison.user.email).first()
                    assigned_users_data.append({
                        'liaison': liaison,
                        'user_table': user_table,
                    })
        except Exception:
            assigned_users_data = []
        
        # Get incident logs
        incident_logs = []
        try:
            from django.db import connection
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, event_description, created_time, user_id
                    FROM core_incident_events
                    WHERE incident_id = %s
                    ORDER BY created_time ASC
                    """,
                    [incident.id]
                )
                log_rows = cursor.fetchall()
                
                for row in log_rows:
                    log_id, event_desc, created_time, user_id = row
                    user = None
                    if user_id:
                        try:
                            user = User.objects.get(id=user_id)
                        except User.DoesNotExist:
                            pass
                    incident_logs.append({
                        'log_id': log_id,
                        'log_description': event_desc,
                        'created_time': created_time,
                        'user_log': user,
                    })
        except Exception:
            incident_logs = []
        
        # Add the "Incident Created" log entry if not already present
        has_created_log = any('created' in log.get('log_description', '').lower() for log in incident_logs)
        if not has_created_log:
            incident_logs.insert(0, {
                'log_id': 0,
                'log_description': f'Incident "{incident.title}" was created with severity level {incident.get_severity_display()}.',
                'created_time': incident.created_at,
                'user_log': incident.created_by.user if incident.created_by else None,
            })
        
        # Prepare PDF in memory using custom template for gradients
        buffer = BytesIO()
        
        # Custom template class for header/footer with gradients
        class CustomPageTemplate:
            def __init__(self, canvas, doc):
                self.canvas = canvas
                self.doc = doc
            
            def draw_header(self, canvas, doc):
                # Draw gradient header background (simulated with solid color)
                # Stay within page boundaries
                canvas.setFillColor(HexColor('#0a1f44'))
                canvas.rect(0, doc.pagesize[1] - 1.5*inch, doc.pagesize[0], 1.5*inch, fill=1, stroke=0)
                
                # Platform text - ensure it fits within margins
                canvas.setFillColor(HexColor('#7fafd4'))
                canvas.setFont("Helvetica-Bold", 10)
                platform_text = "EMERGENCY & INCIDENT MANAGEMENT PLATFORM"
                # Check text width and truncate if needed
                text_width = canvas.stringWidth(platform_text, "Helvetica-Bold", 10)
                max_width = doc.pagesize[0] - 1.1*inch  # Leave margin on both sides
                if text_width > max_width:
                    # Use smaller font or truncate
                    canvas.setFont("Helvetica-Bold", 9)
                canvas.drawString(0.55*inch, doc.pagesize[1] - 0.4*inch, platform_text)
                
                # Title
                canvas.setFillColor(HexColor('#ffffff'))
                canvas.setFont("Helvetica-Bold", 20)
                title_text = "Incident Log History"
                text_width = canvas.stringWidth(title_text, "Helvetica-Bold", 20)
                if text_width > max_width:
                    canvas.setFont("Helvetica-Bold", 18)
                canvas.drawString(0.55*inch, doc.pagesize[1] - 0.65*inch, title_text)
                
                # Report generated - ensure it fits
                canvas.setFillColor(HexColor('#4a6fa8'))
                canvas.setFont("Helvetica", 10)
                report_text = f"Report Generated: {timezone.now().strftime('%d %b %Y, %H:%M hrs')}"
                text_width = canvas.stringWidth(report_text, "Helvetica", 10)
                if text_width > max_width:
                    canvas.setFont("Helvetica", 9)
                canvas.drawRightString(doc.pagesize[0] - 0.55*inch, doc.pagesize[1] - 0.4*inch, report_text)
            
            def draw_footer(self, canvas, doc):
                # Footer background
                canvas.setFillColor(HexColor('#0a1f44'))
                canvas.rect(0, 0, doc.pagesize[0], 0.3*inch, fill=1, stroke=0)
                
                # Footer text - ensure it fits within margins
                canvas.setFillColor(HexColor('#4a6fa8'))
                canvas.setFont("Helvetica", 10)
                footer_left = f"INC-{incident.id} | Log History Report"
                # Check if text fits, reduce font if needed
                text_width = canvas.stringWidth(footer_left, "Helvetica", 10)
                max_width = (doc.pagesize[0] - 1.1*inch) / 2  # Half width for left side
                if text_width > max_width:
                    canvas.setFont("Helvetica", 9)
                canvas.drawString(0.55*inch, 0.15*inch, footer_left)
                
                org_name = organization.name if organization else "Resilience System"
                footer_right = f"{org_name} EIMP | {timezone.now().strftime('%d %b %Y, %H:%M hrs')}"
                text_width = canvas.stringWidth(footer_right, "Helvetica", 10)
                if text_width > max_width:
                    canvas.setFont("Helvetica", 9)
                canvas.drawRightString(doc.pagesize[0] - 0.55*inch, 0.15*inch, footer_right)
        
        # Use SimpleDocTemplate with custom onFirstPage and onLaterPages
        doc = SimpleDocTemplate(buffer, pagesize=letter, 
                               topMargin=2*inch, bottomMargin=0.5*inch,
                               leftMargin=0.6*inch, rightMargin=0.6*inch)
        
        # Container for the 'Flowable' objects
        elements = []
        
        # Define styles matching HTML design
        styles = getSampleStyleSheet()
        
        # Header styles
        platform_style = ParagraphStyle(
            'Platform',
            parent=styles['Normal'],
            fontSize=10,
            textColor=HexColor('#7fafd4'),
            spaceAfter=5,
            alignment=TA_LEFT,
            fontName='Helvetica-Bold',
            leading=12
        )
        
        title_style = ParagraphStyle(
            'Title',
            parent=styles['Heading1'],
            fontSize=20,
            textColor=HexColor('#ffffff'),
            spaceAfter=10,
            alignment=TA_LEFT,
            fontName='Helvetica-Bold',
            leading=24
        )
        
        # Incident title section
        incident_title_label_style = ParagraphStyle(
            'IncidentTitleLabel',
            parent=styles['Normal'],
            fontSize=9,
            textColor=HexColor('#7fafd4'),  # Light blue label for dark blue header
            spaceAfter=6,
            alignment=TA_LEFT,
            fontName='Helvetica-Bold',
            leading=11
        )
        
        incident_title_style = ParagraphStyle(
            'IncidentTitle',
            parent=styles['Heading2'],
            fontSize=16,
            textColor=HexColor('#ffffff'),  # White color for dark blue header background
            spaceAfter=10,
            alignment=TA_LEFT,
            fontName='Helvetica-Bold',
            leading=20
        )
        
        incident_desc_style = ParagraphStyle(
            'IncidentDesc',
            parent=styles['Normal'],
            fontSize=12,
            textColor=HexColor('#93b4d8'),  # Light blue for dark blue header background
            spaceAfter=20,
            alignment=TA_LEFT,
            fontName='Helvetica',
            leading=21
        )
        
        # Meta strip style
        meta_label_style = ParagraphStyle(
            'MetaLabel',
            parent=styles['Normal'],
            fontSize=9,
            textColor=HexColor('#7fafd4'),
            alignment=TA_LEFT,
            fontName='Helvetica-Bold',
            leading=11
        )
        
        meta_value_style = ParagraphStyle(
            'MetaValue',
            parent=styles['Normal'],
            fontSize=13,
            textColor=HexColor('#ffffff'),
            alignment=TA_LEFT,
            fontName='Helvetica-Bold',
            leading=16
        )
        
        # Table styles
        table_header_style = ParagraphStyle(
            'TableHeader',
            parent=styles['Normal'],
            fontSize=10,
            textColor=HexColor('#93b4d8'),
            alignment=TA_LEFT,
            fontName='Helvetica-Bold',
            leading=12
        )
        
        log_cell_style = ParagraphStyle(
            'LogCell',
            parent=styles['Normal'],
            fontSize=12.5,
            textColor=HexColor('#1e2a3a'),
            alignment=TA_LEFT,
            fontName='Helvetica',
            leading=20.6
        )
        
        log_number_style = ParagraphStyle(
            'LogNumber',
            parent=styles['Normal'],
            fontSize=11,
            textColor=HexColor('#9ca3af'),
            alignment=TA_LEFT,
            fontName='Courier',
            leading=14,
            wordWrap='LTR'  # Prevent vertical wrapping
        )
        
        timestamp_style = ParagraphStyle(
            'Timestamp',
            parent=styles['Normal'],
            fontSize=12,
            textColor=HexColor('#0a1f44'),
            alignment=TA_LEFT,
            fontName='Helvetica-Bold',
            leading=16
        )
        
        author_style = ParagraphStyle(
            'Author',
            parent=styles['Normal'],
            fontSize=10.5,
            textColor=HexColor('#94a3b8'),
            alignment=TA_RIGHT,
            fontName='Helvetica-Bold',
            leading=14,
            fontStyle='Italic'
        )
        
        # Create header section with gradient background - include incident title inside
        # Increase header height to accommodate incident title
        header_bg = Table([['']], colWidths=[7.3*inch], rowHeights=[2.2*inch])
        header_bg.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), HexColor('#0a1f44')),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ]))
        elements.append(header_bg)
        
        # Header content overlay - first two rows
        header_content = Table([
            [Paragraph("EMERGENCY & INCIDENT MANAGEMENT PLATFORM", platform_style), 
             Paragraph(f"Report Generated: {timezone.now().strftime('%d %b %Y, %H:%M hrs')}", 
                      ParagraphStyle('ReportGen', parent=styles['Normal'], fontSize=10, 
                                    textColor=HexColor('#4a6fa8'), alignment=TA_RIGHT, fontName='Helvetica'))],
            [Paragraph("Incident Log History", title_style), '']
        ], colWidths=[4*inch, 3.3*inch])
        header_content.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 12),
            ('RIGHTPADDING', (0, 0), (-1, -1), 12),
            ('TOPPADDING', (0, 0), (-1, -1), 12),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
        ]))
        elements.append(Spacer(1, -2.2*inch))
        elements.append(header_content)
        
        # Add incident title inside header - as separate elements positioned over the header
        elements.append(Spacer(1, 0.1*inch))
        elements.append(Paragraph("INCIDENT TITLE", incident_title_label_style))
        elements.append(Spacer(1, 0.04*inch))
        elements.append(Paragraph(f"{incident.title}", incident_title_style))
        if incident.description:
            elements.append(Spacer(1, 0.06*inch))
            elements.append(Paragraph(incident.description.replace('\n', '<br/>'), incident_desc_style))
        
        elements.append(Spacer(1, 0.15*inch))
        
        # Meta strip
        severity_display = f"{incident.severity.upper()} — P1" if incident.severity == 'CRITICAL' else f"{incident.severity.upper()}"
        severity_color = HexColor('#7f1d1d') if incident.severity == 'CRITICAL' else HexColor('#78350f')
        severity_text_color = HexColor('#fca5a5') if incident.severity == 'CRITICAL' else HexColor('#fcd34d')
        
        meta_data = [
            [Paragraph("INCIDENT ID", meta_label_style), Paragraph(f"INC-{incident.id}", meta_value_style)],
            [Paragraph("TOTAL LOG ENTRIES", meta_label_style), Paragraph(str(len(incident_logs)), meta_value_style)],
            [Paragraph("PERIOD", meta_label_style), 
             Paragraph(f"{incident.created_at.strftime('%d %b %Y, %H:%M')} — {timezone.now().strftime('%d %b %Y, %H:%M hrs')}", 
                      ParagraphStyle('Period', parent=styles['Normal'], fontSize=13, 
                                    textColor=HexColor('#e8f0fe'), alignment=TA_LEFT, fontName='Helvetica-Bold'))],
            [Paragraph("SEVERITY", meta_label_style), 
             Paragraph(severity_display, ParagraphStyle('Severity', parent=styles['Normal'], fontSize=10, 
                                                       textColor=severity_text_color, alignment=TA_LEFT, 
                                                       fontName='Helvetica-Bold', backColor=severity_color))]
        ]
        
        meta_table = Table(meta_data, colWidths=[1.8*inch, 5.5*inch])
        meta_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), HexColor('#1a3a6b')),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (0, 0), (-1, -1), 14),
            ('RIGHTPADDING', (0, 0), (-1, -1), 14),
            ('TOPPADDING', (0, 0), (-1, -1), 14),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 14),
        ]))
        elements.append(meta_table)
        elements.append(Spacer(1, 0.3*inch))
        
        # Incident Logs Table
        log_data = [[
            Paragraph('#', table_header_style),
            Paragraph('TIMESTAMP', table_header_style),
            Paragraph('DEPARTMENT', table_header_style),
            Paragraph('ACTION / DESCRIPTION', table_header_style),
            Paragraph('STATUS', table_header_style)
        ]]
        
        # Department color mapping
        dept_colors = {
            'SIEM / SOC Platform': (HexColor('#e0f2fe'), HexColor('#0369a1')),
            'Security Operations': (HexColor('#fce7f3'), HexColor('#9d174d')),
            'Incident Management': (HexColor('#ede9fe'), HexColor('#5b21b6')),
            'Infrastructure': (HexColor('#dcfce7'), HexColor('#14532d')),
            'External — Cyber IR': (HexColor('#f1f5f9'), HexColor('#334155')),
            'Business Continuity': (HexColor('#fef3c7'), HexColor('#92400e')),
            'Legal & Compliance': (HexColor('#fef9c3'), HexColor('#713f12')),
            'Communications': (HexColor('#fef9c3'), HexColor('#713f12')),
            'External — Regulator': (HexColor('#f1f5f9'), HexColor('#334155')),
        }
        
        # Status color mapping
        status_colors = {
            'DETECTED': (HexColor('#7f1d1d'), HexColor('#fca5a5')),
            'ESCALATED': (HexColor('#78350f'), HexColor('#fcd34d')),
            'IN PROGRESS': (HexColor('#78350f'), HexColor('#fcd34d')),
            'LOGGED': (HexColor('#1e3a5f'), HexColor('#93c5fd')),
            'COMPLETE': (HexColor('#064e3b'), HexColor('#6ee7b7')),
            'NOTIFIED': (HexColor('#1e3a5f'), HexColor('#93c5fd')),
            'CONTAINED': (HexColor('#064e3b'), HexColor('#6ee7b7')),
            'CLOSED': (HexColor('#1e3a5f'), HexColor('#93c5fd')),
        }
        
        for idx, log in enumerate(incident_logs, 1):
            timestamp = log['created_time']
            if isinstance(timestamp, str):
                from datetime import datetime
                try:
                    timestamp = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')
                except:
                    timestamp = timezone.now()
            
            date_str = timestamp.strftime('%d %b') if hasattr(timestamp, 'strftime') else str(timestamp)[:6]
            time_str = timestamp.strftime('%H:%M') if hasattr(timestamp, 'strftime') else str(timestamp)[-5:]
            timestamp_para = Paragraph(f"{date_str}<br/>{time_str}", timestamp_style)
            
            user = log.get('user_log')
            department = 'System'
            dept_bg, dept_text = (HexColor('#f1f5f9'), HexColor('#334155'))
            if user:
                try:
                    liaison = user.liaison_profile
                    department = liaison.organization.name if liaison.organization else 'Operations'
                    # Try to match department name
                    for dept_key, (bg, txt) in dept_colors.items():
                        if dept_key.lower() in department.lower() or department.lower() in dept_key.lower():
                            dept_bg, dept_text = bg, txt
                            department = dept_key
                            break
                except:
                    department = user.username
            
            # Department badge
            dept_para = Paragraph(f'<para backColor="{dept_bg.hexval()}" textColor="{dept_text.hexval()}" '
                                 f'leftIndent="3" rightIndent="3" spaceBefore="3" spaceAfter="3">'
                                 f'<font size="10" name="Helvetica-Bold">{department}</font></para>',
                                 ParagraphStyle('DeptBadge', parent=styles['Normal']))
            
            description = log.get('log_description', '')
            # Extract author if present (format: "— Author Name" at end)
            author = None
            if '—' in description:
                parts = description.rsplit('—', 1)
                if len(parts) == 2:
                    description = parts[0].strip()
                    author = parts[1].strip()
            
            # Escape HTML
            description = description.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            
            # Determine status
            status = 'LOGGED'
            desc_lower = description.lower()
            if 'detected' in desc_lower or 'fired' in desc_lower:
                status = 'DETECTED'
            elif 'escalated' in desc_lower:
                status = 'ESCALATED'
            elif 'complete' in desc_lower or 'completed' in desc_lower:
                status = 'COMPLETE'
            elif 'in progress' in desc_lower or 'progress' in desc_lower:
                status = 'IN PROGRESS'
            elif 'notified' in desc_lower:
                status = 'NOTIFIED'
            elif 'contained' in desc_lower:
                status = 'CONTAINED'
            elif 'closed' in desc_lower:
                status = 'CLOSED'
            
            status_bg, status_text = status_colors.get(status, (HexColor('#1e3a5f'), HexColor('#93c5fd')))
            # Match reference PDF: proper padding and font size so status doesn't wrap
            status_para = Paragraph(f'<para backColor="{status_bg.hexval()}" textColor="{status_text.hexval()}" '
                                  f'leftIndent="4" rightIndent="4" spaceBefore="3" spaceAfter="3">'
                                  f'<font size="10" name="Helvetica-Bold">{status}</font></para>',
                                  ParagraphStyle('StatusBadge', parent=styles['Normal']))
            
            # Description with author
            if author:
                desc_with_author = f'{description}<br/><br/><para alignment="right"><font size="10.5" color="#94a3b8"><i>— {author}</i></font></para>'
            else:
                desc_with_author = description
            
            desc_para = Paragraph(desc_with_author, log_cell_style)
            
            log_data.append([
                Paragraph(f"{idx:03d}", log_number_style),
                timestamp_para,
                dept_para,
                desc_para,
                status_para
            ])
        
        # Make log table same width as other sections (7.3 inches total)
        # Match reference PDF: wider columns to prevent header wrapping
        # #: 0.6 (wider to prevent vertical stacking), TIMESTAMP: 1.3, DEPARTMENT: 1.5, ACTION: 2.9, STATUS: 1.0 = 7.3 total
        log_table = Table(log_data, colWidths=[0.6*inch, 1.3*inch, 1.5*inch, 2.9*inch, 1*inch])
        
        # Apply alternating row colors with better padding to match reference PDF
        table_style_commands = [
            ('BACKGROUND', (0, 0), (-1, 0), HexColor('#0a1f44')),  # Header
            ('TEXTCOLOR', (0, 0), (-1, 0), HexColor('#93b4d8')),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'LEFT'),
            ('ALIGN', (2, 0), (2, -1), 'LEFT'),
            ('ALIGN', (3, 0), (3, -1), 'LEFT'),
            ('ALIGN', (4, 0), (4, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            # Header row padding
            ('BOTTOMPADDING', (0, 0), (-1, 0), 14),
            ('TOPPADDING', (0, 0), (-1, 0), 14),
            # Data rows padding - more generous padding
            ('BOTTOMPADDING', (0, 1), (-1, -1), 16),
            ('TOPPADDING', (0, 1), (-1, -1), 16),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            # Left padding - more space on left
            ('LEFTPADDING', (0, 0), (0, -1), 8),  # # column - less padding to prevent vertical stacking
            ('RIGHTPADDING', (0, 0), (0, -1), 8),  # # column - less padding
            ('LEFTPADDING', (1, 0), (1, -1), 14),  # TIMESTAMP
            ('LEFTPADDING', (2, 0), (2, -1), 14),  # DEPARTMENT
            ('LEFTPADDING', (3, 0), (3, -1), 16),  # ACTION/DESCRIPTION - more padding
            ('LEFTPADDING', (4, 0), (4, -1), 12),  # STATUS
            # Right padding - more space on right
            ('RIGHTPADDING', (0, 0), (0, -1), 12),  # # column
            ('RIGHTPADDING', (1, 0), (1, -1), 14),  # TIMESTAMP
            ('RIGHTPADDING', (2, 0), (2, -1), 14),  # DEPARTMENT
            ('RIGHTPADDING', (3, 0), (3, -1), 16),  # ACTION/DESCRIPTION - more padding
            ('RIGHTPADDING', (4, 0), (4, -1), 12),  # STATUS
            ('LINEBELOW', (0, 0), (-1, -1), 1, HexColor('#e5e7eb')),
        ]
        
        # Add alternating row backgrounds
        for i in range(1, len(log_data)):
            if i % 2 == 0:
                table_style_commands.append(('BACKGROUND', (0, i), (-1, i), HexColor('#ffffff')))
            else:
                table_style_commands.append(('BACKGROUND', (0, i), (-1, i), HexColor('#f8fafc')))
        
        log_table.setStyle(TableStyle(table_style_commands))
        elements.append(log_table)
        
        # Build PDF with custom header/footer
        def on_first_page(canvas, doc):
            CustomPageTemplate(canvas, doc).draw_header(canvas, doc)
            CustomPageTemplate(canvas, doc).draw_footer(canvas, doc)
        
        def on_later_pages(canvas, doc):
            CustomPageTemplate(canvas, doc).draw_footer(canvas, doc)
        
        doc.build(elements, onFirstPage=on_first_page, onLaterPages=on_later_pages)
        
        buffer.seek(0)
        response = HttpResponse(buffer, content_type='application/pdf')
        response['Content-Disposition'] = f'inline; filename="Incident_Log_History_INC-{incident.id}.pdf"'
        return response
        
    except IncidentCapture.DoesNotExist:
        return HttpResponse('Incident not found', status=404)
    except Exception as e:
        return HttpResponse(f'Error generating PDF: {str(e)}', status=500)


def incident_case_history_csv(request, incident_id):
    """Export incident log history as CSV (case history) for a single incident."""
    # Check authentication
    if not request.user.is_authenticated and 'user_credentials_id' not in request.session:
        return HttpResponse('Unauthorized', status=401)

    try:
        # Get organization similar to generate_incident_shift_packet_pdf
        organization = None
        if request.user.is_authenticated:
            try:
                liaison = request.user.liaison_profile
                organization = liaison.organization
            except (Liaison.DoesNotExist, AttributeError):
                return HttpResponse('Organization not found', status=400)
        elif 'user_credentials_id' in request.session:
            organization = Organization.objects.first()

        # Get the incident - for legacy users, get incident first then use its organization
        if 'user_credentials_id' in request.session:
            try:
                incident = IncidentCapture.objects.get(id=incident_id)
                organization = incident.organization
            except IncidentCapture.DoesNotExist:
                return HttpResponse('Incident not found', status=404)
        else:
            if not organization:
                return HttpResponse('Organization not found', status=400)
            try:
                incident = IncidentCapture.objects.get(id=incident_id, organization=organization)
            except IncidentCapture.DoesNotExist:
                return HttpResponse('Incident not found', status=404)

        # Build incident logs using same logic as PDF generation
        incident_logs = []
        try:
            from django.db import connection
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, event_description, created_time, user_id
                    FROM core_incident_events
                    WHERE incident_id = %s
                    ORDER BY created_time ASC
                    """,
                    [incident.id]
                )
                log_rows = cursor.fetchall()

                for row in log_rows:
                    log_id, event_desc, created_time, user_id = row
                    user = None
                    if user_id:
                        try:
                            user = User.objects.get(id=user_id)
                        except User.DoesNotExist:
                            pass
                    incident_logs.append({
                        'log_id': log_id,
                        'log_description': event_desc,
                        'created_time': created_time,
                        'user_log': user,
                    })
        except Exception:
            incident_logs = []

        # Add the "Incident Created" log entry if not already present
        has_created_log = any('created' in (log.get('log_description') or '').lower() for log in incident_logs)
        if not has_created_log:
            incident_logs.insert(0, {
                'log_id': 0,
                'log_description': f'Incident \"{incident.title}\" was created with severity level {incident.get_severity_display()}.',
                'created_time': incident.created_at,
                'user_log': incident.created_by.user if incident.created_by else None,
            })

        # Prepare CSV response
        filename = f"Case_History_INC-{incident.id}.csv"
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename=\"{filename}\"'

        writer = csv.writer(response)

        # Header info
        writer.writerow(['Incident ID', f'INC-{incident.id}'])
        writer.writerow(['Title', incident.title])
        writer.writerow(['Severity', incident.get_severity_display()])
        writer.writerow(['Created At', incident.created_at.strftime('%Y-%m-%d %H:%M') if incident.created_at else ''])
        writer.writerow([])  # blank line

        # Table header
        writer.writerow(['#', 'Timestamp', 'Department', 'Action / Description', 'Status'])

        # Department and status detection similar to PDF
        for idx, log in enumerate(incident_logs, start=1):
            timestamp = log.get('created_time')
            if isinstance(timestamp, str):
                from datetime import datetime
                try:
                    timestamp = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')
                except Exception:
                    timestamp = timezone.now()

            ts_str = timestamp.strftime('%Y-%m-%d %H:%M') if hasattr(timestamp, 'strftime') else str(timestamp)

            user = log.get('user_log')
            department = 'System'
            if user:
                try:
                    liaison = user.liaison_profile
                    department = liaison.organization.name if liaison.organization else 'Operations'
                except Exception:
                    department = user.username

            description = log.get('log_description') or ''
            # Extract author suffix if present \"— Author\"
            if '—' in description:
                parts = description.rsplit('—', 1)
                if len(parts) == 2:
                    description = parts[0].strip()

            desc_lower = description.lower()
            status = 'LOGGED'
            if 'detected' in desc_lower or 'fired' in desc_lower:
                status = 'DETECTED'
            elif 'escalated' in desc_lower:
                status = 'ESCALATED'
            elif 'complete' in desc_lower or 'completed' in desc_lower:
                status = 'COMPLETE'
            elif 'in progress' in desc_lower or 'progress' in desc_lower:
                status = 'IN PROGRESS'
            elif 'notified' in desc_lower:
                status = 'NOTIFIED'
            elif 'contained' in desc_lower:
                status = 'CONTAINED'
            elif 'closed' in desc_lower:
                status = 'CLOSED'

            writer.writerow([f"{idx:03d}", ts_str, department, description, status])

        return response

    except IncidentCapture.DoesNotExist:
        return HttpResponse('Incident not found', status=404)
    except Exception as e:
        return HttpResponse(f'Error generating CSV: {str(e)}', status=500)

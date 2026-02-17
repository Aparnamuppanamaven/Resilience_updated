"""
Payment utilities: invoice generation and email sending
"""
from django.db import transaction
from django.utils import timezone
from datetime import timedelta
import random
import string
from .models import Payment, Invoice, Organization


def generate_invoice_id():
    """Generate unique invoice ID: INV-YYYYMMDD-####"""
    from datetime import datetime
    timestamp = datetime.now().strftime('%Y%m%d')
    count = Payment.objects.filter(invoice_id__startswith=f'INV-{timestamp}').count()
    return f'INV-{timestamp}-{count + 1:04d}'


def ensure_unique_invoice_id():
    """Generate and ensure unique invoice ID"""
    max_attempts = 10
    for _ in range(max_attempts):
        invoice_id = generate_invoice_id()
        if not Invoice.objects.filter(invoice_id=invoice_id).exists():
            return invoice_id
    timestamp = timezone.now().strftime('%Y%m%d%H%M%S')
    random_suffix = ''.join(random.choices(string.digits, k=8))
    return f"INV-{timestamp}-{random_suffix}"


def calculate_due_date(payment_terms='NET_30'):
    """Calculate invoice due date based on payment terms"""
    if payment_terms == 'NET_30':
        return timezone.now().date() + timedelta(days=30)
    return timezone.now().date() + timedelta(days=30)


@transaction.atomic
def create_payment_and_invoice(form_data, organization, amount=7500.00):
    """
    Atomically create Payment and Invoice records.
    Returns (payment, invoice) tuple.
    """
    payment_method = form_data.get('payment_method', 'INVOICE')
    
    # Determine status based on payment method
    if payment_method == 'INVOICE':
        status = 'INVOICED'
    elif payment_method == 'ACH':
        status = 'PROCESSING'
    elif payment_method == 'CARD':
        status = 'PAID'  # Assuming immediate processing
    else:
        status = 'PENDING'
    
    # Generate invoice ID
    invoice_id = ensure_unique_invoice_id()
    
    # Create Payment
    payment = Payment.objects.create(
        amount=amount,
        payment_method=payment_method,
        status=status,
        invoice_id=invoice_id,
        organization=organization,
    )
    
    # For Card: store tokenized data (last 4 digits only, token from processor)
    if payment_method == 'CARD':
        card_number = form_data.get('card_number', '').replace(' ', '').replace('-', '')
        if len(card_number) >= 4:
            payment.card_last4 = card_number[-4:]
            # In production, get token from payment processor (Stripe, etc.)
            payment.card_token = f'token_{payment.id}_{timezone.now().timestamp()}'  # Placeholder
        payment.save()
    
    # Create Invoice (always created for records)
    due_date = timezone.now().date() + timedelta(days=30)  # Net 30
    
    invoice = Invoice.objects.create(
        invoice_id=invoice_id,
        payment=payment,
        billing_entity_name=form_data.get('billing_entity_name', organization.name),
        billing_email=form_data.get('billing_email'),
        po_number=form_data.get('po_number', ''),
        payment_terms='NET_30',
        early_pay_terms='2% / 10, Net 30',
        due_date=due_date,
    )
    
    return payment, invoice


def send_payment_confirmation_email(payment, invoice, organization):
    """Send payment confirmation email with invoice details"""
    from django.core.mail import send_mail
    from django.conf import settings
    
    billing_email = invoice.billing_email
    payment_method_display = {
        'INVOICE': 'Invoice - Net 30',
        'ACH': 'ACH (Bank Transfer)',
        'CARD': 'Credit Card',
    }.get(payment.payment_method, payment.payment_method)
    
    # Early pay terms only for Invoice
    early_pay_text = ''
    if payment.payment_method == 'INVOICE':
        early_pay_text = f"\nEarly Payment Terms: {invoice.early_pay_terms}\n"
    
    subject = f'Payment Confirmation - Invoice {invoice.invoice_id}'
    
    message = f"""Thank you for your payment.

Payment Details:
Amount: ${payment.amount:,.2f}
Date: {payment.created_at.strftime('%B %d, %Y')}
Invoice ID: {invoice.invoice_id}
Payment Method: {payment_method_display}
{early_pay_text}Due Date: {invoice.due_date.strftime('%B %d, %Y')}

What's Included:
- Resilience Foundation License
- Standard onboarding support
- 20-minute kickoff session
- Email/ticket support

Next Steps:
Your account setup will begin within 24-48 hours. You will receive an email with account access details and scheduling information for your kickoff session.

Support:
If you have questions, please contact support at support@resilience.example.com or reply to this email.

Thank you for choosing Resilience.
"""
    
    from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@resilience.example.com')
    
    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=from_email,
            recipient_list=[billing_email],
            fail_silently=False,
        )
    except Exception as e:
        # Log error but don't fail payment processing
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Failed to send payment confirmation email: {e}")

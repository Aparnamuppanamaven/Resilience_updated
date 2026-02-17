"""
Enterprise Payment Forms with Invoice/ACH/Card support
"""
from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
from datetime import datetime
import re
from .models import Payment, Invoice


def luhn_check(card_number):
    """Luhn algorithm validation for credit card numbers"""
    def digits_of(n):
        return [int(d) for d in str(n)]
    digits = digits_of(card_number.replace(' ', '').replace('-', ''))
    odd_digits = digits[-1::-2]
    even_digits = digits[-2::-2]
    checksum = sum(odd_digits)
    for d in even_digits:
        checksum += sum(digits_of(d * 2))
    return checksum % 10 == 0


class PaymentForm(forms.Form):
    """Enterprise payment form with Invoice/ACH/Card support. Default: INVOICE."""
    PAYMENT_METHOD_CHOICES = [
        ('INVOICE', 'Invoice - Net 30'),
        ('ACH', 'ACH (Bank Transfer)'),
        ('CARD', 'Credit Card'),
    ]
    
    payment_method = forms.ChoiceField(
        choices=PAYMENT_METHOD_CHOICES,
        initial='INVOICE',
        widget=forms.RadioSelect(attrs={'class': 'payment-method-radio'}),
        label='Payment Method'
    )
    
    # Common fields
    billing_email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'billing@organization.com'
        }),
        label='Billing Email'
    )
    
    # Invoice fields (required when payment_method = INVOICE)
    billing_entity_name = forms.CharField(
        required=False,
        max_length=255,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Organization Name'
        }),
        label='Billing Entity Name'
    )
    po_number = forms.CharField(
        required=False,
        max_length=100,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'PO-12345'
        }),
        label='Purchase Order Number',
        help_text='Required for invoice payment method.'
    )
    
    # ACH fields (required when payment_method = ACH)
    account_holder_name = forms.CharField(
        required=False,
        max_length=255,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Account Holder Name'
        }),
        label='Account Holder Name'
    )
    bank_name = forms.CharField(
        required=False,
        max_length=255,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Bank Name'
        }),
        label='Bank Name'
    )
    routing_number = forms.CharField(
        required=False,
        max_length=9,
        min_length=9,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': '123456789',
            'pattern': '[0-9]{9}'
        }),
        label='Routing Number',
        help_text='9-digit U.S. routing number.'
    )
    account_number = forms.CharField(
        required=False,
        min_length=4,
        max_length=17,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Account Number',
            'pattern': '[0-9]+'
        }),
        label='Account Number'
    )
    
    # Credit Card fields (required when payment_method = CARD)
    cardholder_name = forms.CharField(
        required=False,
        max_length=255,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Name on Card'
        }),
        label='Cardholder Name'
    )
    card_number = forms.CharField(
        required=False,
        max_length=19,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': '0000 0000 0000 0000',
            'pattern': '[0-9\s]+'
        }),
        label='Card Number'
    )
    expiry_date = forms.CharField(
        required=False,
        max_length=5,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'MM/YY',
            'pattern': '[0-9]{2}/[0-9]{2}'
        }),
        label='Expiry Date (MM/YY)'
    )
    cvv = forms.CharField(
        required=False,
        max_length=4,
        min_length=3,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': '123',
            'pattern': '[0-9]+'
        }),
        label='CVV'
    )
    billing_address = forms.CharField(
        required=False,
        max_length=500,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'Street Address, City, State, ZIP'
        }),
        label='Billing Address'
    )
    
    def clean_po_number(self):
        """PO Number required for Invoice method"""
        po_number = self.cleaned_data.get('po_number', '').strip()
        payment_method = self.data.get('payment_method', 'INVOICE')
        if payment_method == 'INVOICE' and not po_number:
            raise ValidationError('Purchase Order Number is required for invoice payment method.')
        return po_number
    
    def clean_billing_entity_name(self):
        """Billing entity name required for Invoice"""
        entity_name = self.cleaned_data.get('billing_entity_name', '').strip()
        payment_method = self.data.get('payment_method', 'INVOICE')
        if payment_method == 'INVOICE' and not entity_name:
            raise ValidationError('Billing Entity Name is required.')
        return entity_name
    
    def clean_routing_number(self):
        """Routing number validation for ACH"""
        routing = self.cleaned_data.get('routing_number', '').strip()
        payment_method = self.data.get('payment_method', 'INVOICE')
        if payment_method == 'ACH':
            if not routing:
                raise ValidationError('Routing number is required for ACH payment.')
            if not routing.isdigit() or len(routing) != 9:
                raise ValidationError('Routing number must be exactly 9 digits.')
        return routing
    
    def clean_account_number(self):
        """Account number validation for ACH"""
        account = self.cleaned_data.get('account_number', '').strip()
        payment_method = self.data.get('payment_method', 'INVOICE')
        if payment_method == 'ACH':
            if not account:
                raise ValidationError('Account number is required for ACH payment.')
            if not account.isdigit() or len(account) < 4:
                raise ValidationError('Account number must be numeric and at least 4 digits.')
        return account
    
    def clean_account_holder_name(self):
        """Account holder name required for ACH"""
        name = self.cleaned_data.get('account_holder_name', '').strip()
        payment_method = self.data.get('payment_method', 'INVOICE')
        if payment_method == 'ACH' and not name:
            raise ValidationError('Account holder name is required.')
        return name
    
    def clean_bank_name(self):
        """Bank name required for ACH"""
        bank = self.cleaned_data.get('bank_name', '').strip()
        payment_method = self.data.get('payment_method', 'INVOICE')
        if payment_method == 'ACH' and not bank:
            raise ValidationError('Bank name is required.')
        return bank
    
    def clean_card_number(self):
        """Card number validation with Luhn algorithm"""
        card = self.cleaned_data.get('card_number', '').strip().replace(' ', '').replace('-', '')
        payment_method = self.data.get('payment_method', 'INVOICE')
        if payment_method == 'CARD':
            if not card:
                raise ValidationError('Card number is required.')
            if not card.isdigit():
                raise ValidationError('Card number must contain only digits.')
            if len(card) < 13 or len(card) > 19:
                raise ValidationError('Card number must be between 13 and 19 digits.')
            if not luhn_check(card):
                raise ValidationError('Invalid card number. Please check and try again.')
        return card
    
    def clean_expiry_date(self):
        """Expiry date validation - must be future date"""
        expiry = self.cleaned_data.get('expiry_date', '').strip()
        payment_method = self.data.get('payment_method', 'INVOICE')
        if payment_method == 'CARD':
            if not expiry:
                raise ValidationError('Expiry date is required.')
            if not re.match(r'^\d{2}/\d{2}$', expiry):
                raise ValidationError('Expiry date must be in MM/YY format.')
            try:
                month, year = expiry.split('/')
                month_int = int(month)
                year_int = int(year)
                if month_int < 1 or month_int > 12:
                    raise ValidationError('Invalid month.')
                # Convert YY to YYYY
                current_year = timezone.now().year
                full_year = 2000 + year_int if year_int < 100 else year_int
                expiry_date = datetime(full_year, month_int, 1).date()
                # Check if expired (compare to first day of current month)
                current_month_start = datetime(current_year, timezone.now().month, 1).date()
                if expiry_date < current_month_start:
                    raise ValidationError('Card has expired.')
            except ValueError:
                raise ValidationError('Invalid expiry date format.')
        return expiry
    
    def clean_cvv(self):
        """CVV validation"""
        cvv = self.cleaned_data.get('cvv', '').strip()
        payment_method = self.data.get('payment_method', 'INVOICE')
        if payment_method == 'CARD':
            if not cvv:
                raise ValidationError('CVV is required.')
            if not cvv.isdigit():
                raise ValidationError('CVV must contain only digits.')
            if len(cvv) not in [3, 4]:
                raise ValidationError('CVV must be 3 or 4 digits.')
        return cvv
    
    def clean_cardholder_name(self):
        """Cardholder name required for Card"""
        name = self.cleaned_data.get('cardholder_name', '').strip()
        payment_method = self.data.get('payment_method', 'INVOICE')
        if payment_method == 'CARD' and not name:
            raise ValidationError('Cardholder name is required.')
        return name
    
    def clean_billing_address(self):
        """Billing address required for Card"""
        address = self.cleaned_data.get('billing_address', '').strip()
        payment_method = self.data.get('payment_method', 'INVOICE')
        if payment_method == 'CARD' and not address:
            raise ValidationError('Billing address is required.')
        return address
    
    def clean(self):
        """Final validation - ensure payment_method is set"""
        cleaned_data = super().clean()
        payment_method = cleaned_data.get('payment_method', 'INVOICE')
        
        # Ensure default is INVOICE if not set
        if not payment_method:
            cleaned_data['payment_method'] = 'INVOICE'
            payment_method = 'INVOICE'
        
        return cleaned_data

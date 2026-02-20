"""
Email utility using Microsoft Graph API
"""
import os
import requests
from msal import ConfidentialClientApplication
from django.conf import settings


def get_azure_credentials():
    """Get Azure credentials from Django settings"""
    tenant_id = getattr(settings, 'AZURE_TENANT_ID', None) or os.getenv("AZURE_TENANT_ID")
    client_id = getattr(settings, 'AZURE_CLIENT_ID', None) or os.getenv("AZURE_CLIENT_ID")
    client_secret = getattr(settings, 'AZURE_CLIENT_SECRET', None) or os.getenv("AZURE_CLIENT_SECRET")
    sender = getattr(settings, 'MAIL_SENDER', None) or os.getenv("MAIL_SENDER")
    
    if not all([tenant_id, client_id, client_secret, sender]):
        raise ValueError("Azure credentials not configured. Please set AZURE_TENANT_ID, AZURE_CLIENT_ID, AZURE_CLIENT_SECRET, and MAIL_SENDER in settings or environment variables.")
    
    return tenant_id, client_id, client_secret, sender


def send_email_via_graph_api(to_emails, subject, html_content, recipient_name=None):
    """
    Send email using Microsoft Graph API
    
    Args:
        to_email: Recipient email address
        subject: Email subject
        html_content: HTML content of the email
        recipient_name: Optional recipient name
    
    Returns:
        tuple: (success: bool, response_text: str)
    """
    try:
        tenant_id, client_id, client_secret, sender = get_azure_credentials()
        
        authority = f"https://login.microsoftonline.com/{tenant_id}"
        scope = ["https://graph.microsoft.com/.default"]
        
        # Get access token
        app = ConfidentialClientApplication(
            client_id,
            authority=authority,
            client_credential=client_secret
        )
        
        token = app.acquire_token_for_client(scopes=scope)
        
        if "access_token" not in token:
            error_msg = f"Token error: {token.get('error_description', token)}"
            return False, error_msg
        
        # Prepare headers
        headers = {
            "Authorization": f"Bearer {token['access_token']}",
            "Content-Type": "application/json"
        }
        
        # Prepare payload
        to_recipients = []
        for email in to_emails:
            to_recipients.append({
                "emailAddress": {
                    "address": email
                }
            })
        payload = {
            "message": {
            "subject": subject,
                "body": {
                    "contentType": "HTML",
                    "content": html_content
                    },
            "toRecipients": to_recipients
            }
        }
        
        # Send email
        url = f"https://graph.microsoft.com/v1.0/users/{sender}/sendMail"
        response = requests.post(url, headers=headers, json=payload)
        
        if response.status_code == 202:
            return True, "Email sent successfully"
        else:
            return False, f"Status {response.status_code}: {response.text}"
            
    except Exception as e:
        return False, str(e)


def send_checkout_confirmation_email(liaison_email, liaison_name, agency_name):
    """
    Send confirmation email when user clicks "Proceed to Payment" at checkout
    
    Args:
        liaison_email: Email address of the liaison
        liaison_name: Name of the primary liaison
        agency_name: Name of the agency/organization
    
    Returns:
        tuple: (success: bool, message: str)
    """
    subject = "Welcome to Resilience Foundation - Account Created"
    
    html_content = f"""
    <html>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
            <h2 style="color: #667eea;">Welcome to Resilience Foundation!</h2>
            
            <p>Dear {liaison_name},</p>
            
            <p>Thank you for signing up for Resilience Foundation! Your account has been successfully created.</p>
            
            <div style="background: #f8f9fa; padding: 15px; border-radius: 8px; margin: 20px 0;">
                <h3 style="margin-top: 0; color: #495057;">Account Details:</h3>
                <p><strong>Agency/Organization:</strong> {agency_name}</p>
                <p><strong>Primary Liaison:</strong> {liaison_name}</p>
                <p><strong>Email:</strong> {liaison_email}</p>
            </div>
            
            <p><strong>Next Steps:</strong></p>
            <ul>
                <li>Complete your payment to activate your subscription</li>
                <li>Set up your password and complete onboarding</li>
                <li>Start using the Resilience platform</li>
            </ul>
            
            <p>If you have any questions or need assistance, please don't hesitate to contact our support team.</p>
            
            <p style="margin-top: 30px;">
                Best regards,<br>
                <strong>The Resilience Team</strong>
            </p>
        </div>
    </body>
    </html>
    """
    
    return send_email_via_graph_api(
        to_email=liaison_email,
        subject=subject,
        html_content=html_content,
        recipient_name=liaison_name
    )


def send_new_user_notification_email(liaison_email, liaison_name, agency_name):
    """
    Send notification email to admin/SaaS person when new user clicks "Proceed to Payment" at checkout
    
    Args:
        liaison_email: Email address of the new user
        liaison_name: Name of the primary liaison
        agency_name: Name of the agency/organization
    
    Returns:
        tuple: (success: bool, message: str)
    """
    import os
    from django.conf import settings
    
    # Get admin email from settings or environment
    admin_emails_raw = getattr(settings, 'ADMIN_EMAIL', None) or os.getenv("ADMIN_EMAIL", "")
    admin_emails = [email.strip() for email in admin_emails_raw.split(",") if email.strip()]
    
    if not admin_emails:
        return False, "Admin email not configured. Please set ADMIN_EMAIL or NOTIFICATION_EMAIL in settings or environment variables."
    
    subject = "New User Signup - Resilience Foundation"
    
    html_content = f"""
    <html>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
            <h2 style="color: #667eea;">New User Signup Notification</h2>
            
            <p>A new user has signed up for Resilience Foundation and clicked "Proceed to Payment".</p>
            
            <div style="background: #f8f9fa; padding: 20px; border-radius: 8px; margin: 20px 0; border-left: 4px solid #667eea;">
                <h3 style="margin-top: 0; color: #495057;">New User Details:</h3>
                <table style="width: 100%; border-collapse: collapse;">
                    <tr>
                        <td style="padding: 8px 0; font-weight: 600; color: #495057; width: 150px;">Agency/Organization:</td>
                        <td style="padding: 8px 0; color: #212529;">{agency_name}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px 0; font-weight: 600; color: #495057;">Primary Liaison:</td>
                        <td style="padding: 8px 0; color: #212529;">{liaison_name}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px 0; font-weight: 600; color: #495057;">Email:</td>
                        <td style="padding: 8px 0; color: #212529;"><a href="mailto:{liaison_email}" style="color: #667eea; text-decoration: none;">{liaison_email}</a></td>
                    </tr>
                </table>
            </div>
            
            <div style="background: #e7f3ff; padding: 15px; border-radius: 8px; margin: 20px 0;">
                <p style="margin: 0; color: #0066cc;">
                    <strong>Action Required:</strong> The user has been redirected to the payment page. 
                    Monitor their payment status and account activation.
                </p>
            </div>
            
            <p style="margin-top: 30px; color: #6c757d; font-size: 0.9em;">
                This is an automated notification from the Resilience Foundation system.
            </p>
        </div>
    </body>
    </html>
    """
    
    return send_email_via_graph_api(
    to_emails=admin_emails,
    subject=subject,
    html_content=html_content,
    recipient_name="Admin"
    )

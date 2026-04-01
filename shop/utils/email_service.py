from flask import current_app, url_for
from flask_mail import Message
from itsdangerous import URLSafeTimedSerializer
from shop.extensions import mail

def generate_verification_token(email):
    
    serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    return serializer.dumps(email, salt='email-verify-salt')

def verify_token(token, expiration=600): # 600 seconds = 10 minutes
    serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    try:
        
        email = serializer.loads(token, salt='email-verify-salt', max_age=expiration)
        return email
    except Exception:
        return False


def send_verification_email(user_email):
    token = generate_verification_token(user_email)
    
    verify_url = url_for('auth.verify_email', token=token, _external=True)
    
    html_body = f"""
    <div style="font-family: Arial, sans-serif; padding: 20px;">
        <h2>Welcome to E-Commerce Pro! 🚀</h2>
        <p>Your account has been created. Please click on the link below to verify your email.</p>
        <p><strong>Note:</strong> This link is valid for only 10 minutes.</p>
        <a href="{verify_url}" style="background-color: #4CAF50; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">Verify My Email</a>
        <br><br>
        <p>If the button does not work, copy this link and paste it into your browser: 👇</p>
        <p>{verify_url}</p>
    </div>
    """
    
    msg = Message(
        subject="Verify your E-Commerce Pro Account",
        recipients=[user_email],
        html=html_body,
        sender=current_app.config['MAIL_DEFAULT_SENDER']
    )
    
    mail.send(msg)










# shop/utils/email_service.py ke aakhir mein ye add karo:

def send_category_request_email_to_admin(admin_emails, seller_name, category_name):
    """Admin ko notification bhejne ke liye function"""
    html_body = f"""
    <div style="font-family: Arial, sans-serif; padding: 20px;">
        <h2 style="color: #FF5722;">🚨 New Category Approval Request</h2>
        <p>Hello Admin,</p>
        <p>Seller <strong>{seller_name}</strong> has requested permission to sell products in the <strong>{category_name}</strong> category.</p>
        <p>Please log in to your Admin Dashboard to Review, Approve, or Reject this request.</p>
        <br>
        <p>Regards,<br>E-Commerce Pro System</p>
    </div>
    """
    
    msg = Message(
        subject=f"Action Required: Category Request from {seller_name}",
        recipients=admin_emails, # Ek se zyada admin ho toh sabko jayega
        html=html_body,
        sender=current_app.config['MAIL_DEFAULT_SENDER']
    )
    
    mail.send(msg)
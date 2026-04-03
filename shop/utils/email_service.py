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


def send_order_status_email(customer_email, customer_name, order_uuid, order_status, total_amount, items, latest_message=None):
    """Customer ko order status / payment confirmation mail bhejne ke liye helper."""
    try:
        status_messages = {
            'pending': 'Your order has been placed successfully and is waiting for the next update.',
            'processing': 'Your payment is complete and your order is now being prepared.',
            'shipped': 'Your package has been shipped and is on the way.',
            'delivered': 'Your order has been delivered successfully.',
            'cancelled': 'Your order has been cancelled.'
        }

        items_html = "".join([
            f"""
            <tr>
                <td style="padding: 10px 0; color: #0f172a;">{item.get('product_name', 'Product')}</td>
                <td style="padding: 10px 0; color: #475569; text-align: center;">{item.get('quantity', 0)}</td>
                <td style="padding: 10px 0; color: #0f172a; text-align: right;">Rs.{float(item.get('line_total', 0)):.2f}</td>
            </tr>
            """
            for item in items
        ])

        html_body = f"""
        <div style="font-family: Arial, sans-serif; background: #f8fafc; padding: 24px;">
            <div style="max-width: 560px; margin: 0 auto; background: #ffffff; border-radius: 18px; overflow: hidden; border: 1px solid #e2e8f0;">
                <div style="background: linear-gradient(135deg, #2563eb, #1d4ed8); color: white; padding: 24px;">
                    <div style="display: inline-flex; align-items: center; gap: 12px;">
                        <div style="width: 44px; height: 44px; border-radius: 14px; background: rgba(255,255,255,0.14); display: inline-flex; align-items: center; justify-content: center; font-weight: 700;">E</div>
                        <div>
                            <div style="font-size: 22px; font-weight: 700;">Pro Shop</div>
                            <div style="font-size: 12px; opacity: 0.85; letter-spacing: 0.08em; text-transform: uppercase;">Order Update</div>
                        </div>
                    </div>
                </div>
                <div style="padding: 24px;">
                    <p style="margin: 0 0 12px; color: #0f172a;">Hi {customer_name},</p>
                    <p style="margin: 0 0 18px; color: #334155; line-height: 1.6;">{status_messages.get(order_status, 'Your order has a fresh update.')}</p>
                    <div style="background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 14px; padding: 16px; margin-bottom: 18px;">
                        <p style="margin: 0 0 8px; color: #1d4ed8; font-weight: 700;">Order #{order_uuid[:8]}</p>
                        <p style="margin: 0; color: #334155;">Status: <strong>{order_status.upper()}</strong></p>
                        <p style="margin: 8px 0 0; color: #334155;">Total: <strong>Rs.{float(total_amount):.2f}</strong></p>
                    </div>
                    <table style="width: 100%; border-collapse: collapse; margin-bottom: 18px;">
                        <thead>
                            <tr>
                                <th style="padding-bottom: 10px; text-align: left; font-size: 12px; color: #64748b; text-transform: uppercase;">Product</th>
                                <th style="padding-bottom: 10px; text-align: center; font-size: 12px; color: #64748b; text-transform: uppercase;">Qty</th>
                                <th style="padding-bottom: 10px; text-align: right; font-size: 12px; color: #64748b; text-transform: uppercase;">Line Total</th>
                            </tr>
                        </thead>
                        <tbody>
                            {items_html}
                        </tbody>
                    </table>
                    <div style="background: #f8fafc; border-radius: 14px; padding: 16px; border: 1px solid #e2e8f0;">
                        <p style="margin: 0 0 8px; color: #0f172a; font-weight: 700;">Latest update</p>
                        <p style="margin: 0; color: #475569; line-height: 1.6;">{latest_message or status_messages.get(order_status, 'Track your order live from your profile dashboard.')}</p>
                    </div>
                    <p style="margin: 18px 0 0; color: #64748b; font-size: 13px;">You can open Pro Shop anytime to track this order in real time.</p>
                </div>
            </div>
        </div>
        """

        msg = Message(
            subject=f"Pro Shop Order Update - #{order_uuid[:8]}",
            recipients=[customer_email],
            html=html_body,
            sender=current_app.config['MAIL_DEFAULT_SENDER']
        )

        mail.send(msg)
        return True
    except Exception as exc:
        print(f"Order email failed: {exc}")
        return False


def send_payment_otp_email(customer_email, customer_name, order_uuid, otp_code, payment_method, expires_in_minutes=10):
    """Send a payment verification OTP email for online transactions."""
    try:
        payment_label = str(payment_method or 'online').replace('_', ' ').upper()
        html_body = f"""
        <div style="font-family: Arial, sans-serif; background: #f8fafc; padding: 24px;">
            <div style="max-width: 560px; margin: 0 auto; background: #ffffff; border-radius: 18px; overflow: hidden; border: 1px solid #e2e8f0;">
                <div style="background: linear-gradient(135deg, #0f172a, #1d4ed8); color: white; padding: 24px;">
                    <div style="display: inline-flex; align-items: center; gap: 12px;">
                        <div style="width: 44px; height: 44px; border-radius: 14px; background: rgba(255,255,255,0.14); display: inline-flex; align-items: center; justify-content: center; font-weight: 700;">P</div>
                        <div>
                            <div style="font-size: 22px; font-weight: 700;">Pro Shop</div>
                            <div style="font-size: 12px; opacity: 0.85; letter-spacing: 0.08em; text-transform: uppercase;">Payment Verification</div>
                        </div>
                    </div>
                </div>
                <div style="padding: 24px;">
                    <p style="margin: 0 0 12px; color: #0f172a;">Hi {customer_name},</p>
                    <p style="margin: 0 0 18px; color: #334155; line-height: 1.6;">
                        We received a {payment_label} payment request for order <strong>#{order_uuid[:8]}</strong>.
                        Use the OTP below to verify and complete your payment.
                    </p>
                    <div style="margin-bottom: 18px; border-radius: 18px; border: 1px solid #bfdbfe; background: #eff6ff; padding: 18px; text-align: center;">
                        <p style="margin: 0 0 8px; color: #1d4ed8; font-size: 12px; letter-spacing: 0.12em; text-transform: uppercase;">Your OTP Code</p>
                        <p style="margin: 0; color: #0f172a; font-size: 34px; font-weight: 800; letter-spacing: 0.28em;">{otp_code}</p>
                    </div>
                    <div style="background: #fff7ed; border: 1px solid #fdba74; border-radius: 14px; padding: 16px;">
                        <p style="margin: 0; color: #9a3412; line-height: 1.6;">
                            This code expires in <strong>{int(expires_in_minutes)}</strong> minutes. Do not share it with anyone.
                            If you did not start this payment, please ignore this email and review your account activity.
                        </p>
                    </div>
                </div>
            </div>
        </div>
        """

        msg = Message(
            subject=f"Pro Shop Payment OTP - Order #{order_uuid[:8]}",
            recipients=[customer_email],
            html=html_body,
            sender=current_app.config['MAIL_DEFAULT_SENDER']
        )

        mail.send(msg)
        return True
    except Exception as exc:
        print(f"Payment OTP email failed: {exc}")
        return False

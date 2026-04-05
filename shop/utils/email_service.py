import base64
from functools import lru_cache
from pathlib import Path

from flask import current_app, url_for
from flask_mail import Message
from itsdangerous import URLSafeTimedSerializer

from shop.extensions import mail

EMAIL_FONT = "'Segoe UI', Arial, sans-serif"
REPO_ROOT = Path(__file__).resolve().parents[2]
LOGO_PATH = REPO_ROOT / 'frontend' / 'static' / 'img' / 'logo.svg'


def generate_verification_token(email):
    serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    return serializer.dumps(email, salt='email-verify-salt')


def verify_token(token, expiration=600):
    serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    try:
        return serializer.loads(token, salt='email-verify-salt', max_age=expiration)
    except Exception:
        return False


@lru_cache(maxsize=1)
def _get_logo_data_uri():
    try:
        encoded = base64.b64encode(LOGO_PATH.read_bytes()).decode('ascii')
        return f'data:image/svg+xml;base64,{encoded}'
    except OSError as exc:
        current_app.logger.warning('Email logo could not be loaded: %s', exc)
        return ''


def _build_logo_markup():
    logo_uri = _get_logo_data_uri()
    if logo_uri:
        return (
            f'<img src="{logo_uri}" width="112" alt="Pro Shop" '
            'style="display:block; margin:0 auto 14px; border:0; outline:none; text-decoration:none;">'
        )

    return (
        '<div style="margin:0 auto 14px; width:72px; height:72px; border-radius:22px; '
        'background:linear-gradient(135deg,#4F46E5,#1F2937); color:#ffffff; '
        f'font-family:{EMAIL_FONT}; font-size:28px; font-weight:800; line-height:72px; text-align:center;">P</div>'
    )


def _email_shell(*, eyebrow, title, content_html, footer_text='Pro Shop'):
    return f"""
    <div style="margin:0; padding:32px 16px; background:#F3F4F6; font-family:{EMAIL_FONT};">
        <div style="max-width:560px; margin:0 auto; background:#FFFFFF; border:1px solid #E5E7EB; border-radius:24px; overflow:hidden;">
            <div style="padding:32px 32px 28px; text-align:center; background:linear-gradient(180deg,#FFFFFF 0%,#F9FAFB 100%);">
                {_build_logo_markup()}
                <p style="margin:0 0 10px; font-size:12px; letter-spacing:0.14em; text-transform:uppercase; color:#6B7280;">{eyebrow}</p>
                <h1 style="margin:0; font-size:28px; line-height:1.2; color:#111827;">{title}</h1>
            </div>
            <div style="padding:0 32px 32px; color:#374151; font-size:15px; line-height:1.7;">
                {content_html}
            </div>
            <div style="padding:18px 32px 28px; border-top:1px solid #E5E7EB; text-align:center; color:#6B7280; font-size:13px;">
                {footer_text}
            </div>
        </div>
    </div>
    """


def _send_html_email(subject, recipients, html_body):
    msg = Message(
        subject=subject,
        recipients=recipients,
        html=html_body,
        sender=current_app.config['MAIL_DEFAULT_SENDER'],
    )
    mail.send(msg)


def send_verification_email(user_email):
    token = generate_verification_token(user_email)
    verify_url = url_for('auth.verify_email', token=token, _external=True)

    body = f"""
    <p style="margin:0 0 16px;">Your account is ready. Verify your email to activate secure login access.</p>
    <div style="margin:0 0 20px; padding:18px; border:1px solid #E5E7EB; border-radius:18px; background:#F9FAFB;">
        <p style="margin:0 0 14px; color:#111827; font-weight:600;">This verification link stays active for 10 minutes.</p>
        <a href="{verify_url}" style="display:inline-block; padding:12px 20px; border-radius:12px; background:#4F46E5; color:#FFFFFF; text-decoration:none; font-weight:700;">Verify My Email</a>
    </div>
    <p style="margin:0 0 8px; color:#6B7280;">If the button does not open, copy this link into your browser:</p>
    <p style="margin:0; word-break:break-all; color:#4F46E5;">{verify_url}</p>
    """

    html_body = _email_shell(
        eyebrow='Account Verification',
        title='Verify Your Email',
        content_html=body,
    )
    _send_html_email('Verify your E-Commerce Pro Account', [user_email], html_body)


def send_category_request_email_to_admin(admin_emails, seller_name, category_name):
    body = f"""
    <p style="margin:0 0 16px;">A seller has requested approval for a protected selling category.</p>
    <div style="margin:0 0 18px; padding:18px; border:1px solid #E5E7EB; border-radius:18px; background:#F9FAFB; text-align:left;">
        <p style="margin:0 0 8px;"><strong>Seller:</strong> {seller_name}</p>
        <p style="margin:0;"><strong>Category:</strong> {category_name}</p>
    </div>
    <p style="margin:0;">Open the admin dashboard on localhost to review and approve or decline the request.</p>
    """

    html_body = _email_shell(
        eyebrow='Admin Action Required',
        title='New Category Approval Request',
        content_html=body,
    )
    _send_html_email(
        f'Action Required: Category Request from {seller_name}',
        admin_emails,
        html_body,
    )


def send_order_status_email(customer_email, customer_name, order_uuid, order_status, total_amount, items, latest_message=None):
    try:
        status_messages = {
            'pending': 'Your order has been placed successfully and is waiting for the next update.',
            'processing': 'Your payment is complete and your order is now being prepared.',
            'shipped': 'Your package has been shipped and is on the way.',
            'delivered': 'Your order has been delivered successfully.',
            'cancelled': 'Your order has been cancelled.',
        }

        items_html = ''.join([
            f"""
            <tr>
                <td style="padding:12px 0; color:#111827;">{item.get('product_name', 'Product')}</td>
                <td style="padding:12px 0; color:#6B7280; text-align:center;">{item.get('quantity', 0)}</td>
                <td style="padding:12px 0; color:#111827; text-align:right;">Rs.{float(item.get('line_total', 0)):.2f}</td>
            </tr>
            """
            for item in items
        ])

        body = f"""
        <p style="margin:0 0 14px;">Hi {customer_name},</p>
        <p style="margin:0 0 18px;">{status_messages.get(order_status, 'Your order has a fresh update.')}</p>
        <div style="margin:0 0 20px; padding:18px; border:1px solid #E5E7EB; border-radius:18px; background:#F9FAFB;">
            <p style="margin:0 0 8px; color:#4F46E5; font-weight:700;">Order #{order_uuid[:8]}</p>
            <p style="margin:0 0 6px;"><strong>Status:</strong> {order_status.upper()}</p>
            <p style="margin:0;"><strong>Total:</strong> Rs.{float(total_amount):.2f}</p>
        </div>
        <table style="width:100%; border-collapse:collapse; margin:0 0 18px;">
            <thead>
                <tr>
                    <th style="padding-bottom:10px; text-align:left; font-size:12px; letter-spacing:0.08em; text-transform:uppercase; color:#6B7280;">Product</th>
                    <th style="padding-bottom:10px; text-align:center; font-size:12px; letter-spacing:0.08em; text-transform:uppercase; color:#6B7280;">Qty</th>
                    <th style="padding-bottom:10px; text-align:right; font-size:12px; letter-spacing:0.08em; text-transform:uppercase; color:#6B7280;">Line Total</th>
                </tr>
            </thead>
            <tbody>{items_html}</tbody>
        </table>
        <div style="padding:16px 18px; border:1px solid #E5E7EB; border-radius:18px; background:#F9FAFB;">
            <p style="margin:0 0 8px; color:#111827; font-weight:700;">Latest update</p>
            <p style="margin:0;">{latest_message or status_messages.get(order_status, 'Track your order live from your profile dashboard.')}</p>
        </div>
        """

        html_body = _email_shell(
            eyebrow='Order Update',
            title='Your Order Status Changed',
            content_html=body,
        )
        _send_html_email(
            f'Pro Shop Order Update - #{order_uuid[:8]}',
            [customer_email],
            html_body,
        )
        return True
    except Exception as exc:
        current_app.logger.exception('Order email failed: %s', exc)
        return False


def send_payment_otp_email(customer_email, customer_name, order_uuid, otp_code, payment_method, expires_in_minutes=10):
    try:
        payment_label = str(payment_method or 'online').replace('_', ' ').upper()
        body = f"""
        <p style="margin:0 0 14px;">Hi {customer_name},</p>
        <p style="margin:0 0 20px;">We received a {payment_label} payment request for order <strong>#{order_uuid[:8]}</strong>. Enter this one-time password to verify and complete your order.</p>
        <div style="margin:0 0 18px; padding:22px 20px; border:1px solid #C7D2FE; border-radius:20px; background:#EEF2FF; text-align:center;">
            <p style="margin:0 0 10px; font-size:12px; letter-spacing:0.14em; text-transform:uppercase; color:#6366F1;">Your OTP Code</p>
            <p style="margin:0; font-size:38px; line-height:1; letter-spacing:0.32em; font-weight:800; color:#111827;">{otp_code}</p>
        </div>
        <div style="padding:16px 18px; border:1px solid #E5E7EB; border-radius:18px; background:#F9FAFB; text-align:center;">
            <p style="margin:0; color:#374151;">This OTP expires in <strong>{int(expires_in_minutes)}</strong> minutes. Never share it with anyone. If you did not start this order, you can safely ignore this email.</p>
        </div>
        """

        html_body = _email_shell(
            eyebrow='Order Payment Verification',
            title='Verify Your Order',
            content_html=body,
            footer_text='Pro Shop secure checkout',
        )
        _send_html_email(
            f'Pro Shop Payment OTP - Order #{order_uuid[:8]}',
            [customer_email],
            html_body,
        )
        return True
    except Exception as exc:
        current_app.logger.exception('Payment OTP email failed: %s', exc)
        return False



#+++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
#+++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++


def send_profile_otp_email(customer_email, customer_name, otp_code, expires_in_minutes=10):
    """Reuses the exact email shell to send a profile update OTP"""
    try:
        body = f"""
        <p style="margin:0 0 14px;">Hi {customer_name},</p>
        <p style="margin:0 0 20px;">We received a request to update your profile information. Enter this one-time password to verify and apply your changes.</p>
        <div style="margin:0 0 18px; padding:22px 20px; border:1px solid #C7D2FE; border-radius:20px; background:#EEF2FF; text-align:center;">
            <p style="margin:0 0 10px; font-size:12px; letter-spacing:0.14em; text-transform:uppercase; color:#6366F1;">Your Verification Code</p>
            <p style="margin:0; font-size:38px; line-height:1; letter-spacing:0.32em; font-weight:800; color:#111827;">{otp_code}</p>
        </div>
        <div style="padding:16px 18px; border:1px solid #E5E7EB; border-radius:18px; background:#F9FAFB; text-align:center;">
            <p style="margin:0; color:#374151;">This OTP expires in <strong>{int(expires_in_minutes)}</strong> minutes. If you did not request this change, please change your password immediately.</p>
        </div>
        """

        html_body = _email_shell(
            eyebrow='Security Verification',
            title='Verify Profile Update',
            content_html=body,
            footer_text='Pro Shop Secure Account Management',
        )
        _send_html_email(
            'Pro Shop - Verify Your Profile Update',
            [customer_email],
            html_body,
        )
        return True
    except Exception as exc:
        current_app.logger.exception('Profile OTP email failed: %s', exc)
        return False
# Order Management & Notifications Service
from flask_mail import Mail, Message
from flask import current_app
import os
from dotenv import load_dotenv

load_dotenv()

mail = Mail()

def send_order_email(customer_email, customer_name, order_uuid, order_status, total_amount, items):
    """Send order notification email to customer"""
    try:
        status_messages = {
            'pending': 'Order Placed Successfully! Your order is pending confirmation.',
            'processing': 'Your order is now being processed.',
            'shipped': 'Your order has been shipped! Track it on our website.',
            'delivered': 'Your order has been delivered. Thank you for shopping!',
            'cancelled': 'Your order has been cancelled.'
        }
        
        items_html = "".join([f"<li>{item['product_name']} x {item['quantity']} - ₹{item['price_at_purchase']}</li>" for item in items])
        
        html_body = f"""
        <html>
            <body style="font-family: Arial, sans-serif; background-color: #f5f5f5; padding: 20px;">
                <div style="background-color: white; padding: 20px; border-radius: 8px; max-width: 500px; margin: 0 auto;">
                    <h2 style="color: #2563eb;">Order Notification</h2>
                    <p>Hi {customer_name},</p>
                    <p style="font-size: 16px; color: #333;">{status_messages.get(order_status, 'Your order status has been updated.')}</p>
                    
                    <div style="background-color: #f9fafb; padding: 15px; border-radius: 5px; margin: 15px 0;">
                        <p><strong>Order ID:</strong> {order_uuid[:8]}...</p>
                        <p><strong>Status:</strong> <span style="color: #2563eb; font-weight: bold;">{order_status.upper()}</span></p>
                        <p><strong>Total Amount:</strong> ₹{total_amount}</p>
                    </div>
                    
                    <h3 style="color: #333;">Items:</h3>
                    <ul style="list-style: none; padding: 0;">
                        {items_html}
                    </ul>
                    
                    <div style="background-color: #dbeafe; padding: 10px; border-left: 4px solid #2563eb; margin-top: 20px;">
                        <p style="color: #1e40af;">Visit your profile to track your order in real-time.</p>
                    </div>
                    
                    <p style="margin-top: 20px; color: #666; font-size: 12px;">
                        Best regards,<br/>
                        <strong>Pro Shop Team</strong>
                    </p>
                </div>
            </body>
        </html>
        """
        
        msg = Message(
            subject=f'Order {order_status.upper()} - Order #{order_uuid[:8]}',
            recipients=[customer_email],
            html=html_body
        )
        
        mail.send(msg)
        return True
    except Exception as e:
        print(f"Failed to send email: {str(e)}")
        return False

def send_welcome_email(email, username):
    """Send welcome email to new user"""
    try:
        html_body = f"""
        <html>
            <body style="font-family: Arial, sans-serif; background-color: #f5f5f5; padding: 20px;">
                <div style="background-color: white; padding: 20px; border-radius: 8px; max-width: 500px; margin: 0 auto;">
                    <h2 style="color: #2563eb;">Welcome to Pro Shop! 🎉</h2>
                    <p>Hi {username},</p>
                    <p>Thank you for registering with us. We're excited to have you on board!</p>
                    <p style="margin-top: 20px;">You can now:</p>
                    <ul>
                        <li>Browse our amazing products</li>
                        <li>Add items to your cart</li>
                        <li>Place orders</li>
                        <li>Track your orders in real-time</li>
                    </ul>
                    <p style="margin-top: 20px; color: #666;">
                        Best regards,<br/>
                        <strong>Pro Shop Team</strong>
                    </p>
                </div>
            </body>
        </html>
        """
        
        msg = Message(
            subject='Welcome to Pro Shop!',
            recipients=[email],
            html=html_body
        )
        
        mail.send(msg)
        return True
    except Exception as e:
        print(f"Failed to send welcome email: {str(e)}")
        return False

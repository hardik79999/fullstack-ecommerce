from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity
import random
import string
from datetime import datetime, timedelta

from shop.extensions import db
from shop.models import (
    User, Product, ProductImage, Category, Specification,
    CartItem, Address, Order, OrderItem, Payment, Invoice,
    OrderTracking, OrderStatus, PaymentStatus, PaymentMethod,
    Otp, OTPAction
)
from shop.utils.email_service import send_order_status_email, send_payment_otp_email

user_bp = Blueprint('user', __name__)
PAYMENT_OTP_EXPIRY_MINUTES = 10
VIRTUAL_PAYMENT_METHODS = {
    PaymentMethod.card,
    PaymentMethod.upi,
    PaymentMethod.netbanking,
}

@user_bp.route('/profile', methods=['GET'])
@jwt_required()
def get_profile():

    uuid = get_jwt_identity()

    
    user = User.query.filter_by(uuid=uuid).first()

    if not user:
        return jsonify({"error": "User not found"}), 404

    addresses = []
    if user.role.role_name == 'customer':
        addresses = [{
            "uuid": addr.uuid,
            "full_name": addr.full_name,
            "phone_number": addr.phone_number,
            "street": addr.street,
            "city": addr.city,
            "state": addr.state,
            "pincode": addr.pincode,
            "is_default": addr.is_default
        } for addr in user.addresses if addr.is_active]

    return jsonify({
        "message": "Welcome to your protected profile!",
        "user": {
            "uuid": user.uuid,
            "username": user.username,
            "email": user.email,
            "phone": user.phone,
            "role": user.role.role_name,
            "is_active": user.is_active,
            "is_verified": user.is_verified,
            "created_at": user.created_at.strftime("%Y-%m-%d %H:%M:%S") if user.created_at else None,
            "addresses": addresses
        }
    }), 200




@user_bp.route('/products', methods=['GET'])
def get_public_products():
    # MAGIC QUERY: Humne join pehle hi lagaya hua hai seller status check karne ke liye
    products = Product.query.join(User, Product.seller_id == User.id)\
        .filter(Product.is_active == True, User.is_active == True).all()
    
    result = []
    for prod in products:
        # Har product ke specs nikal lo
        specs = [{"key": s.spec_key, "value": s.spec_value} for s in prod.specifications if s.is_active]
        
        primary_image = ProductImage.query.filter_by(product_id=prod.id, is_primary=True).first()
        
        result.append({
            "uuid": prod.uuid,
            "name": prod.name,
            "price": prod.price,
            "stock": prod.stock,
            "category": prod.category.name,
            "seller": prod.seller_user.username, 
            "primary_image": primary_image.image_url if primary_image else None,
            "specifications": specs # 👈 List view me bhi specs add kar diye
        })
        
    return jsonify({
        "total_products": len(result),
        "products": result
    }), 200





#================================================================================================================
#================================================================================================================

from flask import request
from shop.models import CartItem


# ✅ NEW ENDPOINT: Get Single Product Details with ALL Images
@user_bp.route('/product/<product_uuid>', methods=['GET'])
def get_product_detail(product_uuid):
    """
    Fetch single product with:
    - All images (primary_image + images array)
    - All specifications
    - Seller info
    """
    product = Product.query.join(User, Product.seller_id == User.id)\
        .filter(Product.uuid == product_uuid, Product.is_active == True, User.is_active == True).first()
    
    if not product:
        return jsonify({"error": "Product not found or inactive"}), 404
    
    # Get all product images from ProductImage table
    all_images = ProductImage.query.filter_by(product_id=product.id, is_active=True).all()
    primary_image = ProductImage.query.filter_by(product_id=product.id, is_primary=True, is_active=True).first()
    
    # Build images list
    images_list = [img.image_url for img in all_images]
    
    # Get all specs
    specs = [{"key": s.spec_key, "value": s.spec_value} for s in product.specifications if s.is_active]
    
    return jsonify({
        "product": {
            "uuid": product.uuid,
            "name": product.name,
            "description": product.description,
            "price": product.price,
            "stock": product.stock,
            "category": product.category.name,
            "seller": product.seller_user.username,
            "primary_image": primary_image.image_url if primary_image else None,
            "images": images_list,
            "specifications": specs
        }
    }), 200


#================================================================================================================
#================================================================================================================

# Helper decorator to ensure the user is a 'customer'
def customer_required(fn):
    @jwt_required()
    def wrapper(*args, **kwargs):
        current_user_uuid = get_jwt_identity()
        user = User.query.filter_by(uuid=current_user_uuid, is_active=True).first()
        
        if not user or user.role.role_name != 'customer':
            return jsonify({"error": "Unauthorized access. Customer privileges required."}), 403
            
        return fn(current_customer=user, *args, **kwargs)
    
    wrapper.__name__ = fn.__name__
    return wrapper

#================================================================================================================
# PAYMENT HELPERS
#================================================================================================================

def _serialize_order_items(order):
    return [{
        "product_name": item.product.name if getattr(item, 'product', None) else f"Product #{item.product_id}",
        "quantity": item.quantity,
        "line_total": float(item.price_at_purchase) * item.quantity
    } for item in order.items]


def _invalidate_unused_payment_otps(customer_id, actor_id):
    Otp.query.filter_by(
        user_id=customer_id,
        action=OTPAction.verification,
        is_used=False,
        is_active=True
    ).update({
        "is_used": True,
        "updated_by": actor_id,
    }, synchronize_session=False)


def _generate_payment_otp(current_customer):
    otp_code = f"{random.randint(0, 999999):06d}"
    otp_entry = Otp(
        user_id=current_customer.id,
        otp_code=otp_code,
        action=OTPAction.verification,
        is_used=False,
        expires_at=datetime.utcnow() + timedelta(minutes=PAYMENT_OTP_EXPIRY_MINUTES),
        created_by=current_customer.id,
        updated_by=current_customer.id,
        is_active=True,
    )
    db.session.add(otp_entry)
    return otp_entry, otp_code


def _build_payment_tracking_message(payment_method_enum):
    return f"Payment via {payment_method_enum.name.upper()} successful. Your order is now being processed."


def _generate_transaction_id():
    return "TXN-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=10))


def _find_conflicting_pending_payment(current_customer, current_order_id):
    return Order.query.join(Payment, Payment.order_id == Order.id).filter(
        Order.user_id == current_customer.id,
        Order.id != current_order_id,
        Order.is_active == True,
        Order.status == OrderStatus.pending,
        Payment.user_id == current_customer.id,
        Payment.is_active == True,
        Payment.status == PaymentStatus.pending
    ).order_by(Order.created_at.desc()).first()


def _finalize_order_payment(order, current_customer, payment_method_enum, payment_record=None):
    transaction_id = None if payment_method_enum == PaymentMethod.cod else _generate_transaction_id()

    if payment_record:
        payment_record.payment_method = payment_method_enum
        payment_record.amount = order.total_amount
        payment_record.status = PaymentStatus.completed
        payment_record.transaction_id = transaction_id
        payment_record.updated_by = current_customer.id
        payment_record.is_active = True
    else:
        payment_record = Payment(
            order_id=order.id,
            user_id=current_customer.id,
            transaction_id=transaction_id,
            payment_method=payment_method_enum,
            amount=order.total_amount,
            status=PaymentStatus.completed,
            created_by=current_customer.id,
            updated_by=current_customer.id,
            is_active=True
        )
        db.session.add(payment_record)

    order.status = OrderStatus.processing
    order.updated_by = current_customer.id

    tracking_entry = OrderTracking(
        order_id=order.id,
        status=OrderStatus.processing,
        message=_build_payment_tracking_message(payment_method_enum),
        created_by=current_customer.id,
        updated_by=current_customer.id,
        is_active=True
    )
    db.session.add(tracking_entry)

    invoice_record = order.invoice
    if not invoice_record:
        invoice_record = Invoice(
            order_id=order.id,
            invoice_number=f"INV-{order.id}-{random.randint(1000, 9999)}",
            created_by=current_customer.id,
            updated_by=current_customer.id,
            is_active=True
        )
        db.session.add(invoice_record)

    _invalidate_unused_payment_otps(current_customer.id, current_customer.id)

    return {
        "payment": payment_record,
        "invoice": invoice_record,
        "transaction_id": transaction_id or "N/A",
        "tracking_message": _build_payment_tracking_message(payment_method_enum),
    }


def _checkout_customer_order(current_customer):
    data = request.get_json() or {}
    address_uuid = str(data.get('address_uuid') or '').strip()

    if not address_uuid:
        return jsonify({"error": "address_uuid is required"}), 400

    address = Address.query.filter_by(
        uuid=address_uuid,
        user_id=current_customer.id,
        is_active=True
    ).first()
    if not address:
        return jsonify({"error": "Invalid delivery address"}), 404

    try:
        cart_items = CartItem.query.filter_by(
            user_id=current_customer.id,
            is_active=True
        ).with_for_update().all()

        if not cart_items:
            return jsonify({"error": "Cart is empty"}), 400

        total_amount = 0.0
        locked_products = {}
        order_items_to_create = []

        for item in cart_items:
            if item.quantity < 1:
                return jsonify({"error": "Cart contains an invalid quantity"}), 400

            product = Product.query.filter_by(
                id=item.product_id,
                is_active=True
            ).with_for_update().first()

            if not product:
                return jsonify({"error": "One of the cart products is unavailable"}), 404

            if product.stock < item.quantity:
                return jsonify({
                    "error": "Insufficient stock",
                    "message": f"Only {product.stock} unit(s) of {product.name} are available right now."
                }), 409

            locked_products[product.id] = product
            total_amount += float(product.price) * item.quantity
            order_items_to_create.append({
                "product_id": product.id,
                "quantity": item.quantity,
                "price_at_purchase": float(product.price)
            })

        new_order = Order(
            user_id=current_customer.id,
            address_id=address.id,
            total_amount=total_amount,
            status=OrderStatus.pending,
            created_by=current_customer.id,
            updated_by=current_customer.id
        )
        db.session.add(new_order)
        db.session.flush()

        for item_payload in order_items_to_create:
            db.session.add(OrderItem(
                order_id=new_order.id,
                product_id=item_payload["product_id"],
                quantity=item_payload["quantity"],
                price_at_purchase=item_payload["price_at_purchase"],
                created_by=current_customer.id,
                updated_by=current_customer.id
            ))
            locked_products[item_payload["product_id"]].stock -= item_payload["quantity"]

        db.session.add(OrderTracking(
            order_id=new_order.id,
            status=OrderStatus.pending,
            message="Order created successfully and awaiting payment confirmation.",
            created_by=current_customer.id,
            updated_by=current_customer.id,
            is_active=True
        ))

        for item in cart_items:
            item.is_active = False
            item.updated_by = current_customer.id

        db.session.commit()

        return jsonify({
            "message": "Order placed successfully!",
            "order_uuid": new_order.uuid,
            "total_payable": total_amount
        }), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Transaction failed", "details": str(e)}), 500


def _process_payment_flow(current_customer):
    data = request.get_json() or {}
    order_uuid = str(data.get('order_uuid') or '').strip()
    payment_method_str = str(data.get('payment_method') or '').strip().lower()

    if not order_uuid or not payment_method_str:
        return jsonify({"error": "order_uuid and payment_method are required"}), 400

    try:
        payment_method_enum = PaymentMethod(payment_method_str)
    except ValueError:
        return jsonify({
            "error": "Invalid Payment Method",
            "message": f"'{payment_method_str}' is not supported.",
            "allowed_options": [method.value for method in PaymentMethod]
        }), 400

    try:
        order = Order.query.filter_by(
            uuid=order_uuid,
            user_id=current_customer.id,
            is_active=True
        ).with_for_update().first()
        if not order:
            return jsonify({"error": "Order not found"}), 404

        if order.status != OrderStatus.pending:
            return jsonify({
                "error": "Payment Already Completed",
                "message": f"Payment for this order is no longer pending (Current Status: {order.status.name.capitalize()})."
            }), 400

        payment_record = Payment.query.filter_by(
            order_id=order.id,
            user_id=current_customer.id
        ).with_for_update().first()

        if payment_record and payment_record.status == PaymentStatus.completed:
            return jsonify({
                "error": "Payment Already Completed",
                "message": f"This order has already been paid (TXN ID: {payment_record.transaction_id or 'N/A'})."
            }), 400

        if payment_method_enum in VIRTUAL_PAYMENT_METHODS:
            conflicting_order = _find_conflicting_pending_payment(current_customer, order.id)
            if conflicting_order:
                return jsonify({
                    "error": "Another payment verification is pending",
                    "message": f"Please complete OTP verification for order #{conflicting_order.uuid[:8]} before starting another online payment."
                }), 409

            if payment_record:
                payment_record.payment_method = payment_method_enum
                payment_record.amount = order.total_amount
                payment_record.status = PaymentStatus.pending
                payment_record.transaction_id = None
                payment_record.updated_by = current_customer.id
                payment_record.is_active = True
            else:
                payment_record = Payment(
                    order_id=order.id,
                    user_id=current_customer.id,
                    transaction_id=None,
                    payment_method=payment_method_enum,
                    amount=order.total_amount,
                    status=PaymentStatus.pending,
                    created_by=current_customer.id,
                    updated_by=current_customer.id,
                    is_active=True
                )
                db.session.add(payment_record)

            _invalidate_unused_payment_otps(current_customer.id, current_customer.id)
            _, otp_code = _generate_payment_otp(current_customer)
            db.session.commit()

            email_sent = send_payment_otp_email(
                customer_email=current_customer.email,
                customer_name=current_customer.username or 'Customer',
                order_uuid=order.uuid,
                otp_code=otp_code,
                payment_method=payment_method_enum.value,
                expires_in_minutes=PAYMENT_OTP_EXPIRY_MINUTES
            )

            return jsonify({
                "message": "OTP sent to your email." if email_sent else "Payment initiated, but the OTP email could not be delivered. Please resend OTP.",
                "require_otp": True,
                "order_uuid": order.uuid,
                "payment_method": payment_method_enum.value,
                "expires_in_minutes": PAYMENT_OTP_EXPIRY_MINUTES,
                "email_status": "sent" if email_sent else "failed"
            }), 200

        result = _finalize_order_payment(
            order=order,
            current_customer=current_customer,
            payment_method_enum=payment_method_enum,
            payment_record=payment_record
        )
        db.session.commit()

        email_sent = send_order_status_email(
            customer_email=current_customer.email,
            customer_name=current_customer.username or 'Customer',
            order_uuid=order.uuid,
            order_status=order.status.name,
            total_amount=order.total_amount,
            items=_serialize_order_items(order),
            latest_message=result["tracking_message"]
        )

        return jsonify({
            "message": "Payment Successful! Order tracking is now active.",
            "require_otp": False,
            "data": {
                "order_status": order.status.name,
                "transaction_id": result["transaction_id"],
                "invoice_number": result["invoice"].invoice_number,
                "payment_method": payment_method_enum.value
            },
            "email_status": "Order confirmation email sent successfully." if email_sent else "Payment completed, but the confirmation email could not be sent."
        }), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Payment failed", "details": str(e)}), 500


def _verify_payment_flow(current_customer):
    data = request.get_json() or {}
    order_uuid = str(data.get('order_uuid') or '').strip()
    otp_code = str(data.get('otp_code') or '').strip()

    if not order_uuid or not otp_code:
        return jsonify({"error": "order_uuid and otp_code are required"}), 400

    if not otp_code.isdigit() or len(otp_code) != 6:
        return jsonify({"error": "OTP must be a 6-digit code"}), 400

    try:
        order = Order.query.filter_by(
            uuid=order_uuid,
            user_id=current_customer.id,
            is_active=True
        ).with_for_update().first()
        if not order:
            return jsonify({"error": "Order not found"}), 404

        conflicting_order = _find_conflicting_pending_payment(current_customer, order.id)
        if conflicting_order:
            return jsonify({
                "error": "Another payment verification is pending",
                "message": f"Please complete OTP verification for order #{conflicting_order.uuid[:8]} first."
            }), 409

        if order.status != OrderStatus.pending:
            return jsonify({
                "error": "Payment already verified",
                "message": f"This order is already in {order.status.name} state."
            }), 400

        payment_record = Payment.query.filter_by(
            order_id=order.id,
            user_id=current_customer.id,
            is_active=True
        ).with_for_update().first()

        if not payment_record or payment_record.status != PaymentStatus.pending:
            return jsonify({"error": "No pending payment verification found for this order"}), 400

        if payment_record.payment_method not in VIRTUAL_PAYMENT_METHODS:
            return jsonify({"error": "OTP verification is only required for online payments"}), 400

        otp_entry = Otp.query.filter_by(
            user_id=current_customer.id,
            otp_code=otp_code,
            action=OTPAction.verification,
            is_used=False,
            is_active=True
        ).with_for_update().order_by(Otp.created_at.desc()).first()

        if not otp_entry:
            return jsonify({"error": "Invalid OTP code"}), 400

        if otp_entry.expires_at and otp_entry.expires_at < datetime.utcnow():
            return jsonify({"error": "OTP has expired. Please request a new one."}), 400

        otp_entry.is_used = True
        otp_entry.updated_by = current_customer.id

        result = _finalize_order_payment(
            order=order,
            current_customer=current_customer,
            payment_method_enum=payment_record.payment_method,
            payment_record=payment_record
        )
        db.session.commit()

        email_sent = send_order_status_email(
            customer_email=current_customer.email,
            customer_name=current_customer.username or 'Customer',
            order_uuid=order.uuid,
            order_status=order.status.name,
            total_amount=order.total_amount,
            items=_serialize_order_items(order),
            latest_message=result["tracking_message"]
        )

        return jsonify({
            "message": "Payment verified successfully. Your order is now processing.",
            "require_otp": False,
            "data": {
                "order_status": order.status.name,
                "transaction_id": result["transaction_id"],
                "invoice_number": result["invoice"].invoice_number,
                "payment_method": payment_record.payment_method.value
            },
            "email_status": "Order confirmation email sent successfully." if email_sent else "Payment completed, but the confirmation email could not be sent."
        }), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "OTP verification failed", "details": str(e)}), 500

#================================================================================================================
#================================================================================================================

@user_bp.route('/cart', methods=['POST'])
@customer_required
def add_to_cart(current_customer):
    # Admin cannot buy products - only view
    if current_customer.role.role_name == 'admin':
        return jsonify({"error": "Unauthorized", "message": "Admin users cannot purchase products."}), 403
    
    data = request.get_json() or {}
    product_uuid = data.get('product_uuid')

    try:
        quantity = int(data.get('quantity', 1))
    except (TypeError, ValueError):
        return jsonify({"error": "Quantity must be a valid number"}), 400

    if quantity < 1:
        return jsonify({"error": "Quantity must be at least 1"}), 400
    
    if not product_uuid:
        return jsonify({"error": "Product UUID is required"}), 400
        
    product = Product.query.filter_by(uuid=product_uuid, is_active=True).first()
    if not product:
        return jsonify({"error": "Product not found or inactive"}), 404
        
    if product.stock < quantity:
         return jsonify({"error": f"Only {product.stock} items left in stock"}), 400

    try:
        # Check if item is already in cart AND is active
        existing_cart_item = CartItem.query.filter_by(
            user_id=current_customer.id, 
            product_id=product.id,
            is_active=True  # 👈 Sirf active items check karega
        ).first()
        
        if existing_cart_item:
            new_quantity = existing_cart_item.quantity + quantity
            if new_quantity > product.stock:
                 return jsonify({"error": "Cannot add more. Exceeds available stock."}), 400
            existing_cart_item.quantity = new_quantity
            existing_cart_item.updated_by = current_customer.id # 👈 Audit Trail Update
            message = "Cart item quantity updated"
        else:
            new_cart_item = CartItem(
                user_id=current_customer.id,
                product_id=product.id,
                quantity=quantity,
                created_by=current_customer.id, # 👈 Audit Trail Create
                updated_by=current_customer.id  # 👈 Audit Trail Create
            )
            db.session.add(new_cart_item)
            message = "Product added to cart"
            
        db.session.commit()
        return jsonify({"message": message}), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Failed to add to cart", "details": str(e)}), 500


@user_bp.route('/cart', methods=['GET'])
@customer_required
def view_cart(current_customer):
    # 👈 Sirf wo items lao jo is_active=True hain
    cart_items = CartItem.query.filter_by(user_id=current_customer.id, is_active=True).all()
    
    result = []
    cart_total = 0
    
    for item in cart_items:
        primary_image = ProductImage.query.filter_by(product_id=item.product.id, is_primary=True).first()
        img_url = primary_image.image_url if primary_image else None
        
        item_total = item.product.price * item.quantity
        cart_total += item_total
        
        result.append({
            "cart_item_uuid": item.uuid,
            "product_name": item.product.name,
            "product_uuid": item.product.uuid,
            "price": item.product.price,
            "quantity": item.quantity,
            "item_total": item_total,
            "image": img_url
        })
        
    return jsonify({
        "cart_total": cart_total,
        "items": result
    }), 200


@user_bp.route('/cart/<cart_item_uuid>', methods=['PATCH'])
@customer_required
def update_cart_item(current_customer, cart_item_uuid):
    data = request.get_json() or {}

    try:
        quantity = int(data.get('quantity', 0))
    except (TypeError, ValueError):
        return jsonify({"error": "Quantity must be a valid number"}), 400

    if quantity < 1:
        return jsonify({"error": "Quantity must be at least 1"}), 400

    cart_item = CartItem.query.filter_by(
        uuid=cart_item_uuid,
        user_id=current_customer.id,
        is_active=True
    ).first()

    if not cart_item:
        return jsonify({"error": "Cart item not found"}), 404

    if cart_item.product.stock < quantity:
        return jsonify({"error": f"Only {cart_item.product.stock} items left in stock"}), 400

    try:
        cart_item.quantity = quantity
        cart_item.updated_by = current_customer.id
        db.session.commit()
        return jsonify({"message": "Cart item updated successfully"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Failed to update cart item", "details": str(e)}), 500


@user_bp.route('/cart/<cart_item_uuid>', methods=['DELETE'])
@customer_required
def remove_cart_item(current_customer, cart_item_uuid):
    cart_item = CartItem.query.filter_by(
        uuid=cart_item_uuid,
        user_id=current_customer.id,
        is_active=True
    ).first()

    if not cart_item:
        return jsonify({"error": "Cart item not found"}), 404

    try:
        cart_item.is_active = False
        cart_item.updated_by = current_customer.id
        db.session.commit()
        return jsonify({"message": "Cart item removed successfully"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Failed to remove cart item", "details": str(e)}), 500


#================================================================================================================
#================================================================================================================


@user_bp.route('/address', methods=['POST'])
@customer_required
def add_address(current_customer):
    data = request.get_json() or {}
    
    # Validation (full_name aur phone_number add kiye)
    required = ['full_name', 'phone_number', 'street', 'city', 'state', 'pincode']
    if not all(k in data for k in required):
        return jsonify({"error": "Missing address details. Required: full_name, phone_number, street, city, state, pincode"}), 400
        
    try:
        new_address = Address(
            user_id=current_customer.id,
            full_name=data.get('full_name'),        
            phone_number=data.get('phone_number'), 
            street=data.get('street'),
            city=data.get('city'),
            state=data.get('state'),
            pincode=data.get('pincode'),
            is_default=data.get('is_default', False)
        )
        db.session.add(new_address)
        db.session.commit()
        
        return jsonify({
            "message": "Address saved successfully",
            "address_uuid": new_address.uuid
        }), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@user_bp.route('/address/<address_uuid>', methods=['PATCH'])
@customer_required
def update_address(current_customer, address_uuid):
    data = request.get_json() or {}

    required = ['full_name', 'phone_number', 'street', 'city', 'state', 'pincode']
    if not all(str(data.get(field, '')).strip() for field in required):
        return jsonify({"error": "All address fields are required"}), 400

    address = Address.query.filter_by(
        uuid=address_uuid,
        user_id=current_customer.id,
        is_active=True
    ).first()

    if not address:
        return jsonify({"error": "Address not found"}), 404

    try:
        address.full_name = data.get('full_name').strip()
        address.phone_number = data.get('phone_number').strip()
        address.street = data.get('street').strip()
        address.city = data.get('city').strip()
        address.state = data.get('state').strip()
        address.pincode = data.get('pincode').strip()
        address.updated_by = current_customer.id

        db.session.commit()

        return jsonify({
            "message": "Address updated successfully",
            "address_uuid": address.uuid
        }), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@user_bp.route('/address/<address_uuid>', methods=['DELETE'])
@customer_required
def delete_address(current_customer, address_uuid):
    address = Address.query.filter_by(
        uuid=address_uuid,
        user_id=current_customer.id,
        is_active=True
    ).first()

    if not address:
        return jsonify({"error": "Address not found"}), 404

    try:
        address.is_active = False
        address.updated_by = current_customer.id
        db.session.commit()

        return jsonify({
            "message": "Address deleted successfully"
        }), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@user_bp.route('/payment/verify', methods=['POST'])
@customer_required
def verify_payment(current_customer):
    return _verify_payment_flow(current_customer)


#+++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
#+++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

@user_bp.route('/checkout', methods=['POST'])
@customer_required
def checkout(current_customer):
    # Admin cannot checkout
    if current_customer.role.role_name == 'admin':
        return jsonify({"error": "Unauthorized", "message": "Admin users cannot place orders."}), 403

    return _checkout_customer_order(current_customer)
    
    data = request.get_json() or {}
    address_uuid = str(data.get('address_uuid') or '').strip()
    
    if not address_uuid:
        return jsonify({"error": "address_uuid is required"}), 400

    address = Address.query.filter_by(
        uuid=address_uuid,
        user_id=current_customer.id,
        is_active=True
    ).first()
    if not address:
        return jsonify({"error": "Invalid delivery address"}), 404
        
    # 👈 Sirf active cart items ko checkout process me lo
    try:
        cart_items = CartItem.query.filter_by(
            user_id=current_customer.id,
            is_active=True
        ).with_for_update().all()

        if not cart_items:
            return jsonify({"error": "Cart is empty"}), 400

        total_amount = 0.0
        locked_products = {}
        order_items_to_create = []
        for item in cart_items:
            if item.quantity < 1:
                return jsonify({"error": "Cart contains an invalid quantity"}), 400

            product = Product.query.filter_by(
                id=item.product_id,
                is_active=True
            ).with_for_update().first()

            if not product:
                return jsonify({"error": "One of the cart products is unavailable"}), 404

            if product.stock < item.quantity:
                return jsonify({
                    "error": "Insufficient stock",
                    "message": f"Only {product.stock} unit(s) of {product.name} are available right now."
                }), 409

            locked_products[product.id] = product
            total_amount += float(product.price) * item.quantity

            order_items_to_create.append({
                "product_id": product.id,
                "quantity": item.quantity,
                "price_at_purchase": float(product.price)
            })

        new_order = Order(
            user_id=current_customer.id,
            address_id=address.id,
            total_amount=total_amount,
            status=OrderStatus.pending,
            created_by=current_customer.id, # 👈 Audit Trail
            updated_by=current_customer.id  # 👈 Audit Trail
        )
        db.session.add(new_order)
        db.session.flush()

        for item_payload in order_items_to_create:
            db.session.add(OrderItem(
                order_id=new_order.id,
                product_id=item_payload["product_id"],
                quantity=item_payload["quantity"],
                price_at_purchase=item_payload["price_at_purchase"],
                created_by=current_customer.id, # 👈 Audit Trail
                updated_by=current_customer.id  # 👈 Audit Trail
            ))

            locked_products[item_payload["product_id"]].stock -= item_payload["quantity"]

        db.session.add(OrderTracking(
            order_id=new_order.id,
            status=OrderStatus.pending,
            message="Order created successfully and awaiting payment confirmation.",
            created_by=current_customer.id,
            updated_by=current_customer.id,
            is_active=True
        ))

        # 🚀 SOFT DELETE LOGIC (Hard delete hata diya)
        for item in cart_items:
            item.is_active = False # 👈 Soft Delete
            item.updated_by = current_customer.id # Kisne delete kiya
        
        db.session.commit()
        
        return jsonify({
            "message": "Order placed successfully!",
            "order_uuid": new_order.uuid,
            "total_payable": total_amount
        }), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Transaction failed", "details": str(e)}), 500
#+++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
#+++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

@user_bp.route('/payment', methods=['POST'])
@customer_required
def process_payment(current_customer):
    return _process_payment_flow(current_customer)

    if not order_uuid or not payment_method_str:
        return jsonify({"error": "order_uuid and payment_method are required"}), 400

    # =========================================================================
    # 🛡️ STRICT VALIDATION: Check if payment method is valid
    # =========================================================================
    valid_methods = [m.name for m in PaymentMethod] # Ye list banayega: ['cod', 'card', 'upi', 'netbanking']
    
    # Lowercase me convert karke check kar rahe hain taaki 'UPI', 'Upi', 'upi' sab chal jaye
    if payment_method_str.lower() not in valid_methods:
        return jsonify({
            "error": "Invalid Payment Method",
            "message": f"Aapne '{payment_method_str}' select kiya hai jo ki galat hai. Kripya allowed options me se kuch chunein.",
            "allowed_options": valid_methods # Ye user ko options dikha dega
        }), 400
        
    payment_method_clean = payment_method_str.lower()
    # =========================================================================

    # 1. Order dhundho
    order = Order.query.filter_by(uuid=order_uuid, user_id=current_customer.id).first()
    if not order:
        return jsonify({"error": "Order not found"}), 404

    # =========================================================================
    # 🛡️ DOUBLE PAYMENT PREVENTION LOGIC
    # =========================================================================
    # Check 1: Agar order 'pending' nahi hai (yani processing, shipped ya delivered hai)
    if order.status != OrderStatus.pending:
        return jsonify({
            "error": "Payment Already Completed",
            "message": f"Payment for this order has already been made (Current Status: {order.status.name.capitalize()}). There is no need to make a payment again."
        }), 400

    # Check 2: Database mein directly Payment table check karo (Extra Safety)
    existing_payment = Payment.query.filter_by(order_id=order.id, status=PaymentStatus.completed).first()
    if existing_payment:
        return jsonify({
            "error": "Payment Already Completed",
            "message": f"Is order ka payment system mein already darj hai (TXN ID: {existing_payment.transaction_id})."
        }), 400
    # =========================================================================

    if order.status == OrderStatus.processing:
        return jsonify({"error": "Order is already paid and being processed"}), 400

    try:
        # --- TRANSACTION START ---
        
        # 2. Payment Record Create Karo
        txn_id = "TXN-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=10))
        payment_status = PaymentStatus.completed 
        
        new_payment = Payment(
            order_id=order.id,
            user_id=current_customer.id,
            transaction_id=txn_id if payment_method_clean != 'cod' else None,
            payment_method=payment_method_clean, # 👈 Cleaned string yahan use ki hai
            amount=order.total_amount,
            status=payment_status,
            created_by=current_customer.id, 
            updated_by=current_customer.id,
            is_active=True
        )
        db.session.add(new_payment)

        # 3. Order Table Update 
        order.status = OrderStatus.processing
        order.updated_by = current_customer.id

        # 4. ORDER TRACKING 
        new_tracking = OrderTracking(
            order_id=order.id,
            status=OrderStatus.processing,
            message=f"Payment via {payment_method_clean.upper()} Successful. Your order is now being processed.",
            created_by=current_customer.id,
            updated_by=current_customer.id,
            is_active=True
        )
        db.session.add(new_tracking)

        # 5. Invoice Generate Karo
        inv_number = f"INV-{order.id}-{random.randint(1000, 9999)}"
        new_invoice = Invoice(
            order_id=order.id,
            invoice_number=inv_number,
            created_by=current_customer.id,
            updated_by=current_customer.id,
            is_active=True
        )
        db.session.add(new_invoice)

        db.session.commit()
        # --- TRANSACTION END ---

        order_items = [{
            "product_name": item.product.name if getattr(item, 'product', None) else f"Product #{item.product_id}",
            "quantity": item.quantity,
            "line_total": float(item.price_at_purchase) * item.quantity
        } for item in order.items]

        email_sent = send_order_status_email(
            customer_email=current_customer.email,
            customer_name=current_customer.username or 'Customer',
            order_uuid=order.uuid,
            order_status=order.status.name,
            total_amount=order.total_amount,
            items=order_items,
            latest_message=f"Payment via {payment_method_clean.upper()} was successful. Your order is now being processed."
        )

        return jsonify({
            "message": "Payment Successful! Order tracking is now active.",
            "data": {
                "order_status": order.status.name,
                "transaction_id": txn_id if payment_method_clean != 'cod' else "N/A",
                "invoice_number": inv_number,
                "payment_method": payment_method_clean
            },
            "email_status": "Order confirmation email sent successfully." if email_sent else "Payment completed, but the confirmation email could not be sent."
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Payment failed", "details": str(e)}), 500

#+++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
#+++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

def _format_tracking_timestamp(value):
    return value.strftime("%Y-%m-%d %H:%M:%S") if value else None


def _build_tracking_payload(order):
    tracking_entries = sorted(
        list(order.tracking or []),
        key=lambda entry: entry.updated_at or entry.created_at or order.created_at
    )
    tracking_by_status = {
        entry.status.name: entry
        for entry in tracking_entries
    }

    stage_blueprint = [
        {
            "key": "pending",
            "title": "Order placed",
            "default_message": "Your order has been placed successfully and is waiting for the next update."
        },
        {
            "key": "processing",
            "title": "Processing",
            "default_message": "Payment is confirmed and your order is being prepared for dispatch."
        },
        {
            "key": "shipped",
            "title": "Shipped",
            "default_message": "Your package has left the warehouse and is on the way."
        },
        {
            "key": "delivered",
            "title": "Delivered",
            "default_message": "The package has reached the delivery address."
        },
    ]

    progress_map = {
        "pending": 20,
        "processing": 50,
        "shipped": 80,
        "delivered": 100,
        "cancelled": 100,
    }

    current_status = order.status.name
    current_index = next((index for index, stage in enumerate(stage_blueprint) if stage["key"] == current_status), -1)

    timeline = []
    for index, stage in enumerate(stage_blueprint):
        tracking_entry = tracking_by_status.get(stage["key"])
        timestamp = None

        if stage["key"] == "pending":
            timestamp = order.created_at
        elif tracking_entry:
            timestamp = tracking_entry.updated_at or tracking_entry.created_at
        elif current_status != "cancelled" and current_index >= index:
            timestamp = order.updated_at or order.created_at

        is_completed = current_status != "cancelled" and current_index >= index
        is_current = current_status != "cancelled" and current_index == index

        timeline.append({
            "step_key": stage["key"],
            "title": stage["title"],
            "status": "completed" if is_completed else ("current" if is_current else "upcoming"),
            "completed": is_completed,
            "current": is_current,
            "message": tracking_entry.message if tracking_entry and tracking_entry.message else stage["default_message"],
            "timestamp": _format_tracking_timestamp(timestamp)
        })

    if current_status == "cancelled":
        cancel_entry = tracking_by_status.get("cancelled")
        timeline.append({
            "step_key": "cancelled",
            "title": "Cancelled",
            "status": "current",
            "completed": True,
            "current": True,
            "message": cancel_entry.message if cancel_entry and cancel_entry.message else "This order was cancelled.",
            "timestamp": _format_tracking_timestamp(
                (cancel_entry.updated_at or cancel_entry.created_at) if cancel_entry else (order.updated_at or order.created_at)
            )
        })

    estimated_delivery = None
    if current_status == "pending":
        estimated_delivery = order.created_at + timedelta(days=6)
    elif current_status == "processing":
        estimated_delivery = order.created_at + timedelta(days=4)
    elif current_status == "shipped":
        estimated_delivery = order.created_at + timedelta(days=2)
    elif current_status == "delivered":
        estimated_delivery = order.updated_at or order.created_at

    items = []
    for item in order.items:
        product = getattr(item, 'product', None)
        items.append({
            "item_uuid": item.uuid,
            "product_uuid": product.uuid if product else None,
            "product_name": product.name if product else f"Product #{item.product_id}",
            "quantity": item.quantity,
            "price_at_purchase": item.price_at_purchase,
            "line_total": item.price_at_purchase * item.quantity
        })

    latest_tracking = tracking_entries[-1] if tracking_entries else None
    latest_update = {
        "status": latest_tracking.status.name if latest_tracking else current_status,
        "message": latest_tracking.message if latest_tracking and latest_tracking.message else timeline[-1]["message"],
        "timestamp": _format_tracking_timestamp(
            (latest_tracking.updated_at or latest_tracking.created_at) if latest_tracking else (order.updated_at or order.created_at)
        )
    }

    shipping_address = None
    if order.shipping_address:
        shipping_address = {
            "full_name": order.shipping_address.full_name,
            "phone_number": order.shipping_address.phone_number,
            "street": order.shipping_address.street,
            "city": order.shipping_address.city,
            "state": order.shipping_address.state,
            "pincode": order.shipping_address.pincode,
        }

    return {
        "order_uuid": order.uuid,
        "order_id": order.id,
        "current_status": current_status,
        "status_label": current_status.replace('_', ' ').title(),
        "progress_percent": progress_map.get(current_status, 0),
        "estimated_delivery": _format_tracking_timestamp(estimated_delivery),
        "latest_update": latest_update,
        "total_amount": order.total_amount,
        "created_at": _format_tracking_timestamp(order.created_at),
        "updated_at": _format_tracking_timestamp(order.updated_at),
        "shipping_address": shipping_address,
        "items": items,
        "summary": {
            "item_count": len(items),
            "total_amount": order.total_amount,
            "payment_method": order.payment.payment_method.name if order.payment else None,
            "payment_status": order.payment.status.name if order.payment else None,
        },
        "tracking_history": timeline,
        "timeline": timeline
    }


@user_bp.route('/order/<order_uuid>/track', methods=['GET'])
@customer_required
def track_order(current_customer, order_uuid):
    order = Order.query.filter_by(uuid=order_uuid, user_id=current_customer.id).first()
    
    if not order:
        return jsonify({"error": "Order not found or access denied"}), 404
        
    return jsonify(_build_tracking_payload(order)), 200

#+++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
# GET USER ORDERS
#+++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

@user_bp.route('/orders', methods=['GET'])
@customer_required
def get_user_orders(current_customer):
    # Fetch all orders for the current customer
    orders = Order.query.filter_by(user_id=current_customer.id).order_by(Order.created_at.desc()).all()
    
    result = []
    for order in orders:
        order_items = []
        for item in order.items:
            product = getattr(item, 'product', None)
            order_items.append({
                "item_uuid": item.uuid,
                "product_name": product.name if product else f"Product #{item.product_id}",
                "product_uuid": product.uuid if product else None,
                "quantity": item.quantity,
                "price_at_purchase": item.price_at_purchase,
                "line_total": item.price_at_purchase * item.quantity
            })
        
        result.append({
            "order_uuid": order.uuid,
            "order_id": order.id,
            "status": order.status.name,
            "total_amount": order.total_amount,
            "created_at": order.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            "items": order_items,
            "item_count": len(order_items)
        })
    
    return jsonify({
        "total_orders": len(result),
        "orders": result
    }), 200

#+++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
#+++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

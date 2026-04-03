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

class CheckoutFlowError(Exception):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _serialize_order_items(order):
    return [{
        "product_name": item.product.name if getattr(item, 'product', None) else f"Product #{item.product_id}",
        "quantity": item.quantity,
        "line_total": float(item.price_at_purchase) * item.quantity
    } for item in order.items if item.is_active]


def _get_payment_method_enum(payment_method_str):
    if not payment_method_str:
        raise CheckoutFlowError("payment_method is required", 400)

    try:
        return PaymentMethod(str(payment_method_str).strip().lower())
    except ValueError:
        raise CheckoutFlowError(
            f"Unsupported payment method. Allowed options: {', '.join(method.value for method in PaymentMethod)}",
            400
        )


def _lock_active_cart_items(current_customer):
    cart_items = CartItem.query.filter_by(
        user_id=current_customer.id,
        is_active=True
    ).with_for_update().all()

    if not cart_items:
        raise CheckoutFlowError("Cart is empty", 400)

    return cart_items


def _validate_cart_items_and_collect_snapshot(cart_items):
    total_amount = 0.0
    snapshot = []

    for cart_item in cart_items:
        if cart_item.quantity < 1:
            raise CheckoutFlowError("Cart contains an invalid quantity", 400)

        product = Product.query.filter_by(
            id=cart_item.product_id,
            is_active=True
        ).with_for_update().first()

        if not product:
            raise CheckoutFlowError("One of the cart products is unavailable", 404)

        if product.stock < cart_item.quantity:
            raise CheckoutFlowError(
                f"Only {product.stock} unit(s) of {product.name} are available right now.",
                409
            )

        item_total = float(product.price) * cart_item.quantity
        total_amount += item_total
        snapshot.append({
            "product": product,
            "cart_item": cart_item,
            "quantity": cart_item.quantity,
            "price_at_purchase": float(product.price),
        })

    return snapshot, total_amount


def _create_order_from_snapshot(current_customer, address, payment_method_enum, snapshot, total_amount):
    order = Order(
        user_id=current_customer.id,
        address_id=address.id,
        total_amount=total_amount,
        payment_method=payment_method_enum,
        status=OrderStatus.pending,
        created_by=current_customer.id,
        updated_by=current_customer.id,
        is_active=True
    )
    db.session.add(order)
    db.session.flush()

    for item in snapshot:
        db.session.add(OrderItem(
            order_id=order.id,
            product_id=item["product"].id,
            quantity=item["quantity"],
            price_at_purchase=item["price_at_purchase"],
            created_by=current_customer.id,
            updated_by=current_customer.id,
            is_active=True
        ))

    db.session.add(OrderTracking(
        order_id=order.id,
        status=OrderStatus.pending,
        message=(
            "Order created successfully and awaiting payment verification."
            if payment_method_enum in VIRTUAL_PAYMENT_METHODS
            else "Cash on Delivery selected. Your order is now moving to processing."
        ),
        created_by=current_customer.id,
        updated_by=current_customer.id,
        is_active=True
    ))

    return order


def _invalidate_unused_payment_otps(customer_id, order_id, actor_id):
    Otp.query.filter_by(
        user_id=customer_id,
        order_id=order_id,
        action=OTPAction.verification,
        is_used=False,
        is_active=True
    ).update({
        "is_used": True,
        "updated_by": actor_id,
    }, synchronize_session=False)


def _generate_payment_otp(current_customer, order):
    otp_code = f"{random.randint(0, 999999):06d}"
    otp_entry = Otp(
        user_id=current_customer.id,
        order_id=order.id,
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


def _generate_transaction_id():
    return "TXN-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=10))


def _get_active_order_items(order):
    return OrderItem.query.filter_by(order_id=order.id, is_active=True).all()


def _lock_products_for_order(order):
    locked_products = {}

    for order_item in _get_active_order_items(order):
        product = Product.query.filter_by(
            id=order_item.product_id,
            is_active=True
        ).with_for_update().first()

        if not product:
            raise CheckoutFlowError("One of the ordered products is unavailable", 404)

        if product.stock < order_item.quantity:
            raise CheckoutFlowError(
                f"Stock changed before verification. Only {product.stock} unit(s) of {product.name} remain.",
                409
            )

        locked_products[product.id] = product

    return locked_products


def _apply_stock_deduction(order, locked_products):
    for order_item in _get_active_order_items(order):
        locked_products[order_item.product_id].stock -= order_item.quantity


def _sync_cart_after_checkout(current_customer, order):
    active_cart_items = {
        item.product_id: item
        for item in CartItem.query.filter_by(
            user_id=current_customer.id,
            is_active=True
        ).with_for_update().all()
    }

    for order_item in _get_active_order_items(order):
        cart_item = active_cart_items.get(order_item.product_id)
        if not cart_item:
            continue

        if cart_item.quantity <= order_item.quantity:
            cart_item.is_active = False
        else:
            cart_item.quantity -= order_item.quantity

        cart_item.updated_by = current_customer.id


def _build_processing_tracking_message(payment_method_enum, payment_status):
    if payment_method_enum == PaymentMethod.cod:
        return "Cash on Delivery confirmed. Your order is now being processed and payment will be collected on delivery."

    if payment_status == PaymentStatus.completed:
        return f"Payment via {payment_method_enum.value.upper()} verified successfully. Your order is now being processed."

    return f"Payment via {payment_method_enum.value.upper()} is pending while your order moves to processing."


def _finalize_order_payment(order, current_customer, payment_status):
    payment_method_enum = order.payment_method
    if not payment_method_enum:
        raise CheckoutFlowError("Order payment method is missing", 400)

    locked_products = _lock_products_for_order(order)
    _apply_stock_deduction(order, locked_products)
    _sync_cart_after_checkout(current_customer, order)

    transaction_id = _generate_transaction_id() if payment_status == PaymentStatus.completed else None
    payment_record = order.payment

    if payment_record:
        payment_record.payment_method = payment_method_enum
        payment_record.amount = order.total_amount
        payment_record.status = payment_status
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
            status=payment_status,
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
        message=_build_processing_tracking_message(payment_method_enum, payment_status),
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

    _invalidate_unused_payment_otps(current_customer.id, order.id, current_customer.id)

    return {
        "payment": payment_record,
        "invoice": invoice_record,
        "transaction_id": transaction_id or "N/A",
        "tracking_message": _build_processing_tracking_message(payment_method_enum, payment_status),
    }


def _checkout_customer_order(current_customer):
    data = request.get_json() or {}
    address_uuid = str(data.get('address_uuid') or '').strip()
    order_uuid = str(data.get('order_uuid') or '').strip()
    payment_method_raw = data.get('payment_method')

    try:
        payment_method_enum = _get_payment_method_enum(payment_method_raw) if payment_method_raw else None

        if order_uuid:
            order = Order.query.filter_by(
                uuid=order_uuid,
                user_id=current_customer.id,
                is_active=True
            ).with_for_update().first()

            if not order:
                raise CheckoutFlowError("Pending order not found", 404)

            if order.status != OrderStatus.pending:
                raise CheckoutFlowError("This order is no longer awaiting verification.", 400)

            if order.payment_method not in VIRTUAL_PAYMENT_METHODS:
                raise CheckoutFlowError("OTP verification is only available for online payments.", 400)

            if payment_method_enum and payment_method_enum != order.payment_method:
                raise CheckoutFlowError("Payment method mismatch for this pending order.", 400)

            _lock_products_for_order(order)
            _invalidate_unused_payment_otps(current_customer.id, order.id, current_customer.id)
            _, otp_code = _generate_payment_otp(current_customer, order)
            db.session.commit()

            email_sent = send_payment_otp_email(
                customer_email=current_customer.email,
                customer_name=current_customer.username or 'Customer',
                order_uuid=order.uuid,
                otp_code=otp_code,
                payment_method=order.payment_method.value,
                expires_in_minutes=PAYMENT_OTP_EXPIRY_MINUTES
            )

            return jsonify({
                "message": "OTP sent" if email_sent else "OTP generated, but the email could not be delivered. Please try again.",
                "require_otp": True,
                "order_uuid": order.uuid,
                "payment_method": order.payment_method.value,
                "expires_in_minutes": PAYMENT_OTP_EXPIRY_MINUTES,
                "email_status": "sent" if email_sent else "failed"
            }), 200

        if not address_uuid:
            raise CheckoutFlowError("address_uuid is required", 400)

        if not payment_method_enum:
            raise CheckoutFlowError("payment_method is required", 400)

        address = Address.query.filter_by(
            uuid=address_uuid,
            user_id=current_customer.id,
            is_active=True
        ).first()
        if not address:
            raise CheckoutFlowError("Invalid delivery address", 404)

        cart_items = _lock_active_cart_items(current_customer)
        snapshot, total_amount = _validate_cart_items_and_collect_snapshot(cart_items)
        order = _create_order_from_snapshot(current_customer, address, payment_method_enum, snapshot, total_amount)

        if payment_method_enum == PaymentMethod.cod:
            result = _finalize_order_payment(order, current_customer, PaymentStatus.pending)
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
                "message": "Order placed successfully! Cash on Delivery selected.",
                "require_otp": False,
                "order_uuid": order.uuid,
                "data": {
                    "order_status": order.status.name,
                    "transaction_id": result["transaction_id"],
                    "invoice_number": result["invoice"].invoice_number,
                    "payment_method": payment_method_enum.value,
                    "payment_status": result["payment"].status.name
                },
                "email_status": "Order confirmation email sent successfully." if email_sent else "Order placed, but the confirmation email could not be sent."
            }), 201

        _, otp_code = _generate_payment_otp(current_customer, order)
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
            "message": "OTP sent" if email_sent else "OTP generated, but the email could not be delivered. Please try again.",
            "require_otp": True,
            "order_uuid": order.uuid,
            "payment_method": payment_method_enum.value,
            "expires_in_minutes": PAYMENT_OTP_EXPIRY_MINUTES,
            "email_status": "sent" if email_sent else "failed"
        }), 201
    except CheckoutFlowError as exc:
        db.session.rollback()
        return jsonify({"error": exc.message}), exc.status_code
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Checkout initiation failed", "details": str(e)}), 500


def _process_payment_flow(current_customer):
    return jsonify({
        "error": "Deprecated endpoint",
        "message": "Use /api/user/checkout/initiate and /api/user/checkout/verify for the two-phase checkout flow."
    }), 410


def _verify_payment_flow(current_customer):
    data = request.get_json() or {}
    order_uuid = str(data.get('order_uuid') or '').strip()
    otp_code = str(data.get('otp_code') or '').strip()
    try:
        if not order_uuid or not otp_code:
            raise CheckoutFlowError("order_uuid and otp_code are required", 400)

        if not otp_code.isdigit() or len(otp_code) != 6:
            raise CheckoutFlowError("OTP must be a 6-digit code", 400)

        order = Order.query.filter_by(
            uuid=order_uuid,
            user_id=current_customer.id,
            is_active=True
        ).with_for_update().first()
        if not order:
            raise CheckoutFlowError("Order not found", 404)

        if order.status != OrderStatus.pending:
            raise CheckoutFlowError(f"This order is already in {order.status.name} state.", 400)

        if order.payment_method not in VIRTUAL_PAYMENT_METHODS:
            raise CheckoutFlowError("OTP verification is only required for online payments", 400)

        otp_entry = Otp.query.filter_by(
            user_id=current_customer.id,
            order_id=order.id,
            otp_code=otp_code,
            action=OTPAction.verification,
            is_used=False,
            is_active=True
        ).with_for_update().order_by(Otp.created_at.desc()).first()

        if not otp_entry:
            raise CheckoutFlowError("Invalid OTP code", 400)

        if otp_entry.expires_at and otp_entry.expires_at < datetime.utcnow():
            raise CheckoutFlowError("OTP has expired. Please request a new one.", 400)

        _lock_products_for_order(order)
        otp_entry.is_used = True
        otp_entry.updated_by = current_customer.id

        result = _finalize_order_payment(order, current_customer, PaymentStatus.completed)
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
            "order_uuid": order.uuid,
            "data": {
                "order_status": order.status.name,
                "transaction_id": result["transaction_id"],
                "invoice_number": result["invoice"].invoice_number,
                "payment_method": order.payment_method.value,
                "payment_status": result["payment"].status.name
            },
            "email_status": "Order confirmation email sent successfully." if email_sent else "Payment completed, but the confirmation email could not be sent."
        }), 200
    except CheckoutFlowError as exc:
        db.session.rollback()
        return jsonify({"error": exc.message}), exc.status_code
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


@user_bp.route('/checkout/initiate', methods=['POST'])
@customer_required
def initiate_checkout(current_customer):
    return _checkout_customer_order(current_customer)


@user_bp.route('/checkout/verify', methods=['POST'])
@customer_required
def verify_checkout(current_customer):
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
            "payment_method": order.payment.payment_method.name if order.payment else (order.payment_method.name if order.payment_method else None),
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
            "payment_method": order.payment.payment_method.name if order.payment else (order.payment_method.name if order.payment_method else None),
            "payment_status": order.payment.status.name if order.payment else None,
            "items": order_items,
            "item_count": len(order_items)
        })
    
    return jsonify({
        "total_orders": len(result),
        "orders": result
    }), 200

#+++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
#+++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

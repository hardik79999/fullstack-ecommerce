import random
import string
from datetime import datetime, timedelta

from flask import Blueprint, current_app, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from shop.extensions import db
from shop.models import (
    Address,
    CartItem,
    Coupon,
    Invoice,
    Order,
    OrderItem,
    OrderStatus,
    OrderTracking,
    OTPAction,
    Otp,
    Payment,
    PaymentMethod,
    PaymentStatus,
    Product,
    ProductImage,
    User,
    Wishlist,
)
from shop.utils.api_response import error_response, success_response
from shop.utils.decorators import customer_required
from shop.utils.email_service import send_order_status_email, send_payment_otp_email

user_bp = Blueprint('user', __name__)

PAYMENT_OTP_EXPIRY_MINUTES = 10
VIRTUAL_PAYMENT_METHODS = {
    PaymentMethod.card,
    PaymentMethod.upi,
    PaymentMethod.netbanking,
}


class CheckoutFlowError(Exception):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
def _format_timestamp(value):
    return value.strftime("%Y-%m-%d %H:%M:%S") if value else None


def _get_primary_image(product):
    return ProductImage.query.filter_by(
        product_id=product.id,
        is_primary=True,
        is_active=True,
    ).first()


def _get_active_images(product):
    return ProductImage.query.filter_by(
        product_id=product.id,
        is_active=True,
    ).order_by(ProductImage.created_at.asc()).all()


def _get_active_reviews(product):
    return [review for review in product.reviews if review.is_active]


def _build_review_metrics(reviews):
    if not reviews:
        return None, 0

    average_rating = round(sum(float(review.rating or 0) for review in reviews) / len(reviews), 1)
    return average_rating, len(reviews)


def _serialize_review(review, reviewer_lookup=None):
    reviewer = None
    if reviewer_lookup is not None:
        reviewer = reviewer_lookup.get(review.user_id)
    if reviewer is None:
        reviewer = User.query.filter_by(id=review.user_id, is_active=True).first()

    comment = (review.comment or '').strip() or 'Customer shared a positive product experience.'

    return {
        "uuid": review.uuid,
        "author": reviewer.username if reviewer else "Customer",
        "rating": int(review.rating or 0),
        "comment": comment,
        "created_at": _format_timestamp(review.created_at),
    }


def _serialize_product_summary(product):
    reviews = _get_active_reviews(product)
    average_rating, review_count = _build_review_metrics(reviews)
    primary_image = _get_primary_image(product)

    return {
        "uuid": product.uuid,
        "name": product.name,
        "description": product.description,
        "price": float(product.price),
        "stock": int(product.stock or 0),
        "category": product.category.name if product.category else None,
        "seller": product.seller_user.username if product.seller_user else None,
        "primary_image": primary_image.image_url if primary_image else None,
        "specifications": [
            {"key": spec.spec_key, "value": spec.spec_value}
            for spec in product.specifications
            if spec.is_active
        ],
        "average_rating": average_rating,
        "review_count": review_count,
    }


def _serialize_product_detail(product):
    detail = _serialize_product_summary(product)
    reviews = sorted(
        _get_active_reviews(product),
        key=lambda review: review.updated_at or review.created_at or datetime.utcnow(),
        reverse=True,
    )
    reviewer_ids = {review.user_id for review in reviews}
    reviewers = User.query.filter(User.id.in_(reviewer_ids)).all() if reviewer_ids else []
    reviewer_lookup = {reviewer.id: reviewer for reviewer in reviewers}

    detail.update({
        "images": [image.image_url for image in _get_active_images(product)],
        "reviews": [_serialize_review(review, reviewer_lookup) for review in reviews],
    })

    return detail


def _serialize_cart_item(cart_item):
    product = cart_item.product
    if not product or not product.is_active:
        return None

    primary_image = _get_primary_image(product)
    item_total = float(product.price) * int(cart_item.quantity or 0)

    return {
        "cart_item_uuid": cart_item.uuid,
        "product_name": product.name,
        "product_uuid": product.uuid,
        "price": float(product.price),
        "quantity": int(cart_item.quantity or 0),
        "item_total": item_total,
        "image": primary_image.image_url if primary_image else None,
        "stock": int(product.stock or 0),
        "category": product.category.name if product.category else None,
        "seller": product.seller_user.username if product.seller_user else None,
        "description": product.description,
    }


def _serialize_coupon_summary():
    now = datetime.utcnow()
    active_coupons = Coupon.query.filter(
        Coupon.is_active.is_(True),
        Coupon.expiry_date >= now,
    ).order_by(Coupon.expiry_date.asc()).all()

    if not active_coupons:
        return {
            "active_coupon_count": 0,
            "headline": "Offers refresh automatically when new coupons go live.",
            "codes": [],
        }

    best_percentage = max(float(coupon.discount_percentage or 0) for coupon in active_coupons)
    best_flat = max(float(coupon.discount_flat or 0) for coupon in active_coupons)

    if best_percentage > 0:
        highlight = f"up to {int(best_percentage)}% off"
    elif best_flat > 0:
        highlight = f"up to Rs.{best_flat:.0f} off"
    else:
        highlight = "exclusive savings"

    return {
        "active_coupon_count": len(active_coupons),
        "headline": f"{len(active_coupons)} live offer(s) available right now, including {highlight}.",
        "codes": [coupon.code for coupon in active_coupons[:3]],
    }


def _serialize_order_items(order):
    return [{
        "product_name": item.product.name if getattr(item, 'product', None) else f"Product #{item.product_id}",
        "quantity": item.quantity,
        "line_total": float(item.price_at_purchase) * item.quantity,
    } for item in order.items if item.is_active]


def _get_payment_method_enum(payment_method_str):
    if not payment_method_str:
        raise CheckoutFlowError("payment_method is required", 400)

    try:
        return PaymentMethod(str(payment_method_str).strip().lower())
    except ValueError as exc:
        raise CheckoutFlowError(
            f"Unsupported payment method. Allowed options: {', '.join(method.value for method in PaymentMethod)}",
            400,
        ) from exc


def _lock_active_cart_items(current_customer):
    cart_items = CartItem.query.filter_by(
        user_id=current_customer.id,
        is_active=True,
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
            is_active=True,
        ).with_for_update().first()

        if not product:
            raise CheckoutFlowError("One of the cart products is unavailable", 404)

        if product.stock < cart_item.quantity:
            raise CheckoutFlowError(
                f"Only {product.stock} unit(s) of {product.name} are available right now.",
                409,
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
        is_active=True,
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
            is_active=True,
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
        is_active=True,
    ))

    return order


def _invalidate_unused_payment_otps(customer_id, order_id, actor_id):
    Otp.query.filter_by(
        user_id=customer_id,
        order_id=order_id,
        action=OTPAction.verification,
        is_used=False,
        is_active=True,
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
            is_active=True,
        ).with_for_update().first()

        if not product:
            raise CheckoutFlowError("One of the ordered products is unavailable", 404)

        if product.stock < order_item.quantity:
            raise CheckoutFlowError(
                f"Stock changed before verification. Only {product.stock} unit(s) of {product.name} remain.",
                409,
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
            is_active=True,
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
            is_active=True,
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
        is_active=True,
    )
    db.session.add(tracking_entry)

    invoice_record = order.invoice
    if not invoice_record:
        invoice_record = Invoice(
            order_id=order.id,
            invoice_number=f"INV-{order.id}-{random.randint(1000, 9999)}",
            created_by=current_customer.id,
            updated_by=current_customer.id,
            is_active=True,
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
                is_active=True,
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
                expires_in_minutes=PAYMENT_OTP_EXPIRY_MINUTES,
            )

            return success_response(
                "OTP sent" if email_sent else "OTP generated, but the email could not be delivered. Please try again.",
                require_otp=True,
                order_uuid=order.uuid,
                payment_method=order.payment_method.value,
                expires_in_minutes=PAYMENT_OTP_EXPIRY_MINUTES,
                email_status="sent" if email_sent else "failed",
            )

        if not address_uuid:
            raise CheckoutFlowError("address_uuid is required", 400)

        if not payment_method_enum:
            raise CheckoutFlowError("payment_method is required", 400)

        address = Address.query.filter_by(
            uuid=address_uuid,
            user_id=current_customer.id,
            is_active=True,
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
                latest_message=result["tracking_message"],
            )

            return success_response(
                "Order placed successfully! Cash on Delivery selected.",
                status_code=201,
                require_otp=False,
                order_uuid=order.uuid,
                data={
                    "order_status": order.status.name,
                    "transaction_id": result["transaction_id"],
                    "invoice_number": result["invoice"].invoice_number,
                    "payment_method": payment_method_enum.value,
                    "payment_status": result["payment"].status.name,
                },
                email_status="Order confirmation email sent successfully." if email_sent else "Order placed, but the confirmation email could not be sent.",
            )

        _, otp_code = _generate_payment_otp(current_customer, order)
        db.session.commit()

        email_sent = send_payment_otp_email(
            customer_email=current_customer.email,
            customer_name=current_customer.username or 'Customer',
            order_uuid=order.uuid,
            otp_code=otp_code,
            payment_method=payment_method_enum.value,
            expires_in_minutes=PAYMENT_OTP_EXPIRY_MINUTES,
        )

        return success_response(
            "OTP sent" if email_sent else "OTP generated, but the email could not be delivered. Please try again.",
            status_code=201,
            require_otp=True,
            order_uuid=order.uuid,
            payment_method=payment_method_enum.value,
            expires_in_minutes=PAYMENT_OTP_EXPIRY_MINUTES,
            email_status="sent" if email_sent else "failed",
        )
    except CheckoutFlowError as exc:
        db.session.rollback()
        return error_response(exc.message, status_code=exc.status_code)
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("Checkout initiation failed")
        return error_response("Checkout initiation failed", status_code=500)


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
            is_active=True,
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
            is_active=True,
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
            latest_message=result["tracking_message"],
        )

        return success_response(
            "Payment verified successfully. Your order is now processing.",
            require_otp=False,
            order_uuid=order.uuid,
            data={
                "order_status": order.status.name,
                "transaction_id": result["transaction_id"],
                "invoice_number": result["invoice"].invoice_number,
                "payment_method": order.payment_method.value,
                "payment_status": result["payment"].status.name,
            },
            email_status="Order confirmation email sent successfully." if email_sent else "Payment completed, but the confirmation email could not be sent.",
        )
    except CheckoutFlowError as exc:
        db.session.rollback()
        return error_response(exc.message, status_code=exc.status_code)
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("OTP verification failed")
        return error_response("OTP verification failed", status_code=500)


def _build_tracking_payload(order):
    tracking_entries = sorted(
        list(order.tracking or []),
        key=lambda entry: entry.updated_at or entry.created_at or order.created_at,
    )
    tracking_by_status = {
        entry.status.name: entry
        for entry in tracking_entries
    }

    stage_blueprint = [
        {
            "key": "pending",
            "title": "Order placed",
            "default_message": "Your order has been placed successfully and is waiting for the next update.",
        },
        {
            "key": "processing",
            "title": "Processing",
            "default_message": "Payment is confirmed and your order is being prepared for dispatch.",
        },
        {
            "key": "shipped",
            "title": "Shipped",
            "default_message": "Your package has left the warehouse and is on the way.",
        },
        {
            "key": "delivered",
            "title": "Delivered",
            "default_message": "The package has reached the delivery address.",
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
            "timestamp": _format_timestamp(timestamp),
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
            "timestamp": _format_timestamp(
                (cancel_entry.updated_at or cancel_entry.created_at) if cancel_entry else (order.updated_at or order.created_at)
            ),
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
            "line_total": item.price_at_purchase * item.quantity,
        })

    latest_tracking = tracking_entries[-1] if tracking_entries else None
    latest_update = {
        "status": latest_tracking.status.name if latest_tracking else current_status,
        "message": latest_tracking.message if latest_tracking and latest_tracking.message else timeline[-1]["message"],
        "timestamp": _format_timestamp(
            (latest_tracking.updated_at or latest_tracking.created_at) if latest_tracking else (order.updated_at or order.created_at)
        ),
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
        "estimated_delivery": _format_timestamp(estimated_delivery),
        "latest_update": latest_update,
        "total_amount": order.total_amount,
        "created_at": _format_timestamp(order.created_at),
        "updated_at": _format_timestamp(order.updated_at),
        "shipping_address": shipping_address,
        "items": items,
        "summary": {
            "item_count": len(items),
            "total_amount": order.total_amount,
            "payment_method": order.payment.payment_method.value if order.payment else (order.payment_method.value if order.payment_method else None),
            "payment_status": order.payment.status.value if order.payment else None,
        },
        "tracking_history": timeline,
        "timeline": timeline,
    }


@user_bp.route('/profile', methods=['GET'])
@jwt_required()
def get_profile():
    user_uuid = get_jwt_identity()
    user = User.query.filter_by(uuid=user_uuid).first()

    if not user:
        return error_response("User not found", status_code=404)

    addresses = []
    wishlist_count = 0

    if user.role.role_name == 'customer':
        addresses = [{
            "uuid": address.uuid,
            "full_name": address.full_name,
            "phone_number": address.phone_number,
            "street": address.street,
            "city": address.city,
            "state": address.state,
            "pincode": address.pincode,
            "is_default": address.is_default,
        } for address in user.addresses if address.is_active]

        wishlist_count = Wishlist.query.filter_by(
            user_id=user.id,
            is_active=True,
        ).count()

    return success_response(
        "Welcome to your protected profile!",
        user={
            "uuid": user.uuid,
            "username": user.username,
            "email": user.email,
            "phone": user.phone,
            "role": user.role.role_name,
            "is_active": user.is_active,
            "is_verified": user.is_verified,
            "created_at": _format_timestamp(user.created_at),
            "addresses": addresses,
            "wishlist_count": wishlist_count,
            "offer_summary": _serialize_coupon_summary(),
        },
    )


@user_bp.route('/products', methods=['GET'])
def get_public_products():
    products = Product.query.join(User, Product.seller_id == User.id).filter(
        Product.is_active.is_(True),
        User.is_active.is_(True),
    ).order_by(Product.created_at.desc()).all()

    result = [_serialize_product_summary(product) for product in products]

    return success_response(
        "Products loaded successfully.",
        total_products=len(result),
        offers_summary=_serialize_coupon_summary(),
        products=result,
    )


@user_bp.route('/product/<product_uuid>', methods=['GET'])
def get_product_detail(product_uuid):
    product = Product.query.join(User, Product.seller_id == User.id).filter(
        Product.uuid == product_uuid,
        Product.is_active.is_(True),
        User.is_active.is_(True),
    ).first()

    if not product:
        return error_response("Product not found or inactive", status_code=404)

    return success_response("Product loaded successfully.", product=_serialize_product_detail(product))


@user_bp.route('/wishlist', methods=['GET'])
@customer_required(inject_user=True, kwarg_name='current_customer')
def get_wishlist(current_customer):
    wishlist_entries = Wishlist.query.filter_by(
        user_id=current_customer.id,
        is_active=True,
    ).order_by(Wishlist.updated_at.desc(), Wishlist.created_at.desc()).all()

    items = []
    for entry in wishlist_entries:
        product = Product.query.filter_by(id=entry.product_id, is_active=True).first()
        if not product:
            continue

        product_summary = _serialize_product_summary(product)
        product_summary["wishlist_uuid"] = entry.uuid
        items.append(product_summary)

    return success_response("Wishlist loaded successfully.", total_items=len(items), items=items)


@user_bp.route('/wishlist', methods=['POST'])
@customer_required(inject_user=True, kwarg_name='current_customer')
def update_wishlist(current_customer):
    data = request.get_json() or {}
    product_uuid = str(data.get('product_uuid') or '').strip()
    saved = data.get('saved')

    if not product_uuid:
        return error_response("product_uuid is required", status_code=400)

    product = Product.query.filter_by(uuid=product_uuid, is_active=True).first()
    if not product:
        return error_response("Product not found or inactive", status_code=404)

    wishlist_entry = Wishlist.query.filter_by(
        user_id=current_customer.id,
        product_id=product.id,
    ).order_by(Wishlist.created_at.desc()).first()

    if saved is None:
        next_state = not bool(wishlist_entry and wishlist_entry.is_active)
    else:
        next_state = bool(saved)

    try:
        if wishlist_entry:
            wishlist_entry.is_active = next_state
            wishlist_entry.updated_by = current_customer.id
        elif next_state:
            wishlist_entry = Wishlist(
                user_id=current_customer.id,
                product_id=product.id,
                created_by=current_customer.id,
                updated_by=current_customer.id,
                is_active=True,
            )
            db.session.add(wishlist_entry)

        db.session.commit()

        return success_response(
            "Saved to wishlist." if next_state else "Removed from wishlist.",
            saved=next_state,
            product_uuid=product.uuid,
            wishlist_uuid=wishlist_entry.uuid if wishlist_entry else None,
        )
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("Failed to update wishlist")
        return error_response("Failed to update wishlist", status_code=500)


@user_bp.route('/cart', methods=['POST'])
@customer_required(inject_user=True, kwarg_name='current_customer')
def add_to_cart(current_customer):
    data = request.get_json() or {}
    product_uuid = str(data.get('product_uuid') or '').strip()

    try:
        quantity = int(data.get('quantity', 1))
    except (TypeError, ValueError):
        return error_response("Quantity must be a valid number", status_code=400)

    if quantity < 1:
        return error_response("Quantity must be at least 1", status_code=400)

    if not product_uuid:
        return error_response("Product UUID is required", status_code=400)

    product = Product.query.filter_by(uuid=product_uuid, is_active=True).first()
    if not product:
        return error_response("Product not found or inactive", status_code=404)

    if product.stock < quantity:
        return error_response(f"Only {product.stock} items left in stock", status_code=400)

    try:
        existing_cart_item = CartItem.query.filter_by(
            user_id=current_customer.id,
            product_id=product.id,
            is_active=True,
        ).first()

        if existing_cart_item:
            new_quantity = existing_cart_item.quantity + quantity
            if new_quantity > product.stock:
                return error_response("Cannot add more. Exceeds available stock.", status_code=400)

            existing_cart_item.quantity = new_quantity
            existing_cart_item.updated_by = current_customer.id
            message = "Cart item quantity updated"
        else:
            db.session.add(CartItem(
                user_id=current_customer.id,
                product_id=product.id,
                quantity=quantity,
                created_by=current_customer.id,
                updated_by=current_customer.id,
                is_active=True,
            ))
            message = "Product added to cart"

        db.session.commit()
        return success_response(message)
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("Failed to add to cart")
        return error_response("Failed to add to cart", status_code=500)


@user_bp.route('/cart', methods=['GET'])
@customer_required(inject_user=True, kwarg_name='current_customer')
def view_cart(current_customer):
    cart_items = CartItem.query.filter_by(
        user_id=current_customer.id,
        is_active=True,
    ).all()

    result = []
    cart_total = 0.0

    for item in cart_items:
        payload = _serialize_cart_item(item)
        if not payload:
            continue

        cart_total += payload["item_total"]
        result.append(payload)

    return success_response("Cart loaded successfully.", cart_total=cart_total, items=result)


@user_bp.route('/cart/<cart_item_uuid>', methods=['PATCH'])
@customer_required(inject_user=True, kwarg_name='current_customer')
def update_cart_item(current_customer, cart_item_uuid):
    data = request.get_json() or {}

    try:
        quantity = int(data.get('quantity', 0))
    except (TypeError, ValueError):
        return error_response("Quantity must be a valid number", status_code=400)

    if quantity < 1:
        return error_response("Quantity must be at least 1", status_code=400)

    cart_item = CartItem.query.filter_by(
        uuid=cart_item_uuid,
        user_id=current_customer.id,
        is_active=True,
    ).first()

    if not cart_item:
        return error_response("Cart item not found", status_code=404)

    if not cart_item.product or not cart_item.product.is_active:
        return error_response("Product not found or inactive", status_code=404)

    if cart_item.product.stock < quantity:
        return error_response(f"Only {cart_item.product.stock} items left in stock", status_code=400)

    try:
        cart_item.quantity = quantity
        cart_item.updated_by = current_customer.id
        db.session.commit()
        return success_response("Cart item updated successfully")
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("Failed to update cart item")
        return error_response("Failed to update cart item", status_code=500)


@user_bp.route('/cart/<cart_item_uuid>', methods=['DELETE'])
@customer_required(inject_user=True, kwarg_name='current_customer')
def remove_cart_item(current_customer, cart_item_uuid):
    cart_item = CartItem.query.filter_by(
        uuid=cart_item_uuid,
        user_id=current_customer.id,
        is_active=True,
    ).first()

    if not cart_item:
        return error_response("Cart item not found", status_code=404)

    try:
        cart_item.is_active = False
        cart_item.updated_by = current_customer.id
        db.session.commit()
        return success_response("Cart item removed successfully")
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("Failed to remove cart item")
        return error_response("Failed to remove cart item", status_code=500)


@user_bp.route('/address', methods=['POST'])
@customer_required(inject_user=True, kwarg_name='current_customer')
def add_address(current_customer):
    data = request.get_json() or {}
    required = ['full_name', 'phone_number', 'street', 'city', 'state', 'pincode']

    if not all(str(data.get(field, '')).strip() for field in required):
        return error_response("Missing address details. Required: full_name, phone_number, street, city, state, pincode", status_code=400)

    is_default = bool(data.get('is_default'))
    has_existing_addresses = Address.query.filter_by(user_id=current_customer.id, is_active=True).count() > 0
    should_set_default = is_default or not has_existing_addresses

    try:
        if should_set_default:
            Address.query.filter_by(user_id=current_customer.id, is_active=True).update({
                "is_default": False,
                "updated_by": current_customer.id,
            }, synchronize_session=False)

        new_address = Address(
            user_id=current_customer.id,
            full_name=str(data.get('full_name')).strip(),
            phone_number=str(data.get('phone_number')).strip(),
            street=str(data.get('street')).strip(),
            city=str(data.get('city')).strip(),
            state=str(data.get('state')).strip(),
            pincode=str(data.get('pincode')).strip(),
            is_default=should_set_default,
            created_by=current_customer.id,
            updated_by=current_customer.id,
            is_active=True,
        )
        db.session.add(new_address)
        db.session.commit()

        return success_response("Address saved successfully", status_code=201, address_uuid=new_address.uuid)
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("Failed to save address")
        return error_response("Failed to save address", status_code=500)


@user_bp.route('/address/<address_uuid>', methods=['PATCH'])
@customer_required(inject_user=True, kwarg_name='current_customer')
def update_address(current_customer, address_uuid):
    data = request.get_json() or {}
    required = ['full_name', 'phone_number', 'street', 'city', 'state', 'pincode']

    if not all(str(data.get(field, '')).strip() for field in required):
        return error_response("All address fields are required", status_code=400)

    address = Address.query.filter_by(
        uuid=address_uuid,
        user_id=current_customer.id,
        is_active=True,
    ).first()

    if not address:
        return error_response("Address not found", status_code=404)

    try:
        should_set_default = bool(data.get('is_default')) or address.is_default
        if should_set_default:
            Address.query.filter(
                Address.user_id == current_customer.id,
                Address.uuid != address_uuid,
                Address.is_active.is_(True),
            ).update({
                "is_default": False,
                "updated_by": current_customer.id,
            }, synchronize_session=False)

        address.full_name = str(data.get('full_name')).strip()
        address.phone_number = str(data.get('phone_number')).strip()
        address.street = str(data.get('street')).strip()
        address.city = str(data.get('city')).strip()
        address.state = str(data.get('state')).strip()
        address.pincode = str(data.get('pincode')).strip()
        address.is_default = should_set_default
        address.updated_by = current_customer.id

        db.session.commit()

        return success_response("Address updated successfully", address_uuid=address.uuid)
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("Failed to update address")
        return error_response("Failed to update address", status_code=500)


@user_bp.route('/address/<address_uuid>', methods=['DELETE'])
@customer_required(inject_user=True, kwarg_name='current_customer')
def delete_address(current_customer, address_uuid):
    address = Address.query.filter_by(
        uuid=address_uuid,
        user_id=current_customer.id,
        is_active=True,
    ).first()

    if not address:
        return error_response("Address not found", status_code=404)

    try:
        was_default = address.is_default
        address.is_active = False
        address.is_default = False
        address.updated_by = current_customer.id

        if was_default:
            next_address = Address.query.filter(
                Address.user_id == current_customer.id,
                Address.uuid != address_uuid,
                Address.is_active.is_(True),
            ).order_by(Address.created_at.asc()).first()

            if next_address:
                next_address.is_default = True
                next_address.updated_by = current_customer.id

        db.session.commit()

        return success_response("Address deleted successfully")
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("Failed to delete address")
        return error_response("Failed to delete address", status_code=500)


@user_bp.route('/payment/verify', methods=['POST'])
@customer_required(inject_user=True, kwarg_name='current_customer')
def verify_payment(current_customer):
    return _verify_payment_flow(current_customer)


@user_bp.route('/checkout/initiate', methods=['POST'])
@customer_required(inject_user=True, kwarg_name='current_customer')
def initiate_checkout(current_customer):
    return _checkout_customer_order(current_customer)


@user_bp.route('/checkout/verify', methods=['POST'])
@customer_required(inject_user=True, kwarg_name='current_customer')
def verify_checkout(current_customer):
    return _verify_payment_flow(current_customer)


@user_bp.route('/checkout', methods=['POST'])
@customer_required(inject_user=True, kwarg_name='current_customer')
def checkout(current_customer):
    return _checkout_customer_order(current_customer)


@user_bp.route('/payment', methods=['POST'])
@customer_required(inject_user=True, kwarg_name='current_customer')
def process_payment(current_customer):
    return _checkout_customer_order(current_customer)


@user_bp.route('/order/<order_uuid>/track', methods=['GET'])
@customer_required(inject_user=True, kwarg_name='current_customer')
def track_order(current_customer, order_uuid):
    order = Order.query.filter_by(uuid=order_uuid, user_id=current_customer.id).first()

    if not order:
        return error_response("Order not found or access denied", status_code=404)

    return success_response("Order tracking loaded successfully.", **_build_tracking_payload(order))


@user_bp.route('/orders', methods=['GET'])
@customer_required(inject_user=True, kwarg_name='current_customer')
def get_user_orders(current_customer):
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
                "line_total": item.price_at_purchase * item.quantity,
            })

        result.append({
            "order_uuid": order.uuid,
            "order_id": order.id,
            "status": order.status.name,
            "total_amount": order.total_amount,
            "created_at": _format_timestamp(order.created_at),
            "payment_method": order.payment.payment_method.value if order.payment else (order.payment_method.value if order.payment_method else None),
            "payment_status": order.payment.status.value if order.payment else None,
            "items": order_items,
            "item_count": len(order_items),
        })

    return success_response("Orders loaded successfully.", total_orders=len(result), orders=result)


#++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
#++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++


# # File: shop/user/routes.py (add to your existing routes3.py)
# from shop.utils.email_service import send_profile_otp_email
# from shop.extensions import bcrypt
# import random

# # Temporary storage for pending updates
# PENDING_PROFILE_UPDATES = {}

# @user_bp.route('/profile/update/request-otp', methods=['POST'])
# @jwt_required()
# def request_profile_update_otp():
#     user_uuid = get_jwt_identity()
#     user = User.query.filter_by(uuid=user_uuid, is_active=True).first()
    
#     if not user:
#         return error_response("User not found", status_code=404)

#     data = request.get_json() or {}
#     new_name = str(data.get('name') or '').strip()
#     new_email = str(data.get('email') or '').strip()
#     new_password = data.get('password')

#     # Ensure there are actually changes requested
#     if not new_name and not new_email and not new_password:
#         return error_response("No changes requested.", status_code=400)

#     # Email uniqueness check
#     if new_email and new_email != user.email:
#         existing_user = User.query.filter_by(email=new_email).first()
#         if existing_user:
#             return error_response("This email is already registered to another account.", status_code=409)

#     # 1. Generate OTP using existing OTP model logic
#     otp_code = f"{random.randint(0, 999999):06d}"
#     otp_entry = Otp(
#         user_id=user.id,
#         order_id=None, # Crucial: NULL order_id indicates it's a profile action
#         otp_code=otp_code,
#         action=OTPAction.verification,
#         is_used=False,
#         expires_at=datetime.utcnow() + timedelta(minutes=10),
#         created_by=user.id,
#         updated_by=user.id,
#         is_active=True
#     )
#     db.session.add(otp_entry)
#     db.session.commit()

#     # 2. Store pending data temporarily mapping to user.id
#     PENDING_PROFILE_UPDATES[user.id] = {
#         'username': new_name if new_name else None,
#         'email': new_email if new_email and new_email != user.email else None,
#         'password': new_password if new_password else None
#     }

#     # 3. Send OTP to CURRENT email
#     email_sent = send_profile_otp_email(user.email, user.username, otp_code, expires_in_minutes=10)

#     if not email_sent:
#         return error_response("Failed to send OTP to your email. Try again.", status_code=500)

#     return success_response("OTP sent securely to your current email.", require_otp=True)


# @user_bp.route('/profile/update/verify-otp', methods=['POST'])
# @jwt_required()
# def verify_profile_update_otp():
#     user_uuid = get_jwt_identity()
#     user = User.query.filter_by(uuid=user_uuid, is_active=True).first()
#     data = request.get_json() or {}
#     otp_code = str(data.get('otp') or '').strip()

#     if not otp_code:
#         return error_response("OTP is required", status_code=400)

#     # 1. Check if OTP is valid and not expired
#     otp_entry = Otp.query.filter_by(
#         user_id=user.id,
#         otp_code=otp_code,
#         action=OTPAction.verification,
#         is_used=False,
#         is_active=True
#     ).order_by(Otp.created_at.desc()).first()

#     if not otp_entry or otp_entry.expires_at < datetime.utcnow():
#         return error_response("Invalid or expired OTP. Please request a new one.", status_code=400)

#     # 2. Get pending updates
#     pending_data = PENDING_PROFILE_UPDATES.get(user.id)
#     if not pending_data:
#         return error_response("No pending update session found. Please try again.", status_code=400)

#     # 3. Apply changes securely
#     if pending_data.get('username'):
#         user.username = pending_data['username']
#     if pending_data.get('email'):
#         user.email = pending_data['email']
#     if pending_data.get('password'):
#         user.password = bcrypt.generate_password_hash(pending_data['password']).decode('utf-8')

#     # Mark OTP as used
#     otp_entry.is_used = True
#     otp_entry.updated_by = user.id
#     user.updated_by = user.id
    
#     db.session.commit()

#     # Clear pending cache
#     PENDING_PROFILE_UPDATES.pop(user.id, None)

#     return success_response("Profile updated successfully!")
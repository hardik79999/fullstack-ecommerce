from datetime import timedelta

from flask import Blueprint, current_app, request

from shop.extensions import db
from shop.models import (
    Category,
    Order,
    OrderStatus,
    OrderTracking,
    Product,
    ProductImage,
    Role,
    SellerCategory,
    User,
)
from shop.utils.api_response import error_response, success_response
from shop.utils.decorators import admin_required
from shop.utils.email_service import send_order_status_email

admin_bp = Blueprint('admin_bp', __name__)


def _format_admin_tracking_timestamp(value):
    return value.strftime('%Y-%m-%d %H:%M:%S') if value else None


def _serialize_order_tracking_for_admin(order):
    tracking_entries = sorted(
        list(order.tracking or []),
        key=lambda entry: entry.updated_at or entry.created_at or order.created_at,
    )
    tracking_by_status = {entry.status.name: entry for entry in tracking_entries}

    stage_blueprint = [
        {'key': 'pending', 'title': 'Order placed', 'default_message': 'Order created and waiting for the next operational update.'},
        {'key': 'processing', 'title': 'Processing', 'default_message': 'Order is being packed and prepared for dispatch.'},
        {'key': 'shipped', 'title': 'Shipped', 'default_message': 'Shipment has left the warehouse and is in transit.'},
        {'key': 'delivered', 'title': 'Delivered', 'default_message': 'Shipment delivered successfully.'},
    ]

    progress_map = {
        'pending': 20,
        'processing': 50,
        'shipped': 80,
        'delivered': 100,
        'cancelled': 100,
    }

    current_status = order.status.name
    current_index = next((index for index, stage in enumerate(stage_blueprint) if stage['key'] == current_status), -1)

    timeline = []
    for index, stage in enumerate(stage_blueprint):
        tracking_entry = tracking_by_status.get(stage['key'])
        timestamp = None
        if stage['key'] == 'pending':
            timestamp = order.created_at
        elif tracking_entry:
            timestamp = tracking_entry.updated_at or tracking_entry.created_at
        elif current_status != 'cancelled' and current_index >= index:
            timestamp = order.updated_at or order.created_at

        timeline.append({
            'step_key': stage['key'],
            'title': stage['title'],
            'status': 'completed' if (current_status != 'cancelled' and current_index >= index) else ('current' if (current_status != 'cancelled' and current_index == index) else 'upcoming'),
            'completed': current_status != 'cancelled' and current_index >= index,
            'current': current_status != 'cancelled' and current_index == index,
            'message': tracking_entry.message if tracking_entry and tracking_entry.message else stage['default_message'],
            'timestamp': _format_admin_tracking_timestamp(timestamp),
        })

    if current_status == 'cancelled':
        cancel_entry = tracking_by_status.get('cancelled')
        timeline.append({
            'step_key': 'cancelled',
            'title': 'Cancelled',
            'status': 'current',
            'completed': True,
            'current': True,
            'message': cancel_entry.message if cancel_entry and cancel_entry.message else 'This order was cancelled.',
            'timestamp': _format_admin_tracking_timestamp((cancel_entry.updated_at or cancel_entry.created_at) if cancel_entry else (order.updated_at or order.created_at)),
        })

    estimated_delivery = None
    if current_status == 'pending':
        estimated_delivery = order.created_at + timedelta(days=6)
    elif current_status == 'processing':
        estimated_delivery = order.created_at + timedelta(days=4)
    elif current_status == 'shipped':
        estimated_delivery = order.created_at + timedelta(days=2)
    elif current_status == 'delivered':
        estimated_delivery = order.updated_at or order.created_at

    items = []
    for item in order.items:
        product = getattr(item, 'product', None)
        items.append({
            'item_uuid': item.uuid,
            'product_uuid': product.uuid if product else None,
            'product_name': product.name if product else f'Product #{item.product_id}',
            'quantity': item.quantity,
            'price_at_purchase': item.price_at_purchase,
            'line_total': item.price_at_purchase * item.quantity,
        })

    shipping_address = None
    if order.shipping_address:
        shipping_address = {
            'full_name': order.shipping_address.full_name,
            'phone_number': order.shipping_address.phone_number,
            'street': order.shipping_address.street,
            'city': order.shipping_address.city,
            'state': order.shipping_address.state,
            'pincode': order.shipping_address.pincode,
        }

    latest_tracking = tracking_entries[-1] if tracking_entries else None

    return {
        'order_uuid': order.uuid,
        'order_id': order.id,
        'current_status': current_status,
        'status_label': current_status.replace('_', ' ').title(),
        'progress_percent': progress_map.get(current_status, 0),
        'estimated_delivery': _format_admin_tracking_timestamp(estimated_delivery),
        'latest_update': {
            'status': latest_tracking.status.name if latest_tracking else current_status,
            'message': latest_tracking.message if latest_tracking and latest_tracking.message else timeline[-1]['message'],
            'timestamp': _format_admin_tracking_timestamp((latest_tracking.updated_at or latest_tracking.created_at) if latest_tracking else (order.updated_at or order.created_at)),
        },
        'total_amount': order.total_amount,
        'created_at': _format_admin_tracking_timestamp(order.created_at),
        'updated_at': _format_admin_tracking_timestamp(order.updated_at),
        'shipping_address': shipping_address,
        'items': items,
        'summary': {
            'item_count': len(items),
            'total_amount': order.total_amount,
            'payment_method': order.payment.payment_method.name if order.payment else None,
            'payment_status': order.payment.status.name if order.payment else None,
        },
        'tracking_history': timeline,
        'timeline': timeline,
    }


@admin_bp.route('/category', methods=['POST'])
@admin_required(inject_user=True, kwarg_name='current_admin')
def create_category(current_admin):
    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    description = (data.get('description') or '').strip()

    if not name:
        return error_response('Category name is required', status_code=400)

    existing_category = Category.query.filter_by(name=name).first()
    if existing_category:
        return error_response(f"Category '{name}' already exists", status_code=409)

    try:
        new_category = Category(
            name=name,
            description=description,
            created_by=current_admin.id,
        )
        db.session.add(new_category)
        db.session.commit()
        return success_response(
            'Category created successfully',
            status_code=201,
            category={
                'uuid': new_category.uuid,
                'name': new_category.name,
                'description': new_category.description,
                'is_active': new_category.is_active,
            },
        )
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Failed to create category')
        return error_response('Failed to create category', status_code=500)


@admin_bp.route('/categories', methods=['GET'])
def get_all_categories():
    categories = Category.query.filter_by(is_active=True).all()
    result = [{'uuid': category.uuid, 'name': category.name, 'description': category.description} for category in categories]
    return success_response('Categories loaded successfully.', total=len(result), categories=result)


@admin_bp.route('/sellers', methods=['GET'])
@admin_required()
def get_all_sellers():
    seller_role = Role.query.filter_by(role_name='seller').first()
    sellers = User.query.filter_by(role_id=seller_role.id).all() if seller_role else []
    result = [{
        'uuid': seller.uuid,
        'username': seller.username,
        'email': seller.email,
        'phone': seller.phone,
        'is_active': seller.is_active,
        'is_verified': seller.is_verified,
        'joined_at': seller.created_at,
    } for seller in sellers]
    return success_response('Sellers loaded successfully.', total_sellers=len(result), sellers=result)


@admin_bp.route('/products', methods=['GET'])
@admin_required()
def get_all_products():
    products = Product.query.filter_by(is_active=True).order_by(Product.created_at.desc()).all()
    result = []
    for product in products:
        primary_image = ProductImage.query.filter_by(
            product_id=product.id,
            is_primary=True,
            is_active=True,
        ).first()
        result.append({
            'uuid': product.uuid,
            'name': product.name,
            'description': product.description,
            'price': float(product.price),
            'stock': product.stock,
            'category_name': product.category.name if product.category else 'Unknown',
            'category_uuid': product.category.uuid if product.category else None,
            'seller_username': product.seller_user.username if product.seller_user else 'Unknown',
            'seller_email': product.seller_user.email if product.seller_user else None,
            'primary_image': primary_image.image_url if primary_image else None,
            'created_at': product.created_at.strftime('%Y-%m-%d %H:%M:%S') if product.created_at else None,
            'updated_at': product.updated_at.strftime('%Y-%m-%d %H:%M:%S') if product.updated_at else None,
        })
    return success_response('Products loaded successfully.', total_products=len(result), products=result)


@admin_bp.route('/seller/<seller_uuid>/status', methods=['PUT'])
@admin_required()
def toggle_seller_status(seller_uuid):
    seller = User.query.filter_by(uuid=seller_uuid).first()
    if not seller or seller.role.role_name != 'seller':
        return error_response('Seller not found', status_code=404)

    seller.is_active = not seller.is_active
    db.session.commit()
    action = 'Activated' if seller.is_active else 'Deactivated'
    return success_response(
        f"Seller '{seller.username}' has been {action} successfully.",
        current_status='Active' if seller.is_active else 'Deactive',
    )


@admin_bp.route('/order/<order_uuid>/status', methods=['PUT'])
@admin_required(inject_user=True, kwarg_name='current_admin')
def update_order_status(current_admin, order_uuid):
    data = request.get_json() or {}
    new_status_str = (data.get('status') or '').strip()
    message = (data.get('message') or '').strip()
    if not new_status_str:
        return error_response('Status is required', status_code=400)

    order = Order.query.filter_by(uuid=order_uuid).first()
    if not order:
        return error_response('Order not found', status_code=404)

    try:
        new_status = OrderStatus[new_status_str.lower()]
    except KeyError:
        valid_statuses = [entry.name for entry in OrderStatus]
        return error_response(f"Invalid status. Must be one of: {valid_statuses}", status_code=400)

    try:
        order.status = new_status
        order.updated_by = current_admin.id
        db.session.add(OrderTracking(
            order_id=order.id,
            status=new_status,
            message=message,
            created_by=current_admin.id,
            updated_by=current_admin.id,
            is_active=True,
        ))
        db.session.commit()

        order_items = [{
            'product_name': item.product.name if getattr(item, 'product', None) else f'Product #{item.product_id}',
            'quantity': item.quantity,
            'line_total': float(item.price_at_purchase) * item.quantity,
        } for item in order.items]

        email_sent = False
        if order.customer and order.customer.email:
            email_sent = send_order_status_email(
                customer_email=order.customer.email,
                customer_name=order.customer.username or 'Customer',
                order_uuid=order.uuid,
                order_status=new_status.name,
                total_amount=order.total_amount,
                items=order_items,
                latest_message=message or f'Your order status is now {new_status.name.upper()}.',
            )

        return success_response(
            f'Order status updated to {new_status.name}',
            tracking_message=message,
            email_status='Customer notification email sent successfully.' if email_sent else 'Order updated, but customer email notification could not be sent.',
        )
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Failed to update order status for %s', order_uuid)
        return error_response('Failed to update status', status_code=500)


@admin_bp.route('/category-requests', methods=['GET'])
@admin_required()
def get_all_category_requests():
    pending_requests = SellerCategory.query.filter_by(is_approved=False, is_active=True).all()
    result = []
    for request_entry in pending_requests:
        seller = User.query.get(request_entry.seller_id)
        category = Category.query.get(request_entry.category_id)
        result.append({
            'request_uuid': request_entry.uuid,
            'seller_name': seller.username if seller else 'Unknown',
            'category_name': category.name if category else 'Unknown',
            'requested_at': request_entry.created_at.strftime('%Y-%m-%d %H:%M:%S') if request_entry.created_at else None,
        })
    return success_response('Category requests loaded successfully.', total_pending=len(result), requests=result)


@admin_bp.route('/category-request/<request_uuid>/approve', methods=['PUT'])
@admin_required(inject_user=True, kwarg_name='current_admin')
def approve_seller_category(current_admin, request_uuid):
    category_request = SellerCategory.query.filter_by(uuid=request_uuid).first()
    if not category_request:
        return error_response('Request not found', status_code=404)
    if category_request.is_approved:
        return error_response('This request is already approved.', status_code=400)

    try:
        category_request.is_approved = True
        category_request.updated_by = current_admin.id
        db.session.commit()

        seller = User.query.get(category_request.seller_id)
        category = Category.query.get(category_request.category_id)
        return success_response(
            f"Success! Seller '{seller.username if seller else 'Unknown'}' is now approved to sell in '{category.name if category else 'Unknown'}'."
        )
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Failed to approve category request %s', request_uuid)
        return error_response('Failed to approve request', status_code=500)


@admin_bp.route('/category-request/<request_uuid>/decline', methods=['PUT'])
@admin_required(inject_user=True, kwarg_name='current_admin')
def decline_seller_category(current_admin, request_uuid):
    category_request = SellerCategory.query.filter_by(uuid=request_uuid).first()
    if not category_request:
        return error_response('Request not found', status_code=404)
    if category_request.is_approved:
        return error_response('This request is already approved. Cannot decline.', status_code=400)

    try:
        category_request.is_active = False
        category_request.updated_by = current_admin.id
        db.session.commit()

        seller = User.query.get(category_request.seller_id)
        category = Category.query.get(category_request.category_id)
        return success_response(
            f"Request from '{seller.username if seller else 'Unknown'}' for '{category.name if category else 'Unknown'}' has been declined."
        )
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Failed to decline category request %s', request_uuid)
        return error_response('Failed to decline request', status_code=500)


@admin_bp.route('/orders', methods=['GET'])
@admin_required()
def get_all_orders():
    orders = Order.query.order_by(Order.created_at.desc()).all()
    result = []
    for order in orders:
        customer = User.query.get(order.user_id)
        order_items = []
        for item in order.items:
            product = getattr(item, 'product', None)
            order_items.append({
                'product_name': product.name if product else f'Product #{item.product_id}',
                'product_price': float(product.price) if product else float(item.price_at_purchase),
                'product_uuid': product.uuid if product else None,
                'quantity': item.quantity,
                'price_at_purchase': item.price_at_purchase,
            })

        result.append({
            'order_uuid': order.uuid,
            'order_id': order.id,
            'customer_username': customer.username if customer else 'Unknown',
            'customer_email': customer.email if customer else 'Unknown',
            'status': order.status.name,
            'total_amount': order.total_amount,
            'created_at': order.created_at.strftime('%Y-%m-%d %H:%M:%S') if order.created_at else None,
            'items': order_items,
            'item_count': len(order_items),
        })

    return success_response('Orders loaded successfully.', total_orders=len(result), orders=result)


@admin_bp.route('/order/<order_uuid>/track', methods=['GET'])
@admin_required()
def admin_track_order(order_uuid):
    order = Order.query.filter_by(uuid=order_uuid).first()
    if not order:
        return error_response('Order not found', status_code=404)

    return success_response('Order tracking loaded successfully.', **_serialize_order_tracking_for_admin(order))

from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from shop.models import User
from shop.extensions import db

from shop.models import Product, ProductImage, Category

user_bp = Blueprint('user', __name__)

@user_bp.route('/profile', methods=['GET'])
@jwt_required()
def get_profile():

    uuid = get_jwt_identity()

    
    user = User.query.filter_by(uuid=uuid).first()

    if not user:
        return jsonify({"error": "User not found"}), 404

    return jsonify({
        "message": "Welcome to your protected profile!",
        "user_data": {
            "uuid": user.uuid,
            "username": user.username,
            "email": user.email,
            "phone": user.phone,
            "role": user.role.role_name,
            "is_active": user.is_active,
            "is_verified": user.is_verified
        }
    }), 200




@user_bp.route('/products', methods=['GET'])
def get_public_products():
    """Public API to view all active products"""
    # Sirf wahi products dikhao jo active hain
    products = Product.query.filter_by(is_active=True).all()
    
    result = []
    for prod in products:
        # Get the primary image for the product thumbnail
        primary_image = ProductImage.query.filter_by(product_id=prod.id, is_primary=True).first()
        img_url = primary_image.image_url if primary_image else None
        
        result.append({
            "uuid": prod.uuid,
            "name": prod.name,
            "description": prod.description,
            "price": prod.price,
            "category": prod.category.name,
            "seller": prod.seller_user.username, # Accessing seller's username
            "primary_image": img_url,
            "stock": prod.stock
        })
        
    return jsonify({
        "total_products": len(result),
        "products": result
    }), 200





#================================================================================================================
#================================================================================================================

from flask import request
from shop.models import CartItem

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
#================================================================================================================

@user_bp.route('/cart', methods=['POST'])
@customer_required
def add_to_cart(current_customer):
    data = request.get_json()
    product_uuid = data.get('product_uuid')
    quantity = data.get('quantity', 1)
    
    if not product_uuid:
        return jsonify({"error": "Product UUID is required"}), 400
        
    # Find the product
    product = Product.query.filter_by(uuid=product_uuid, is_active=True).first()
    if not product:
        return jsonify({"error": "Product not found or inactive"}), 404
        
    # Check if enough stock is available
    if product.stock < quantity:
         return jsonify({"error": f"Only {product.stock} items left in stock"}), 400

    try:
        # Check if item is already in cart
        existing_cart_item = CartItem.query.filter_by(
            user_id=current_customer.id, 
            product_id=product.id
        ).first()
        
        if existing_cart_item:
            # If exists, update quantity
            new_quantity = existing_cart_item.quantity + quantity
            if new_quantity > product.stock:
                 return jsonify({"error": "Cannot add more. Exceeds available stock."}), 400
            existing_cart_item.quantity = new_quantity
            message = "Cart item quantity updated"
        else:
            # If new, create cart item
            new_cart_item = CartItem(
                user_id=current_customer.id,
                product_id=product.id,
                quantity=quantity
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
    cart_items = CartItem.query.filter_by(user_id=current_customer.id).all()
    
    result = []
    cart_total = 0
    
    for item in cart_items:
        # Get primary image for cart display
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


#================================================================================================================
#================================================================================================================


from shop.models import Address

@user_bp.route('/address', methods=['POST'])
@customer_required
def add_address(current_customer):
    data = request.get_json()
    
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


#+++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
#+++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

from shop.models import Order, OrderItem

@user_bp.route('/checkout', methods=['POST'])
@customer_required
def checkout(current_customer):
    data = request.get_json()
    address_uuid = data.get('address_uuid')
    
    # 1. Check Address
    address = Address.query.filter_by(uuid=address_uuid, user_id=current_customer.id).first()
    if not address:
        return jsonify({"error": "Invalid delivery address"}), 404
        
    # 2. Get Cart Items
    cart_items = CartItem.query.filter_by(user_id=current_customer.id).all()
    if not cart_items:
        return jsonify({"error": "Cart is empty"}), 400
        
    total_amount = 0
    order_items_to_create = []

    try:
        # 3. Validate Stock & Calculate Total
        for item in cart_items:
            if item.product.stock < item.quantity:
                return jsonify({"error": f"Product {item.product.name} out of stock!"}), 400
            
            item_total = item.product.price * item.quantity
            total_amount += item_total
            
            # Prepare OrderItem
            order_items_to_create.append({
                "product_id": item.product.id,
                "quantity": item.quantity,
                "price_at_order": item.product.price
            })

        # 4. Create Main Order
        new_order = Order(
            user_id=current_customer.id,
            address_id=address.id,
            total_amount=total_amount,
            status='pending' # Initial status
        )
        db.session.add(new_order)
        db.session.flush() # Get order ID

        # 5. Create OrderItems & Update Stock
        for oi in order_items_to_create:
            # Add to OrderItem table
            order_item = OrderItem(
                order_id=new_order.id,
                product_id=oi['product_id'],
                quantity=oi['quantity'],
                price_at_order=oi['price_at_order']
            )
            db.session.add(order_item)
            
            # Reduce Stock from Product table
            prod = Product.query.get(oi['product_id'])
            prod.stock -= oi['quantity']

        # 6. Clear Cart
        CartItem.query.filter_by(user_id=current_customer.id).delete()
        
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
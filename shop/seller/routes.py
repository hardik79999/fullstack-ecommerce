import os
import uuid
import json
from werkzeug.utils import secure_filename
from flask import Blueprint, request, jsonify, current_app
from shop.models import Product, ProductImage, User, Category, Specification, SellerCategory, Role
from shop.extensions import db
from flask_jwt_extended import jwt_required, get_jwt_identity

seller_bp = Blueprint('seller_bp', __name__)

# ==============================================================================
# 🛡️ HELPER: Check if user is Seller
# ==============================================================================
def seller_required(fn):
    @jwt_required()
    def wrapper(*args, **kwargs):
        current_user_uuid = get_jwt_identity()
        user = User.query.filter_by(uuid=current_user_uuid, is_active=True).first()
        
        if not user or user.role.role_name != 'seller':
            return jsonify({"error": "Unauthorized access. Seller privileges required."}), 403
            
        return fn(current_seller=user, *args, **kwargs)
    
    wrapper.__name__ = fn.__name__
    return wrapper

# ==============================================================================
# 📁 HELPER: Allowed File Extension Check
# ==============================================================================
def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in current_app.config['ALLOWED_EXTENSIONS']

# ==============================================================================
# 📦 PRODUCT APIs (Seller Only)
# ==============================================================================

@seller_bp.route('/product', methods=['POST'])
@seller_required
def create_product(current_seller):
    name = request.form.get('name')
    description = request.form.get('description')
    price = request.form.get('price')
    stock = request.form.get('stock', 0)
    category_uuid = request.form.get('category_uuid')
    
    # 👈 NAYA: Specifications ko form se get karna
    specifications_data = request.form.get('specifications') 
    
    # 1. Basic Validation
    if not all([name, description, price, category_uuid]):
        return jsonify({"error": "Missing required text fields"}), 400
        
    category = Category.query.filter_by(uuid=category_uuid, is_active=True).first()
    if not category:
        return jsonify({"error": "Invalid or inactive category"}), 404
    
    # =========================================================================
    # 🛡️ GATED CATEGORY CHECK (NAYA LOGIC)
    # =========================================================================
    is_approved_seller = SellerCategory.query.filter_by(
        seller_id=current_seller.id,
        category_id=category.id,
        is_approved=True,
        is_active=True
    ).first()

    if not is_approved_seller:
        return jsonify({
            "error": "Category Approval Required",
            "message": f"Aap '{category.name}' category mein product nahi daal sakte. Pehle Admin se approval lijiye."
        }), 403

    # 3. Handle MULTIPLE File Uploads
    image_files = request.files.getlist('images')
    saved_image_urls = []

    if image_files and image_files[0].filename != '':
        upload_dir = current_app.config['UPLOAD_FOLDER']
        if not os.path.exists(upload_dir):
            os.makedirs(upload_dir)
            
        for file in image_files:
            if file and allowed_file(file.filename):
                original_filename = secure_filename(file.filename)
                unique_filename = f"{uuid.uuid4().hex}_{original_filename}"
                upload_path = os.path.join(upload_dir, unique_filename)
                file.save(upload_path)
                saved_image_urls.append(f"/static/uploads/products/{unique_filename}")

    # 4. Create Product, Images & Specs in DB Transaction
    try:
        # Step A: Create Product 
        new_product = Product(
            name=name,
            description=description,
            price=float(price),
            stock=int(stock),
            category_id=category.id,
            seller_id=current_seller.id,
            created_by=current_seller.id, 
            updated_by=current_seller.id,
            is_active=True
        )
        db.session.add(new_product)
        db.session.flush() # ID mil jayegi
        
        # Step B: Create Product Images
        for index, url in enumerate(saved_image_urls):
            is_primary = True if index == 0 else False
            new_image = ProductImage(
                product_id=new_product.id,
                image_url=url,
                is_primary=is_primary,
                created_by=current_seller.id,
                updated_by=current_seller.id,
                is_active=True
            )
            db.session.add(new_image)
            
        # ==========================================================
        # 🚀 Step C: Create Specifications (NAYA LOGIC)
        # ==========================================================
        parsed_specs = []
        if specifications_data:
            try:
                # String array ko actual Python List (dictionaries) me badlo
                spec_list = json.loads(specifications_data)
                
                for spec in spec_list:
                    new_spec = Specification(
                        product_id=new_product.id,
                        spec_key=spec.get('key'),
                        spec_value=spec.get('value'),
                        created_by=current_seller.id,
                        updated_by=current_seller.id,
                        is_active=True
                    )
                    db.session.add(new_spec)
                    parsed_specs.append({"key": new_spec.spec_key, "value": new_spec.spec_value})
            except json.JSONDecodeError:
                db.session.rollback()
                return jsonify({"error": "Invalid format for specifications. It must be a valid JSON array."}), 400
        # ==========================================================
            
        db.session.commit()
        
        return jsonify({
            "message": "Product created successfully with images and specs",
            "product": {
                "uuid": new_product.uuid,
                "name": new_product.name,
                "price": new_product.price,
                "images": saved_image_urls,
                "specifications": parsed_specs # Response me dikhane ke liye
            }
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Failed to create product", "details": str(e)}), 500

#==================================================================================================================================
#==================================================================================================================================

@seller_bp.route('/products', methods=['GET'])
@seller_required
def get_my_products(current_seller):
    products = Product.query.filter_by(seller_id=current_seller.id, is_active=True).all()
    
    result = []
    for prod in products:
        # Fetch primary image if exists
        primary_image = ProductImage.query.filter_by(product_id=prod.id, is_primary=True).first()
        img_url = primary_image.image_url if primary_image else None
        
        result.append({
            "uuid": prod.uuid,
            "name": prod.name,
            "price": prod.price,
            "stock": prod.stock,
            "category": prod.category.name,
            "primary_image": img_url
        })
        
    return jsonify({
        "total_products": len(result),
        "products": result
    }), 200



#==============================================================================================================================
#==============================================================================================================================

from shop.utils.email_service import send_category_request_email_to_admin

@seller_bp.route('/category-request', methods=['POST'])
@seller_required
def request_category_approval(current_seller):
    data = request.get_json()
    category_uuid = data.get('category_uuid')
    
    if not category_uuid:
        return jsonify({"error": "category_uuid is required"}), 400
        
    category = Category.query.filter_by(uuid=category_uuid, is_active=True).first()
    if not category:
        return jsonify({"error": "Category not found or inactive"}), 404
        
    # Only check for ACTIVE requests (not declined ones)
    existing_request = SellerCategory.query.filter_by(
        seller_id=current_seller.id, 
        category_id=category.id,
        is_active=True  # 👈 Only check active requests
    ).first()
    
    if existing_request:
        status = "Approved" if existing_request.is_approved else "Pending"
        return jsonify({"message": f"You already have a {status} request for this category. Please wait for admin approval."}), 400
        
    try:
        new_request = SellerCategory(
            seller_id=current_seller.id,
            category_id=category.id,
            is_approved=False, 
            created_by=current_seller.id,
            updated_by=current_seller.id,
            is_active=True
        )
        db.session.add(new_request)
        db.session.commit()
        
        # =====================================================================
        # 📧 EMAIL TO ADMIN LOGIC
        # =====================================================================
        try:
            # 1. Pehle Admin role ki ID nikalo
            admin_role = Role.query.filter_by(role_name='admin').first()
            
            # 2. Saare active admins nikal lo (kya pata system me 2-3 admin hon)
            active_admins = User.query.filter_by(role_id=admin_role.id, is_active=True).all()
            
            if active_admins:
                admin_emails = [admin.email for admin in active_admins]
                
                # 3. Mail bhej do
                send_category_request_email_to_admin(
                    admin_emails=admin_emails,
                    seller_name=current_seller.username,
                    category_name=category.name
                )
                print(f"Notification sent to admins: {admin_emails}")
        except Exception as mail_err:
            print(f"Admin email sending failed: {str(mail_err)}")
            # Agar mail fail bhi ho jaye, toh request cancel nahi honi chahiye
        # =====================================================================
        
        return jsonify({
            "message": f"Request to sell in '{category.name}' submitted successfully. An email notification has been sent to the Admin.",
            "request_uuid": new_request.uuid
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": "Failed to submit request", "details": str(e)}), 500


@seller_bp.route('/my-categories', methods=['GET'])
@seller_required
def get_my_categories(current_seller):
    """Get all categories with seller's approval status"""
    # Get ALL active categories from database
    all_categories = Category.query.filter_by(is_active=True).all()
    
    # Get seller's SellerCategory records to check approval status
    seller_categories = SellerCategory.query.filter_by(
        seller_id=current_seller.id,
        is_active=True
    ).all()
    
    # Create a mapping of category_id to approval status
    seller_category_map = {
        sc.category_id: {
            'is_approved': sc.is_approved,
            'request_uuid': sc.uuid
        } for sc in seller_categories
    }
    
    result = []
    for category in all_categories:
        category_data = {
            "uuid": category.uuid,
            "name": category.name,
            "description": category.description,
            "id": category.id
        }
        
        # Check seller's status for this category
        if category.id in seller_category_map:
            status_info = seller_category_map[category.id]
            if status_info['is_approved']:
                category_data['status'] = 'approved'
                category_data['request_uuid'] = status_info['request_uuid']
            else:
                category_data['status'] = 'pending'
                category_data['request_uuid'] = status_info['request_uuid']
        else:
            category_data['status'] = 'available'  # Seller hasn't requested this yet
        
        result.append(category_data)
    
    return jsonify({
        "total_categories": len(result),
        "categories": result
    }), 200
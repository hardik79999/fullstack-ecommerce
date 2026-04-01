import os
import uuid
from werkzeug.utils import secure_filename
from flask import Blueprint, request, jsonify, current_app
from shop.models import Product, ProductImage, User, Category
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
    
    # 1. Basic Validation
    if not all([name, description, price, category_uuid]):
        return jsonify({"error": "Missing required text fields (name, description, price, category_uuid)"}), 400
        
    # 2. Verify Category
    category = Category.query.filter_by(uuid=category_uuid, is_active=True).first()
    if not category:
        return jsonify({"error": "Invalid or inactive category"}), 404

    # 3. Handle MULTIPLE File Uploads
    # Dhyan de: getlist('images') use kar rahe hain, jiska matlab Postman me key ka naam 'images' hoga
    image_files = request.files.getlist('images')
    saved_image_urls = []

    # Agar koi image nahi aayi toh blank list rah jayegi, lekin agar aayi hai toh process karo
    if image_files and image_files[0].filename != '':
        upload_dir = current_app.config['UPLOAD_FOLDER']
        
        # Ensure directory exists
        if not os.path.exists(upload_dir):
            os.makedirs(upload_dir)
            
        for file in image_files:
            if file and allowed_file(file.filename):
                original_filename = secure_filename(file.filename)
                unique_filename = f"{uuid.uuid4().hex}_{original_filename}"
                upload_path = os.path.join(upload_dir, unique_filename)
                file.save(upload_path)
                
                # Append relative URL to our list
                saved_image_urls.append(f"/static/uploads/products/{unique_filename}")
            else:
                return jsonify({"error": f"Invalid file type for '{file.filename}'. Allowed: jpg, jpeg, png, webp"}), 400

    # 4. Create Product & Images in DB Transaction
    try:
        # Step A: Create Product (Ab created_by aur updated_by ke sath)
        new_product = Product(
            name=name,
            description=description,
            price=float(price),
            stock=int(stock),
            category_id=category.id,
            seller_id=current_seller.id,
            created_by=current_seller.id, # Audit field
            updated_by=current_seller.id  # Audit field
        )
        db.session.add(new_product)
        db.session.flush() # Flush to get new_product.id
        
        # Step B: Create Product Images
        for index, url in enumerate(saved_image_urls):
            # Pehli image ko primary bana denge (index 0)
            is_primary = True if index == 0 else False
            
            new_image = ProductImage(
                product_id=new_product.id,
                image_url=url,
                is_primary=is_primary,
                created_by=current_seller.id # Audit field
            )
            db.session.add(new_image)
            
        db.session.commit()
        
        return jsonify({
            "message": "Product created successfully with images",
            "product": {
                "uuid": new_product.uuid,
                "name": new_product.name,
                "price": new_product.price,
                "created_by": new_product.created_by,  # 👈 Ye add kar diya humne
                "images": saved_image_urls
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
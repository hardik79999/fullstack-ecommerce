import json
import os
import uuid

from flask import Blueprint, current_app, request
from werkzeug.utils import secure_filename

from shop.extensions import db
from shop.models import Category, Product, ProductImage, Role, SellerCategory, Specification, User
from shop.utils.api_response import error_response, success_response
from shop.utils.decorators import seller_required
from shop.utils.email_service import send_category_request_email_to_admin

seller_bp = Blueprint('seller_bp', __name__)


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in current_app.config['ALLOWED_EXTENSIONS']


def serialize_seller_product(product):
    primary_image = ProductImage.query.filter_by(
        product_id=product.id,
        is_primary=True,
        is_active=True,
    ).first()

    images = ProductImage.query.filter_by(
        product_id=product.id,
        is_active=True,
    ).order_by(ProductImage.created_at.asc()).all()

    specifications = Specification.query.filter_by(
        product_id=product.id,
        is_active=True,
    ).order_by(Specification.created_at.asc()).all()

    return {
        'uuid': product.uuid,
        'name': product.name,
        'description': product.description,
        'price': float(product.price),
        'stock': product.stock,
        'category': product.category.name,
        'category_uuid': product.category.uuid,
        'primary_image': primary_image.image_url if primary_image else None,
        'images': [image.image_url for image in images],
        'specifications': [{'key': spec.spec_key, 'value': spec.spec_value} for spec in specifications],
        'created_at': product.created_at.strftime('%Y-%m-%d %H:%M:%S') if product.created_at else None,
        'updated_at': product.updated_at.strftime('%Y-%m-%d %H:%M:%S') if product.updated_at else None,
    }


def ensure_seller_category_access(current_seller, category):
    is_approved_seller = SellerCategory.query.filter_by(
        seller_id=current_seller.id,
        category_id=category.id,
        is_approved=True,
        is_active=True,
    ).first()

    if not is_approved_seller:
        return error_response(
            f"Category approval required for '{category.name}'. Please request admin approval first.",
            status_code=403,
        )

    return None


@seller_bp.route('/product', methods=['POST'])
@seller_required(inject_user=True, kwarg_name='current_seller')
def create_product(current_seller):
    name = (request.form.get('name') or '').strip()
    description = (request.form.get('description') or '').strip()
    price = request.form.get('price')
    stock = request.form.get('stock', 0)
    category_uuid = (request.form.get('category_uuid') or '').strip()
    specifications_data = request.form.get('specifications')

    if not all([name, description, price, category_uuid]):
        return error_response('Missing required text fields', status_code=400)

    category = Category.query.filter_by(uuid=category_uuid, is_active=True).first()
    if not category:
        return error_response('Invalid or inactive category', status_code=404)

    category_access_error = ensure_seller_category_access(current_seller, category)
    if category_access_error:
        return category_access_error

    image_files = request.files.getlist('images')
    saved_image_urls = []

    if image_files and image_files[0].filename != '':
        upload_dir = current_app.config['UPLOAD_FOLDER']
        os.makedirs(upload_dir, exist_ok=True)

        for file in image_files:
            if file and allowed_file(file.filename):
                original_filename = secure_filename(file.filename)
                unique_filename = f"{uuid.uuid4().hex}_{original_filename}"
                upload_path = os.path.join(upload_dir, unique_filename)
                file.save(upload_path)
                saved_image_urls.append(f'/static/uploads/products/{unique_filename}')

    try:
        new_product = Product(
            name=name,
            description=description,
            price=float(price),
            stock=int(stock),
            category_id=category.id,
            seller_id=current_seller.id,
            created_by=current_seller.id,
            updated_by=current_seller.id,
            is_active=True,
        )
        db.session.add(new_product)
        db.session.flush()

        for index, url in enumerate(saved_image_urls):
            db.session.add(ProductImage(
                product_id=new_product.id,
                image_url=url,
                is_primary=index == 0,
                created_by=current_seller.id,
                updated_by=current_seller.id,
                is_active=True,
            ))

        parsed_specs = []
        if specifications_data:
            try:
                spec_list = json.loads(specifications_data)
            except json.JSONDecodeError:
                db.session.rollback()
                return error_response('Invalid format for specifications. It must be a valid JSON array.', status_code=400)

            for spec in spec_list:
                spec_key = (spec.get('key') or '').strip()
                spec_value = (spec.get('value') or '').strip()
                if not spec_key or not spec_value:
                    continue

                db.session.add(Specification(
                    product_id=new_product.id,
                    spec_key=spec_key,
                    spec_value=spec_value,
                    created_by=current_seller.id,
                    updated_by=current_seller.id,
                    is_active=True,
                ))
                parsed_specs.append({'key': spec_key, 'value': spec_value})

        db.session.commit()
        return success_response(
            'Product created successfully with images and specs',
            status_code=201,
            product={
                'uuid': new_product.uuid,
                'name': new_product.name,
                'price': float(new_product.price),
                'images': saved_image_urls,
                'specifications': parsed_specs,
            },
        )
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Failed to create seller product')
        return error_response('Failed to create product', status_code=500)


@seller_bp.route('/products', methods=['GET'])
@seller_required(inject_user=True, kwarg_name='current_seller')
def get_my_products(current_seller):
    products = Product.query.filter_by(
        seller_id=current_seller.id,
        is_active=True,
    ).order_by(Product.created_at.desc()).all()

    result = [serialize_seller_product(product) for product in products]
    return success_response('Seller products loaded successfully.', total_products=len(result), products=result)


@seller_bp.route('/product/<product_uuid>', methods=['PUT'])
@seller_required(inject_user=True, kwarg_name='current_seller')
def update_product(current_seller, product_uuid):
    product = Product.query.filter_by(
        uuid=product_uuid,
        seller_id=current_seller.id,
        is_active=True,
    ).first()
    if not product:
        return error_response('Product not found', status_code=404)

    is_form_request = request.content_type and 'multipart/form-data' in request.content_type
    payload = request.form if is_form_request else (request.get_json() or {})

    name = (payload.get('name') or product.name).strip()
    description = (payload.get('description') or product.description).strip()
    price = payload.get('price', product.price)
    stock = payload.get('stock', product.stock)
    category_uuid = payload.get('category_uuid', product.category.uuid if product.category else None)
    specifications_data = payload.get('specifications')

    if not all([name, description, category_uuid]):
        return error_response('Missing required fields', status_code=400)

    category = Category.query.filter_by(uuid=category_uuid, is_active=True).first()
    if not category:
        return error_response('Invalid or inactive category', status_code=404)

    category_access_error = ensure_seller_category_access(current_seller, category)
    if category_access_error:
        return category_access_error

    image_files = request.files.getlist('images') if is_form_request else []
    has_new_images = bool(image_files and image_files[0].filename)

    try:
        product.name = name
        product.description = description
        product.price = float(price)
        product.stock = int(stock)
        product.category_id = category.id
        product.updated_by = current_seller.id

        if specifications_data is not None:
            for existing_spec in product.specifications:
                if existing_spec.is_active:
                    existing_spec.is_active = False
                    existing_spec.updated_by = current_seller.id

            parsed_specs = json.loads(specifications_data) if isinstance(specifications_data, str) else specifications_data
            for spec in parsed_specs or []:
                spec_key = (spec.get('key') or '').strip()
                spec_value = (spec.get('value') or '').strip()
                if not spec_key or not spec_value:
                    continue

                db.session.add(Specification(
                    product_id=product.id,
                    spec_key=spec_key,
                    spec_value=spec_value,
                    created_by=current_seller.id,
                    updated_by=current_seller.id,
                    is_active=True,
                ))

        if has_new_images:
            upload_dir = current_app.config['UPLOAD_FOLDER']
            os.makedirs(upload_dir, exist_ok=True)

            for existing_image in product.images:
                if existing_image.is_active:
                    existing_image.is_active = False
                    existing_image.is_primary = False
                    existing_image.updated_by = current_seller.id

            for index, file in enumerate(image_files):
                if file and allowed_file(file.filename):
                    original_filename = secure_filename(file.filename)
                    unique_filename = f"{uuid.uuid4().hex}_{original_filename}"
                    upload_path = os.path.join(upload_dir, unique_filename)
                    file.save(upload_path)
                    db.session.add(ProductImage(
                        product_id=product.id,
                        image_url=f'/static/uploads/products/{unique_filename}',
                        is_primary=index == 0,
                        created_by=current_seller.id,
                        updated_by=current_seller.id,
                        is_active=True,
                    ))

        db.session.commit()
        return success_response('Product updated successfully', product=serialize_seller_product(product))
    except json.JSONDecodeError:
        db.session.rollback()
        return error_response('Invalid specifications format', status_code=400)
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Failed to update seller product %s', product_uuid)
        return error_response('Failed to update product', status_code=500)


@seller_bp.route('/product/<product_uuid>', methods=['DELETE'])
@seller_required(inject_user=True, kwarg_name='current_seller')
def delete_product(current_seller, product_uuid):
    product = Product.query.filter_by(
        uuid=product_uuid,
        seller_id=current_seller.id,
        is_active=True,
    ).first()
    if not product:
        return error_response('Product not found', status_code=404)

    try:
        product.is_active = False
        product.updated_by = current_seller.id

        for image in product.images:
            image.is_active = False
            image.updated_by = current_seller.id

        for specification in product.specifications:
            specification.is_active = False
            specification.updated_by = current_seller.id

        db.session.commit()
        return success_response(f"Product '{product.name}' deleted successfully.")
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Failed to delete seller product %s', product_uuid)
        return error_response('Failed to delete product', status_code=500)


@seller_bp.route('/category-request', methods=['POST'])
@seller_required(inject_user=True, kwarg_name='current_seller')
def request_category_approval(current_seller):
    data = request.get_json() or {}
    category_uuid = (data.get('category_uuid') or '').strip()
    if not category_uuid:
        return error_response('category_uuid is required', status_code=400)

    category = Category.query.filter_by(uuid=category_uuid, is_active=True).first()
    if not category:
        return error_response('Category not found or inactive', status_code=404)

    existing_request = SellerCategory.query.filter_by(
        seller_id=current_seller.id,
        category_id=category.id,
        is_active=True,
    ).first()
    if existing_request:
        status = 'Approved' if existing_request.is_approved else 'Pending'
        return error_response(f'You already have a {status} request for this category. Please wait for admin approval.', status_code=400)

    try:
        new_request = SellerCategory(
            seller_id=current_seller.id,
            category_id=category.id,
            is_approved=False,
            created_by=current_seller.id,
            updated_by=current_seller.id,
            is_active=True,
        )
        db.session.add(new_request)
        db.session.commit()

        email_sent = False
        try:
            admin_role = Role.query.filter_by(role_name='admin').first()
            active_admins = User.query.filter_by(role_id=admin_role.id, is_active=True).all() if admin_role else []
            if active_admins:
                admin_emails = [admin.email for admin in active_admins if admin.email]
                if admin_emails:
                    send_category_request_email_to_admin(
                        admin_emails=admin_emails,
                        seller_name=current_seller.username,
                        category_name=category.name,
                    )
                    email_sent = True
        except Exception as exc:
            current_app.logger.warning('Admin email sending failed: %s', exc)

        return success_response(
            f"Request to sell in '{category.name}' submitted successfully.",
            status_code=201,
            request_uuid=new_request.uuid,
            email_status='Admin notification email sent successfully.' if email_sent else 'Request saved, but admin email notification could not be sent.',
        )
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Failed to submit seller category request')
        return error_response('Failed to submit request', status_code=500)


@seller_bp.route('/my-categories', methods=['GET'])
@seller_required(inject_user=True, kwarg_name='current_seller')
def get_my_categories(current_seller):
    all_categories = Category.query.filter_by(is_active=True).all()
    seller_categories = SellerCategory.query.filter_by(
        seller_id=current_seller.id,
        is_active=True,
    ).all()

    seller_category_map = {
        seller_category.category_id: {
            'is_approved': seller_category.is_approved,
            'request_uuid': seller_category.uuid,
        }
        for seller_category in seller_categories
    }

    result = []
    for category in all_categories:
        category_data = {
            'uuid': category.uuid,
            'name': category.name,
            'description': category.description,
            'id': category.id,
        }

        if category.id in seller_category_map:
            status_info = seller_category_map[category.id]
            category_data['status'] = 'approved' if status_info['is_approved'] else 'pending'
            category_data['request_uuid'] = status_info['request_uuid']
        else:
            category_data['status'] = 'available'

        result.append(category_data)

    return success_response('Seller categories loaded successfully.', total_categories=len(result), categories=result)

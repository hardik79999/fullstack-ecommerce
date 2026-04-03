from datetime import timedelta

from flask import Blueprint, current_app, request
from flask_jwt_extended import create_access_token, jwt_required

from shop.extensions import bcrypt, db
from shop.models import Role, User
from shop.utils.api_response import error_response, success_response
from shop.utils.email_service import send_verification_email, verify_token

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/signup', methods=['POST'])
def signup():
    data = request.get_json() or {}
    username = (data.get('username') or '').strip()
    email = (data.get('email') or '').strip()
    password = data.get('password')
    phone = (data.get('phone') or '').strip() or None
    requested_role = (data.get('role') or 'customer').lower().strip()

    if not username or not email or not password:
        return error_response('Username, email, and password are required!', status_code=400)

    if requested_role not in {'customer', 'seller'}:
        return error_response("Invalid role. Must be 'customer' or 'seller'.", status_code=400)

    existing_user = User.query.filter((User.email == email) | (User.username == username)).first()
    if existing_user:
        return error_response('User with this email or username already exists!', status_code=409)

    user_role = Role.query.filter_by(role_name=requested_role).first()
    if not user_role:
        return error_response('System roles not initialized', status_code=500)

    hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
    new_user = User(
        username=username,
        email=email,
        password=hashed_password,
        phone=phone,
        role_id=user_role.id,
        is_active=True,
        is_verified=False,
    )
    db.session.add(new_user)
    db.session.commit()

    try:
        send_verification_email(new_user.email)
        if requested_role == 'seller':
            current_app.logger.info('New seller registered: %s (%s)', username, email)
        email_status = 'Verification email sent!'
    except Exception as exc:
        current_app.logger.warning('Verification email failed for %s: %s', email, exc)
        email_status = 'Account created, but failed to send verification email.'

    return success_response(
        f"{requested_role.capitalize()} registered successfully! Please check your email to verify.",
        status_code=201,
        email_status=email_status,
    )


@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.get_json() or {}
    email = (data.get('email') or '').strip()
    password = data.get('password')

    if not email or not password:
        return error_response('Email and password are required', status_code=400)

    user = User.query.filter_by(email=email).first()
    if not user or not bcrypt.check_password_hash(user.password, password):
        return error_response('Invalid email or password', status_code=401)

    if not user.is_active:
        return error_response('Your account has been deactivated. Contact support.', status_code=403)

    if not user.is_verified:
        return error_response('Account not verified. Please check your email for the verification link.', status_code=403)

    access_token = create_access_token(
        identity=str(user.uuid),
        additional_claims={'role': user.role.role_name},
        expires_delta=timedelta(days=1),
    )

    return success_response(
        'Login successful!',
        access_token=access_token,
        user={
            'uuid': user.uuid,
            'username': user.username,
            'email': user.email,
            'role': user.role.role_name,
        },
    )


@auth_bp.route('/verify-email/<token>', methods=['GET'])
def verify_email(token):
    email = verify_token(token)
    if not email:
        return error_response('The verification link is invalid or has expired.', status_code=400)

    user = User.query.filter_by(email=email).first()
    if not user:
        return error_response('User not found.', status_code=404)

    if user.is_verified:
        return success_response('Account is already verified. You can login now.')

    user.is_verified = True
    db.session.commit()
    return success_response('Email verified successfully! Your account is now active and you can login.')


@auth_bp.route('/logout', methods=['POST'])
@jwt_required(optional=True)
def logout():
    return success_response('Logout acknowledged. Clear the token on the client to complete sign out.')

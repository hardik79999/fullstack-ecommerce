from flask import Blueprint, request, jsonify
from shop.extensions import db, bcrypt
from shop.models import User

# Auth Blueprint create karna
auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/signup', methods=['POST'])
def signup():   
    data = request.get_json()

    # User se data lena
    username = data.get('username')
    email = data.get('email')
    password = data.get('password')
    phone = data.get('phone')

    # Basic validation: Check karna ki required fields khali toh nahi hain
    if not username or not email or not password:
        return jsonify({"error": "Username, email, and password are required!"}), 400

    # Check karna ki user pehle se exist toh nahi karta
    existing_user = User.query.filter((User.email == email) | (User.username == username)).first()
    if existing_user:
        return jsonify({"error": "User with this email or username already exists!"}), 409

    # Password ko hash (encrypt) karna
    hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')

    # Naya user create karna
    new_user = User(
        username=username,
        email=email,
        password=hashed_password,
        phone=phone
    )

    # Database me save karna
    db.session.add(new_user)
    db.session.commit()

    return jsonify({"message": "User registered successfully!"}), 201
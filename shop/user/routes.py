from flask import Blueprint, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from shop.models import User

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
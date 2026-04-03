from functools import wraps

from flask_jwt_extended import get_jwt_identity, jwt_required

from shop.models import User
from shop.utils.api_response import error_response


def role_required(*allowed_roles, inject_user=False, kwarg_name="current_user"):
    def decorator(fn):
        @wraps(fn)
        @jwt_required()
        def wrapper(*args, **kwargs):
            current_user_uuid = get_jwt_identity()
            user = User.query.filter_by(uuid=current_user_uuid, is_active=True).first()

            if not user or user.role.role_name not in allowed_roles:
                role_label = "/".join(role.title() for role in allowed_roles)
                return error_response(
                    f"Unauthorized access. {role_label} privileges required.",
                    status_code=403,
                )

            if inject_user:
                kwargs[kwarg_name] = user

            return fn(*args, **kwargs)

        return wrapper

    return decorator


def admin_required(fn=None, *, inject_user=False, kwarg_name="current_admin"):
    decorator = role_required("admin", inject_user=inject_user, kwarg_name=kwarg_name)
    return decorator(fn) if callable(fn) else decorator


def seller_required(fn=None, *, inject_user=False, kwarg_name="current_seller"):
    decorator = role_required("seller", inject_user=inject_user, kwarg_name=kwarg_name)
    return decorator(fn) if callable(fn) else decorator


def customer_required(fn=None, *, inject_user=False, kwarg_name="current_customer"):
    decorator = role_required("customer", inject_user=inject_user, kwarg_name=kwarg_name)
    return decorator(fn) if callable(fn) else decorator

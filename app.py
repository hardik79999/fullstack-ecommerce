from flask import Flask , render_template
from config import Config
from shop.extensions import db, migrate, bcrypt, jwt, mail, cors
from shop.utils.runtime import configure_logging, register_api_error_handlers
import os


def ensure_system_roles(app):
    from shop.models import Role

    required_roles = ('admin', 'seller', 'customer')

    with app.app_context():
        try:
            existing_roles = {
                role.role_name
                for role in Role.query.filter(Role.role_name.in_(required_roles)).all()
            }

            missing_roles = [role_name for role_name in required_roles if role_name not in existing_roles]
            if not missing_roles:
                return

            for role_name in missing_roles:
                db.session.add(Role(role_name=role_name))

            db.session.commit()
            app.logger.info("Created missing roles: %s", ", ".join(missing_roles))
        except Exception as exc:
            db.session.rollback()
            app.logger.warning("Role initialization skipped: %s", exc)

def create_app(config_class=Config):
    # Configure Flask to serve frontend from frontend/ directory
    basedir = os.path.abspath(os.path.dirname(__file__))
    template_dir = os.path.join(basedir, 'frontend', 'templates')
    static_dir = os.path.join(basedir, 'frontend', 'static')
    
    app = Flask(__name__, template_folder=template_dir, static_folder=static_dir, static_url_path='/static')
    
    app.config.from_object(config_class)
    configure_logging(app)

    # extensions initialize
    db.init_app(app)
    migrate.init_app(app, db)
    bcrypt.init_app(app)
    jwt.init_app(app)
    mail.init_app(app)
    cors.init_app(app, resources={r"/api/*": {"origins": "*"}})
    register_api_error_handlers(app, jwt)

    from shop import models

    # Blueprints Register
    from shop.auth.routes import auth_bp
    app.register_blueprint(auth_bp, url_prefix='/api/auth')

    from shop.user.routes import user_bp
    app.register_blueprint(user_bp, url_prefix='/api/user')

    from shop.admin.routes import admin_bp
    app.register_blueprint(admin_bp, url_prefix='/api/admin')
    
    from shop.seller.routes import seller_bp
    app.register_blueprint(seller_bp, url_prefix='/api/seller')

    ensure_system_roles(app)

    @app.route('/')
    def index():
        return render_template('index.html')

    return app

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, port=5000)

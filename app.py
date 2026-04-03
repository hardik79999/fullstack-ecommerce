from flask import Flask , render_template
from config import Config
from shop.extensions import db, migrate, bcrypt, jwt, mail, cors
import os

def create_app(config_class=Config):
    # Configure Flask to serve frontend from frontend/ directory
    basedir = os.path.abspath(os.path.dirname(__file__))
    template_dir = os.path.join(basedir, 'frontend', 'templates')
    static_dir = os.path.join(basedir, 'frontend', 'static')
    
    app = Flask(__name__, template_folder=template_dir, static_folder=static_dir, static_url_path='/static')
    
    app.config.from_object(config_class)

    # extensions initialize
    db.init_app(app)
    migrate.init_app(app, db)
    bcrypt.init_app(app)
    jwt.init_app(app)
    mail.init_app(app)
    cors.init_app(app, resources={r"/api/*": {"origins": "*"}})

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

    @app.route('/')
    def index():
        return render_template('index.html')

    return app

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, port=5000)
from flask import Flask
from config import Config
from shop.extensions import db, migrate  # <-- Yahan se utils hata diya

def create_app(config_class=Config):
    app = Flask(__name__)
    
    app.config.from_object(config_class)

    db.init_app(app)
    migrate.init_app(app, db)

    # Models ko yahan import karna zaroori hai
    from shop import models  # <-- Yahan se bhi utils hata diya

    @app.route('/')
    def index():
        return {"message": "E-Commerce Backend is Running Successfully!"}, 200

    return app

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True)
import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev_fallback_secret_key_with_minimum_length'
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    LOG_LEVEL = os.environ.get('LOG_LEVEL') or 'INFO'
    
    # Naya add kiya hai: JWT ke liye secret key
    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY') or f'{SECRET_KEY}_jwt_signing_material'

    MAIL_SERVER = os.environ.get('MAIL_SERVER')
    MAIL_PORT = int(os.environ.get('MAIL_PORT') or 587)
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS') == 'True'
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_USERNAME')



    # 📁 File Upload Settings
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'frontend', 'static', 'uploads', 'products')
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024  # Max 5MB file allowed
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}

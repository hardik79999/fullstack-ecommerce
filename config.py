import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev_fallback_secret_key'
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Naya add kiya hai: JWT ke liye secret key
    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY') or 'hardik_jwt_super_secret_key'
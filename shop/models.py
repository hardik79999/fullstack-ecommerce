import uuid
from datetime import datetime
from shop.extensions import db

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True) # Ye DB ke internal kaam ke liye rahega
    
    public_id = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    phone = db.Column(db.String(15), unique=True, nullable=True)
    
    role = db.Column(db.String(20), default='user')
    
    is_active = db.Column(db.Boolean, default=True)
    is_verified = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<User {self.username} - Role: {self.role}>"
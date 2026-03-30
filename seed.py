from app import create_app
from shop.extensions import db
from shop.models import Role

app = create_app()

with app.app_context():
    # Check karna ki kahin roles pehle se toh nahi hain
    if not Role.query.first():
        print("Creating default roles...")
        role1 = Role(role_name='user')
        role2 = Role(role_name='seller')
        role3 = Role(role_name='admin')
        
        db.session.add_all([role1, role2, role3])
        db.session.commit()
        print("✅ Default roles added successfully!")
    else:
        print("⚠️ Roles already exist in the database.")
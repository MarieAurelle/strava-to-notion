from app import app # ton app Flask
from dbCalls import db

with app.app_context():
    db.create_all()

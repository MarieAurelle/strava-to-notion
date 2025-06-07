from app import app, db  # ton app Flask

with app.app_context():
    db.create_all()

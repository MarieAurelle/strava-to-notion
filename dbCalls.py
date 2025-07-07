from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timezone
import os, requests
from sqlalchemy import func

db = SQLAlchemy()

class Athlete(db.Model):
    __tablename__ = "Athlete"  # ce nom doit exister
    id = db.Column(db.Integer, primary_key=True)
    strava_id = db.Column(db.String, unique=True, nullable=False)
    collab_id = db.Column(db.String, unique=True, nullable=False)
    access_token = db.Column(db.String, nullable=False)
    refresh_token = db.Column(db.String, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    last_sync = db.Column(db.DateTime(timezone=True), default=datetime.utcnow, server_default=func.now(), nullable=False)

def initDb(app, config):
    app.config["SQLALCHEMY_DATABASE_URI"] = config["DATABASE_URL"]
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    db.init_app(app)

def upsertAthlete(collab_id, tokens):
    athlete = getAthleteDbFromCollab(collab_id)
    if not athlete:
        athlete = Athlete(collab_id=collab_id)
    athlete.access_token = tokens['access_token']
    athlete.refresh_token = tokens['refresh_token']
    athlete.expires_at = tokens['expires_at']
    athlete.strava_id = str(tokens['athlete']['id'])
    db.session.add(athlete)
    db.session.commit()

    return athlete

def getAthleteDb(flaskId):
    return db.session.get(Athlete, flaskId)

def getAthleteDbFromCollab(collab_id):
    return Athlete.query.filter_by(collab_id=collab_id).first()

def saveUser(user):
      db.session.commit()

def delete_collab_from_db(collab_id):
    athlete = Athlete.query.filter_by(id=collab_id).first()
    if athlete:
        db.session.delete(athlete)
        db.session.commit()

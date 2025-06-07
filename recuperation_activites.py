import time
from datetime import datetime
from flask import Flask
from config import getConfig
from dbCalls import initDb, getAthleteDb
from notionCalls import get_all_athletes, save_activity, link_to_participation, get_active_participations, getAvailableActivitiesForAthleteForChallenges
from stravaCalls import refresh_token, get_activities

# Créer une app Flask pour lier SQLAlchemy
app = Flask(__name__)

# Charger la configuration
config = getConfig()
initDb(app, config)

def is_activity_count_for_challenge(activity, p, athlete_activities_ids):
    act_date = datetime.fromisoformat(activity["start_date_local"].replace("Z", "")).date()
    act_type = activity["type"]
    act_id = str(activity["id"])

    return datetime.fromisoformat(p["start"]).date() <= act_date <= datetime.fromisoformat(p["end"]).replace(hour=23, minute=59, second=59).date() and act_type in config["ALLOWED_ACTIVITY_TYPES"] and act_id not in athlete_activities_ids

if __name__ == "__main__":
    with app.app_context():
        # Récupère les athlètes
        athletes = get_all_athletes()

        for athlete in athletes:
            props = athlete["properties"]
            # Get athlete dans la bdd flask
            athletedb = getAthleteDb(props["ID Flask"]["rich_text"][0]["plain_text"])
            expires_at = datetime.fromisoformat(athletedb.expires_at)

            if datetime.utcnow() >= expires_at:
                client_id = config["STRAVA_CLIENT_ID"]
                client_secret = config["STRAVA_CLIENT_SECRET"]
                try:
                    access_token = refresh_token(athletedb.refresh_token, client_id, client_secret, athlete["id"], athletedb)
                except Exception as e:
                    print(f"Erreur refresh token pour {athlete['id']} : {e}")
                    continue
            else:
                access_token = athletedb.access_token

            participations = get_active_participations(athlete["id"])

            # Convertir les dates en objets datetime
            start_dates = [datetime.fromisoformat(p["start"]) for p in participations]
            end_dates = [datetime.fromisoformat(p["end"]).replace(hour=23, minute=59, second=59) for p in participations]

            if start_dates and end_dates:
                # Récupérer les dates min et max
                min_start = min(start_dates)
                max_end = max(end_dates)

                # Récupérer les activités déjà enregistrées pour les participations de l'athlete
                athlete_activities = getAvailableActivitiesForAthleteForChallenges(athlete["id"], min_start, max_end)
                athlete_activities_ids = []
                for activity in athlete_activities:
                    props = activity.get("properties", {})
                    identifiant = props.get("Identifiant", {})

                    rich_text = identifiant.get("rich_text", [])
                    if rich_text and isinstance(rich_text, list) and "plain_text" in rich_text[0]:
                        athlete_activities_ids.append(rich_text[0]["plain_text"])

                # Récupérer les activités dans les participations
                activities = get_activities(access_token, min_start, max_end)

                for activity in activities:
                    for p in participations:
                        if is_activity_count_for_challenge(activity, p, athlete_activities_ids):
                            save_activity(activity, athlete['id'], p["participation_id"])
                            time.sleep(0.2)

        print("✅ Extraction terminée.")

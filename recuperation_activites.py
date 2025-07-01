import json
import time
from datetime import datetime, timezone
import requests
from notion_client import Client

# Charger la configuration
with open("config.prod.json") as f:
    config = json.load(f)

NOTION_SECRET = config["NOTION_TOKEN"]
DB_ATHLETES = config["ATHLETES_DB_ID"]
DB_ACTIVITIES = config["ACTIVITES_DB_ID"]

notion = Client(auth=NOTION_SECRET)

def get_all_athletes():
    athletes = []
    cursor = None
    while True:
        query = notion.databases.query(
            database_id=DB_ATHLETES,
            start_cursor=cursor
        )
        athletes.extend(query["results"])
        if not query.get("has_more"):
            break
        cursor = query.get("next_cursor")
    return athletes


def refresh_token(refresh_token, client_id, client_secret, athlete_page_id):
    response = requests.post("https://www.strava.com/api/v3/oauth/token", data={
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token
    })
    response.raise_for_status()
    token_data = response.json()
    
    access_token = token_data["access_token"]
    new_refresh_token = token_data["refresh_token"]
    expires_at = datetime.fromtimestamp(token_data["expires_at"]).isoformat()
    
    # 🔄 Mise à jour dans Notion
    notion.pages.update(
        page_id=athlete_page_id,
        properties={
            "Access Token": {"rich_text": [{"text": {"content": access_token}}]},
            "Refresh Token": {"rich_text": [{"text": {"content": new_refresh_token}}]},
            "Expires At": {"number": token_data['expires_at']},
            "Last Sync": {"date": {"start": datetime.now(timezone.utc).isoformat()}}
        }
    )

    return access_token


def get_activities(access_token, start, end):
    url = "https://www.strava.com/api/v3/athlete/activities"
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"after": int(start.replace(tzinfo=timezone.utc).timestamp()), "before": int(end.replace(tzinfo=timezone.utc).timestamp()), "per_page": 100, "page": 1}
    all_activities = []

    while True:
        resp = requests.get(url, headers=headers, params=params)
        
        if resp.status_code != 200:
            raise Exception(f"❌ Erreur API : {resp.text}")
        data = resp.json()
        if not data:
            break
        all_activities.extend(data)
        params["page"] += 1

    return all_activities

def is_activity_count_for_challenge(activity, p, athlete_activities_ids):
    act_date = activity["start_date_local"]
    act_type = activity["type"]
    act_id = str(activity["id"])

    return p["start"] <= act_date <= p["end"]  and act_type in config["ALLOWED_ACTIVITY_TYPES"] and act_id not in athlete_activities_ids


#def save_activity(activity, extraction_id, athlete_id, participation_id):
def save_activity(activity, athlete_id, participation_id):
    page = notion.pages.create(
        parent={"database_id": DB_ACTIVITIES},
        properties={
            "Nom": {"title": [{"text": {"content": f"{activity['name']} - {round(activity['distance'] / 1000, 2)}"}}]},
            "Date": {
                "date": {"start": activity["start_date_local"]}
            },
            "Distance (km)": {
                "number": round(activity["distance"] / 1000, 2)
            },
            "Temps (min)": {
                "number": round(activity["moving_time"] / 60, 1)
            },
            "Type": {
                "select": {"name": activity["type"]}
            },
            "Athlete": {
                "relation": [{"id": athlete_id}]
            },
            "Identifiant": {
                "rich_text": [{"text": {"content": str(activity["id"])}}]
            },
        }
    )
    
    # Lier aux participations si applicable
    link_to_participation(page["id"], participation_id)
    return page["id"]
    
def link_to_participation(activity_page_id, participation_id):
    participation = notion.pages.retrieve(participation_id)

    props = participation["properties"]
    challenge_ref = participation["properties"]["Challenge"]["relation"]
    
    if challenge_ref:
        challenge_id = challenge_ref[0]["id"]
        challenge = notion.pages.retrieve(challenge_id)
        challenge_props = challenge["properties"]
        start = challenge_props["Date début"]["date"]["start"]
        end = challenge_props["Date fin"]["date"]["end"]

        # Mise à jour de la participation : ajout de l’activité
        existing_relations = props.get("Activités", {}).get("relation", [])
        existing_ids = [rel["id"] for rel in existing_relations]

        if activity_page_id not in existing_ids:
            notion.pages.update(
                page_id=participation_id,
                properties={
                    "Activités": {"relation": existing_relations + [{"id": activity_page_id}]}
                }
            )

def get_active_participations(athlete_id):
    participations = notion.databases.query(
        database_id=config["PARTICIPATIONS_DB_ID"],
        filter={
            "and": [
                {"property": "Athlete", "relation": {"contains": athlete_id}}
            ]
        }
    )
    
    active = []
    now = datetime.utcnow().isoformat()
    
    for p in participations["results"]:
        challenge_rel = p["properties"]["Challenge"]["relation"]
        if not challenge_rel:
            continue

        challenge_id = challenge_rel[0]["id"]
        challenge = notion.pages.retrieve(challenge_id)
        start = challenge["properties"]["Date début"]["date"]["start"]
        end = challenge["properties"]["Date fin"]["date"]["start"]

        if start <= now <= end:
            active.append({
                "participation_id": p["id"],
                "start": start,
                "end": end
            })

    return active


def main():
    # Récupère les athlètes
    athletes = get_all_athletes()
    
    for athlete in athletes:
        props = athlete["properties"]     
        refresh = props["Refresh Token"]["rich_text"][0]["plain_text"]
        client_id = config["STRAVA_CLIENT_ID"]
        client_secret = config["STRAVA_CLIENT_SECRET"]

        try:
            access_token = refresh_token(refresh, client_id, client_secret, athlete["id"])
        except Exception as e:
            print(f"Erreur refresh token pour {athlete['id']} : {e}")
            continue
        
        participations = get_active_participations(athlete["id"])
                
        # Convertir les dates en objets datetime
        start_dates = [datetime.fromisoformat(p["start"]) for p in participations]
        end_dates = [datetime.fromisoformat(p["end"]) for p in participations]

        if not start_dates or not end_dates:
            print(f"⛔ Aucune participation valide pour l'athlète {athlete['id']}.")
            continue

        # Récupérer les dates min et max
        min_start = min(start_dates)
        max_end = max(end_dates)

        # Récupérer les activités déjà enregistrées pour les participations de l'athlete
        athlete_activities = notion.databases.query(
            database_id=config["ACTIVITES_DB_ID"],
            filter={
                "and": [
                    {"property": "Athlete", "relation": {"contains": athlete['id']}},
                    {
                        "property": "Date",
                        "date": {
                            "on_or_after": min_start.isoformat()
                        }
                    },
                    {
                        "property": "Date",
                        "date": {
                            "on_or_before": max_end.isoformat()
                        }
                    }
                ]
            }
        )
        athlete_activities_ids = []
        for activity in athlete_activities.get("results", []):
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
                    #save_activity(activity, extraction_id, athlete['id'], p["participation_id"])
                    save_activity(activity, athlete['id'], p["participation_id"])
                    time.sleep(0.2)

    
    print("✅ Extraction terminée.")


if __name__ == "__main__":
    main()

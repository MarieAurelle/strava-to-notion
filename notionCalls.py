from notion_client import Client
import json
from config import getConfig
from datetime import datetime, timezone

# Charger la config
config = getConfig()
notion = Client(auth=config["NOTION_TOKEN"])

def getAthleteFromCollab(collab_id):
    # Récupération de l'athlète correspondant
    query = notion.databases.query(
        database_id=config["ATHLETES_DB_ID"],
        filter={
            "property": "Collaborateur",  # nom de la propriété de relation
            "people": {
                "contains": collab_id
            }
        }
    )
    return query.get("results", [])

def getAthlete(athlete_id):
    return notion.pages.retrieve(page_id=athlete_id)

def get_all_athletes():
    athletes = []
    cursor = None
    while True:
        query = notion.databases.query(
            database_id=config["ATHLETES_DB_ID"],
            start_cursor=cursor
        )
        athletes.extend(query["results"])
        if not query.get("has_more"):
            break
        cursor = query.get("next_cursor")
    return athletes

def createAthlete(title, flask_id, collab_id):
    return notion.pages.create(
       parent={"database_id": config["ATHLETES_DB_ID"]},
       properties={
           "Nom": {"title": [{"text": {"content": title}}]},
           "ID Flask": {"rich_text": [{"text": {"content": flask_id}}]},
           "Last Sync": {"date": {"start": datetime.now(timezone.utc).isoformat()}},
           "Collaborateur": {"people": [{"id": collab_id}]}
       }
   )

def updateAthleteFlaskId(athlete_page_id, flaskId):
    return notion.pages.update(
       page_id=athlete_page_id,
       properties={
           "ID Flask": {
               "rich_text": [
                   {"text": {"content": flaskId}}
               ]
           }
       }
   )

def getRunningPage():
    return notion.pages.retrieve(page_id=config["CLUB_RUNNING_ID"])

def getChallengeParticipations(challenge_id):
    return notion.databases.query(
       database_id=config["PARTICIPATIONS_DB_ID"],
       filter={
           "property": "Challenge",
           "relation": {"contains": challenge_id}
       }
   )["results"]

def getChallengeParticipationsForAthlete(challenge_id, athlete_id):
    return notion.databases.query(
       database_id=config["PARTICIPATIONS_DB_ID"],
       filter={
           "and": [
               {"property": "Athlete", "relation": {"contains": athlete_id}},
               {"property": "Challenge", "relation": {"contains": challenge_id}},
           ]
       }
   )["results"]

def createParticipationOfAthleteForChallenge(challenge_id, athlete_id):
    return notion.pages.create(
       parent={"database_id": config["PARTICIPATIONS_DB_ID"]},
       properties={
           "Athlete": {"relation": [{"id": athlete_id}]},
           "Challenge": {"relation": [{"id": challenge_id}]},
       }
   )

def get_collaborateurs_from_club():
    page = getRunningPage()
    collaborateurs_rel = page["properties"]["Collaborateurs"]['people']

    collaborateurs = []

    for collab in collaborateurs_rel:
        collab_id = collab["id"]
        name = collab["name"]

        collaborateurs.append({
            "id": collab_id,
            "name": name
        })

    return collaborateurs

def get_collaborateurs_non_inscrits(challenge_id):
    # 1. Récupérer tous les collaborateurs (id, nom, prénom)
    all_collabs = get_collaborateurs_from_club()
    all_collab_ids = {c["id"] for c in all_collabs}

    # 2. Récupérer les participations au challenge
    participations = getChallengeParticipations(challenge_id)

    # 3. Identifier les collaborateurs déjà inscrits via les athlètes
    collabs_inscrits = set()

    for participation in participations:
        athlete_rel = participation["properties"].get("Athlete", {}).get("relation", [])
        if not athlete_rel:
            continue
        athlete_id = athlete_rel[0]["id"]
        athlete = getAthlete(athlete_id)
        collab_rel = athlete["properties"].get("Collaborateur", {}).get("people", [])
        if collab_rel:
            collabs_inscrits.add(collab_rel[0]["id"])

    # 4. Filtrer les collaborateurs non inscrits
    non_inscrits = [c for c in all_collabs if c["id"] not in collabs_inscrits]

    return non_inscrits

def save_activity(activity, athlete_id, participation_id):
    page = notion.pages.create(
        parent={"database_id": config["ACTIVITES_DB_ID"]},
        properties={
            "Nom": {"title": [{"text": {"content": f"{activity['name']} - {round(activity['distance'] / 1000, 2)}"}}]},
            "Date": {
                "date": {"start": datetime.fromisoformat(activity["start_date_local"].replace("Z", "")).date().isoformat()}
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

        challengeStatus = challenge["properties"]["Statut"]['formula']['string']

        if challengeStatus == 'En cours':
            start = challenge["properties"]["Date début"]["date"]["start"]
            end = challenge["properties"]["Date fin"]["date"]["start"]

            active.append({
                "participation_id": p["id"],
                "start": start,
                "end": end
            })

    return active

def getAvailableActivitiesForAthleteForChallenges(athleteId, min_start, max_end):
    return notion.databases.query(
        database_id=config["ACTIVITES_DB_ID"],
        filter={
           "and": [
               {"property": "Athlete", "relation": {"contains": athleteId}},
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
    )["results"]

def delete_collab_data_from_notion(collab_id):
    # Récupération de l'athlète correspondant
    athlete = getAthleteFromCollab(collab_id)[0]["id"]

    participations = notion.databases.query(
        database_id=config["PARTICIPATIONS_DB_ID"],
        filter={
            "and": [
                {"property": "Athlete", "relation": {"contains": athlete_id}}
            ]
        }
    )["results"]

    activities = notion.databases.query(
            database_id=config["ACTIVITES_DB_ID"],
            filter={
               "and": [
                   {"property": "Athlete", "relation": {"contains": athleteId}},
               ]
            }
        )["results"]

    for page in participations:
        notion.pages.update(page["id"], archived=True)
    for page in activities:
        notion.pages.update(page["id"], archived=True)
    notion.pages.update(athlete, archived=True)


from flask import Flask, request, redirect, render_template
import requests
import json
from datetime import datetime, timezone
from notion_client import Client

app = Flask(__name__)
config_path = os.getenv("CONFIG_PATH", "/etc/secrets/config.json")

# Charger la config
with open("config.json") as f:
    config = json.load(f)

notion = Client(auth=config["NOTION_TOKEN"])

@app.route("/")
def index():
    return render_template("form.html")

@app.route("/start", methods=["POST"])
def start():
    email = request.form["email"]
    strava_auth_url = (
        f"https://www.strava.com/oauth/authorize"
        f"?client_id={config['STRAVA_CLIENT_ID']}"
        f"&response_type=code"
        f"&redirect_uri={config['REDIRECT_URI']}"
        f"&approval_prompt=auto"
        f"&scope=read,activity:read_all"
        f"&state={email}"
    )
    return redirect(strava_auth_url)

@app.route("/callback")
def callback():
    code = request.args.get("code")
    email = request.args.get("state")

    # Échange le code contre des tokens
    token_res = requests.post("https://www.strava.com/oauth/token", data={
        "client_id": config["STRAVA_CLIENT_ID"],
        "client_secret": config["STRAVA_CLIENT_SECRET"],
        "code": code,
        "grant_type": "authorization_code"
    })
    tokens = token_res.json()

    if "access_token" not in tokens:
        print("Erreur lors de l'authentification Strava")
        return render_template("error.html", message="Erreur lors de l'authentification Strava !")
        
    # Rechercher un athlète par email
    athletes = notion.databases.query(
        database_id=config["ATHLETES_DB_ID"],
        filter={"property": "Email", "email": {"equals": email}}
    )

    if athletes["results"]:
        print("❌ Cet athlète existe déjà dans Notion")
        return render_template("success.html", message="Votre compte Strava est déjà connecté à Notion !")
    
    # Rechercher le collaborateur par email
    collabs = notion.databases.query(
        database_id=config["COLLAB_DB_ID"],
        filter={"property": "email", "email": {"equals": email}}
    )

    if not collabs["results"]:
        print("❌ Collaborateur introuvable dans Notion")
        return render_template("error.html", message="Nous ne vous avons pas trouvé dans Notion !")

    collab_id = collabs["results"][0]["id"]
    collab_nom = collabs["results"][0]["properties"]["Nom"]["title"][0]["plain_text"]
    collab_prenom = collabs["results"][0]["properties"]["Prénom"]["rich_text"][0]["plain_text"]
    title = f"{collab_nom} {collab_prenom}"

    # Créer l’entrée Athlète
    notion.pages.create(
        parent={"database_id": config["ATHLETES_DB_ID"]},
        properties={
            "Nom": {"title": [{"text": {"content": title}}]},
            "Email": {"email": email},
            "Strava ID": {"rich_text": [{"text": {"content": str(tokens['athlete']['id'])}}]},
            "Access Token": {"rich_text": [{"text": {"content": tokens['access_token']}}]},
            "Refresh Token": {"rich_text": [{"text": {"content": tokens['refresh_token']}}]},
            "Expires At": {"number": tokens['expires_at']},
            "Last Sync": {"date": {"start": datetime.now(timezone.utc).isoformat()}},
            "Collaborateur": {"relation": [{"id": collab_id}]}
        }
    )

    return render_template("success.html", message="Votre compte Strava est maintenant connecté à Notion !")

@app.route("/inscription/<challenge_id>")
def inscription(challenge_id):
    # Récupère les athlètes dans Notion
    athletes = notion.databases.query(
        database_id=config["ATHLETES_DB_ID"]
    )["results"]

    # Récupère toutes les participations à ce challenge
    participations = notion.databases.query(
        database_id=config["PARTICIPATIONS_DB_ID"],
        filter={
            "property": "Challenge",
            "relation": {
                "contains": challenge_id
            }
        }
    )["results"]

    # Obtenir les IDs des athlètes déjà inscrits
    inscrits_ids = {
        p["properties"]["Athlète"]["relation"][0]["id"]
        for p in participations
        if p["properties"]["Athlète"]["relation"]
    }
    
    # Ne garder que ceux non inscrits
    athletes_non_inscrits = [a for a in athletes if a["id"] not in inscrits_ids]


    athlete_list = []
    for athlete in athletes_non_inscrits:
        props = athlete["properties"]
        email = props.get("Email", {}).get("email")
        name = props.get("Nom", {}).get("title", [{}])[0].get("plain_text", "Inconnu")
        if email:
            athlete_list.append({"name": name, "email": email, "id": athlete.get("id")})
    print(athlete_list)
    return render_template("inscription.html", athletes=athlete_list, challenge_id=challenge_id)


@app.route("/join-challenge", methods=["POST"])
def join_challenge():
    challenge_id = request.form["challenge_id"]
    athlete_id = request.form["athlete_id"]
    
    if not challenge_id or not athlete_id:
        return render_template("error.html", message="Paramètres manquants.")

    # Vérifier s’il existe déjà une participation
    participations = notion.databases.query(
        database_id=config["PARTICIPATIONS_DB_ID"],
        filter={
            "and": [
                {"property": "Athlète", "relation": {"contains": athlete_id}},
                {"property": "Challenge", "relation": {"contains": challenge_id}},
            ]
        }
    )

    if participations["results"]:
        return render_template("success.html", message="✅ Vous êtes déjà inscrit à ce challenge.")

    # Créer la participation
    notion.pages.create(
        parent={"database_id": config["PARTICIPATIONS_DB_ID"]},
        properties={
            "Athlète": {"relation": [{"id": athlete_id}]},
            "Challenge": {"relation": [{"id": challenge_id}]},
            "Distance totale (km)": {"number": 0},
            #"Temps total (min)": {"number": 0},
            #"Nombre d'activités": {"number": 0},
        }
    )

    return render_template("success.html", message="✅ Inscription au challenge réussie !")


if __name__ == "__main__":
    app.run(debug=True)

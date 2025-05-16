from flask import Flask, request, redirect, render_template, render_template_string, url_for, jsonify
import requests
import json, urllib.parse
from datetime import datetime, timezone
from notion_client import Client
import os
import webbrowser

app = Flask(__name__)
config_path = os.getenv("CONFIG_PATH", "/etc/secrets/config.json")

# Charger la config
with open("config.prod.json") as f:
    config = json.load(f)

notion = Client(auth=config["NOTION_TOKEN"])

@app.route("/start")
def start():
    collab_id = request.args.get("collab_id")
    challenge_id = request.args.get("challenge_id")

    try:
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
        athletes = query.get("results", [])

        if not athletes:
            # Aucun athlète trouvé alors on le créé
            state_data = {
                "collab_id": collab_id,
                "challenge_id": challenge_id,
                "post_redirect": True  # Pour déclencher le formulaire POST plus tard
            }
            state_encoded = urllib.parse.quote(json.dumps(state_data))

            strava_auth_url = (
                f"https://www.strava.com/oauth/authorize"
                f"?client_id={config['STRAVA_CLIENT_ID']}"
                f"&response_type=code"
                f"&redirect_uri={config['REDIRECT_URI']}"
                f"&approval_prompt=auto"
                f"&scope=read,activity:read_all"
                f"&state={state_encoded}"
            )

            return redirect(strava_auth_url)

        return redirect(url_for("join_challenge_success", message="✅ Connexion à Strava déjà établie !", auto_close_popup=True, collab_id=collab_id, challenge_id=challenge_id))
    except Exception as e:
        return redirect(url_for("join_challenge_error", message=str(e)))

@app.route("/callback")
def callback():
    code = request.args.get("code")

    state = request.args.get("state")
    state_decoded = json.loads(urllib.parse.unquote(state))
    collab_id = state_decoded["collab_id"]
    challenge_id = state_decoded["challenge_id"]

    try:

        # Échange le code contre des tokens
        token_res = requests.post("https://www.strava.com/oauth/token", data={
            "client_id": config["STRAVA_CLIENT_ID"],
            "client_secret": config["STRAVA_CLIENT_SECRET"],
            "code": code,
            "grant_type": "authorization_code"
        })
        tokens = token_res.json()

        if "access_token" not in tokens:
            raise Exception("❌ Erreur lors de l'authentification Strava")

        # Récupération de l'athlète correspondant
        athletes = notion.databases.query(
            database_id=config["ATHLETES_DB_ID"],
            filter={
                "property": "Collaborateur",  # nom de la propriété de relation
                "people": {
                    "contains": collab_id
                }
            }
        )

        if athletes["results"]:
            raise Exception("❌ Cet athlète existe déjà dans Notion")

        # Rechercher le collaborateur par id
        #collab = notion.pages.retrieve(page_id=collab_id)
        collabs = get_collaborateurs_from_club()
        collab = next((c for c in collabs if c["id"] == collab_id), None)

        if not collab:
            raise Exception("❌ Collaborateur introuvable dans Notion")

        #collab_nom = collab["properties"]["Nom"]["title"][0]["plain_text"]
        #collab_prenom = collab["properties"]["Prénom"]["rich_text"][0]["plain_text"]
        #title = f"{collab_nom} {collab_prenom}"
        title = collab["name"]

        # Créer l’entrée Athlète
        athlete = notion.pages.create(
            parent={"database_id": config["ATHLETES_DB_ID"]},
            properties={
                "Nom": {"title": [{"text": {"content": title}}]},
                "Strava ID": {"rich_text": [{"text": {"content": str(tokens['athlete']['id'])}}]},
                "Access Token": {"rich_text": [{"text": {"content": tokens['access_token']}}]},
                "Refresh Token": {"rich_text": [{"text": {"content": tokens['refresh_token']}}]},
                "Expires At": {"number": tokens['expires_at']},
                "Last Sync": {"date": {"start": datetime.now(timezone.utc).isoformat()}},
                "Collaborateur": {"people": [{"id": collab_id}]}
            }
        )

        return redirect(url_for("join_challenge_success", message="✅ Connexion à Strava réussie !", auto_close_popup=True, collab_id=collab_id, challenge_id=challenge_id))
    except Exception as e:
        return redirect(url_for("join_challenge_error", message=str(e)))

def get_collaborateurs_from_club():
    page = notion.pages.retrieve(page_id=config["CLUB_RUNNING_ID"])
    #collaborateurs_rel = page["properties"]["Collaborateurs"]["relation"]
    collaborateurs_rel = page["properties"]["Collaborateurs"]['people']
    #collab_ids = [rel["id"] for rel in collaborateurs_rel]

    collaborateurs = []

    for collab in collaborateurs_rel:
        #for collab_id in collab_ids:
        #collab_page = notion.pages.retrieve(page_id=collab_id)
        #props = collab_page["properties"]

        #nom = props["Nom"]["title"][0]["plain_text"] if props["Nom"]["title"] else ""
        #prenom = props["Prénom"]["rich_text"][0]["plain_text"] if props["Prénom"]["rich_text"] else "

        collab_id = collab["id"]
        name = collab["name"]

        collaborateurs.append({
            "id": collab_id,
            "name": name
            #"nom": nom,
            #"prenom": prenom
        })
    print(collaborateurs)
    return collaborateurs

def get_collaborateurs_non_inscrits(challenge_id):
    # 1. Récupérer tous les collaborateurs (id, nom, prénom)
    all_collabs = get_collaborateurs_from_club()
    all_collab_ids = {c["id"] for c in all_collabs}

    # 2. Récupérer les participations au challenge
    participations = notion.databases.query(
        database_id=config["PARTICIPATIONS_DB_ID"],
        filter={
            "property": "Challenge",
            "relation": {"contains": challenge_id}
        }
    )

    # 3. Identifier les collaborateurs déjà inscrits via les athlètes
    collabs_inscrits = set()

    for participation in participations["results"]:
        athlete_rel = participation["properties"].get("Athlete", {}).get("relation", [])
        if not athlete_rel:
            continue
        athlete_id = athlete_rel[0]["id"]
        athlete = notion.pages.retrieve(page_id=athlete_id)
        #collab_rel = athlete["properties"].get("Collaborateur", {}).get("relation", [])
        collab_rel = athlete["properties"].get("Collaborateur", {}).get("people", [])
        if collab_rel:
            collabs_inscrits.add(collab_rel[0]["id"])

    # 4. Filtrer les collaborateurs non inscrits
    non_inscrits = [c for c in all_collabs if c["id"] not in collabs_inscrits]

    return non_inscrits


@app.route("/inscription/<challenge_id>")
def inscription(challenge_id):
    # Ne garder que ceux non inscrits
    athletes_non_inscrits = get_collaborateurs_non_inscrits(challenge_id)

    athlete_list = []
    for athlete in athletes_non_inscrits:
        #name = f"{athlete['nom']} {athlete['prenom']}"
        name = athlete["name"]
        if name:
            athlete_list.append({"name": name, "id": athlete.get("id")})

    return render_template("inscription.html", athletes=athlete_list, challenge_id=challenge_id)

@app.route("/join-challenge", methods=["POST"])
def join_challenge():
    data = request.get_json()
    collab_id = data['collab_id']
    challenge_id = data['challenge_id']

    try:
        if not challenge_id or not collab_id:
            raise Exception("❌ Paramètres manquants")

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
        athletes = query.get("results", [])

        if not athletes:
            # Aucun athlète trouvé alors erreur
            raise Exception("❌ Athlète non trouvé dans Notion !")
        else:
            athlete = athletes[0]

        athlete_id = athlete["id"]

        # Vérifier s’il existe déjà une participation
        participations = notion.databases.query(
            database_id=config["PARTICIPATIONS_DB_ID"],
            filter={
                "and": [
                    {"property": "Athlete", "relation": {"contains": athlete_id}},
                    {"property": "Challenge", "relation": {"contains": challenge_id}},
                ]
            }
        )

        if participations["results"]:
            return jsonify({
                    "message": "✅ Vous êtes déjà inscrit à ce challenge !",
                    "redirect_url": url_for('join_challenge_success')  # ou une URL vers une page succès dans ton app
                })

        # Créer la participation
        notion.pages.create(
            parent={"database_id": config["PARTICIPATIONS_DB_ID"]},
            properties={
                "Athlete": {"relation": [{"id": athlete_id}]},
                "Challenge": {"relation": [{"id": challenge_id}]},
            }
        )

        return jsonify({
                "message": "✅ Inscription au challenge réussie !",
                "redirect_url": url_for('join_challenge_success')  # ou une URL vers une page succès dans ton app
            })
    except Exception as e:
        return jsonify({
                        "message": f"❌ Erreur lors de l'inscription : { str(e)}",
                        "redirect_url": url_for('join_challenge_error')  # ou une URL vers une page succès dans ton app
                    })

@app.route("/join-challenge/success")
def join_challenge_success():
    message = request.args.get("message", "Succès !")
    auto_close_popup = request.args.get("auto_close_popup", "False")
    collab_id = request.args.get("collab_id", "")
    challenge_id = request.args.get("challenge_id", "")
    return render_template("success.html", message=message, auto_close_popup=auto_close_popup, collab_id=collab_id, challenge_id=challenge_id)

@app.route("/join-challenge/error")
def join_challenge_error():
    message = request.args.get("message", "Une erreur est survenue.")
    return render_template("error.html", message=message)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))  # fallback à 5000 si PORT non défini
    app.run(debug=True, host="0.0.0.0", port=port)

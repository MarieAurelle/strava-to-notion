from flask import Flask, request, redirect, render_template, url_for, jsonify
import json, urllib.parse
import os
from dbCalls import db, Athlete, initDb, upsertAthlete, getAthleteDb, getAthleteDbFromCollab, delete_collab_from_db
from stravaCalls import askStravaData, getTokens
from notionCalls import get_collaborateurs_non_inscrits, get_collaborateurs_from_club, updateAthleteFlaskId, createParticipationOfAthleteForChallenge, getAthleteFromCollab, createAthlete, getChallengeParticipations, getChallengeParticipationsForAthlete, delete_collab_data_from_notion
from config import getConfig

app = Flask(__name__)

# Charger la config
config = getConfig()
initDb(app, config)

with app.app_context():
    db.create_all()

# Fonction qui permet d'aller vérifier si la config strava existe
@app.route("/start")
def start():
    # On récupère l'id du collab ainsi que l'id du challenge de l'utilisateur qui veut se connecter
    collab_id = request.args.get("collab_id")
    challenge_id = request.args.get("challenge_id")

    try:
        # On va chercher l'athlete correspondant au collab dans notion
        athlete = getAthleteFromCollab(collab_id)

        if not athlete:
            # Si aucun athlète n'est trouvé dans Notion alors on cherche d'abord s'il existe en bdd
            athleteFlask = getAthleteDbFromCollab(collab_id)

            if athleteFlask:
                # S'il existe en bdd alors on créé un athlète dans Notion avec cet ID
                collabs = get_collaborateurs_from_club()
                collab = next((c for c in collabs if c["id"] == collab_id), None)
                title = collab["name"]
                athlete = createAthlete(title, str(athleteFlask.id), collab_id)
            else:
                # Sinon on demande l'authentification Strava
                return askStravaData(collab_id, challenge_id)
        else:
            athlete = athlete[0]
            # Si l'athlète existe, on vérifie que son ID flask existe bien en bdd

            if athlete["properties"]["ID Flask"]["rich_text"]:
                athleteFlask = getAthleteDb(int(athlete["properties"]["ID Flask"]["rich_text"][0]["plain_text"]))

                if not athleteFlask:
                    # Si la config Flask n'existe pas alors on demande l'authentification Strava
                    return askStravaData(collab_id, challenge_id)
            else:
                # Si la config Flask n'existe pas alors on demande l'authentification Strava
                return askStravaData(collab_id, challenge_id)

        return redirect(url_for("join_challenge_success", message="✅ Connexion à Strava déjà établie !", auto_close_popup=True, collab_id=collab_id, challenge_id=challenge_id))
    except Exception as e:
        return redirect(url_for("join_challenge_error", message=str(e)))

# Fonction appelée après l'authentification Strava pour récupérer et créer les données de l'athlete (notion/bdd)
@app.route("/callback")
def callback():
    code = request.args.get("code")

    state = request.args.get("state")
    state_decoded = json.loads(urllib.parse.unquote(state))
    collab_id = state_decoded["collab_id"]
    challenge_id = state_decoded["challenge_id"]

    try:
        # On vérifie que le collab fait partie du club dans Notion
        collabs = get_collaborateurs_from_club()
        collab = next((c for c in collabs if c["id"] == collab_id), None)

        if not collab:
            raise Exception("❌ Collaborateur introuvable dans Notion")

        # Échange le code contre des tokens
        tokens = getTokens(code)

        if "access_token" not in tokens:
            raise Exception("❌ Erreur lors de l'authentification Strava")

        # On créé ou update l'entité en bdd
        athleteFlask = upsertAthlete(collab_id, tokens)

        # Récupération de l'athlète correspondant
        athlete = getAthleteFromCollab(collab_id)

        if athlete:
            athlete = updateAthleteFlaskId(athlete[0]["id"], str(athleteFlask.id))
        else:
            title = collab["name"]
            athlete = createAthlete(title, str(athleteFlask.id), collab_id)

        return redirect(url_for("join_challenge_success", message="✅ Connexion à Strava réussie !", auto_close_popup=True, collab_id=collab_id, challenge_id=challenge_id))
    except Exception as e:
        return redirect(url_for("join_challenge_error", message=str(e)))

# Fonction qui permet d'afficher la liste des collabs qui peuvent s'inscrire à un challenge
# Il s'agit des collab du club non encore inscrit à ce challenge
@app.route("/inscription/<challenge_id>")
def inscription(challenge_id):
    # Ne garder que ceux non inscrits
    athletes_non_inscrits = get_collaborateurs_non_inscrits(challenge_id)

    athlete_list = []
    for athlete in athletes_non_inscrits:
        name = athlete["name"]
        if name:
            athlete_list.append({"name": name, "id": athlete.get("id")})

    return render_template("inscription.html", athletes=athlete_list, challenge_id=challenge_id)

# Fonction qui permet à un athlète de participer à un challenge
@app.route("/join-challenge", methods=["POST"])
def join_challenge():
    data = request.get_json()
    collab_id = data['collab_id']
    challenge_id = data['challenge_id']

    try:
        if not challenge_id or not collab_id:
            raise Exception("❌ Paramètres manquants")

        # Récupération de l'athlète correspondant
        athletes = getAthleteFromCollab(collab_id)

        if not athletes:
            # Aucun athlète trouvé alors erreur
            raise Exception("❌ Athlète non trouvé dans Notion !")
        else:
            athlete = athletes[0]

        athlete_id = athlete["id"]

        # Vérifier s’il existe déjà une participation
        participations = getChallengeParticipationsForAthlete(challenge_id, athlete_id)

        if participations:
            return jsonify({
                    "message": "✅ Vous êtes déjà inscrit à ce challenge !",
                    "redirect_url": url_for('join_challenge_success')  # ou une URL vers une page succès dans ton app
                })

        # Créer la participation
        createParticipationOfAthleteForChallenge(challenge_id, athlete_id)

        return jsonify({
                "message": "✅ Inscription au challenge réussie !",
                "redirect_url": url_for('join_challenge_success')  # ou une URL vers une page succès dans ton app
            })
    except Exception as e:
        return jsonify({
                        "message": f"❌ Erreur lors de l'inscription : { str(e)}",
                        "redirect_url": url_for('join_challenge_error')  # ou une URL vers une page succès dans ton app
                    })

# Fonction qui affiche un message de succès suite à l'inscription au challenge
@app.route("/join-challenge/success")
def join_challenge_success():
    message = request.args.get("message", "Succès !")
    auto_close_popup = request.args.get("auto_close_popup", "False")
    collab_id = request.args.get("collab_id", "")
    challenge_id = request.args.get("challenge_id", "")
    return render_template("success.html", message=message, auto_close_popup=auto_close_popup, collab_id=collab_id, challenge_id=challenge_id)

# Fonction qui affiche un message d'erreur suite à la demande d'inscription au challenge
@app.route("/join-challenge/error")
def join_challenge_error():
    message = request.args.get("message", "Une erreur est survenue.")
    return render_template("error.html", message=message)

@app.route("/ping")
def ping():
    expected_token = config["PING_SECRET"]
    received_token = request.args.get("token")

    if not expected_token or received_token != expected_token:
        return jsonify({"status": "unauthorized"}), 401

    return jsonify({"status": "ok", "message": "Warmup successful"}), 200

@app.route('/delete_collab_data', methods=['GET'])
def delete_collab_data():
    athletes_inscrits = get_collaborateurs_from_club()

    athlete_list = []
    for athlete in athletes_inscrits:
        name = athlete["name"]
        if name:
            athlete_list.append({"name": name, "id": athlete.get("id")})

    return render_template("delete_data.html", athletes=athlete_list)

@app.route('/confirm_delete_collab_data', methods=['POST'])
def confirm_delete_collab_data():
    data = request.get_json()
    collab_id = data['collab_id']

    try:
        delete_collab_data_from_notion(collab_id)
        delete_collab_from_db(collab_id)
        print("✅ Données supprimées avec succès.")
        return jsonify({
            "message": "✅ Données supprimées avec succès.",
            "redirect_url": url_for('delete_collab_data_success')  # ou une URL vers une page succès dans ton app
        })
    except Exception as e:
        print(f"❌ Erreur pendant la suppression : {str(e)}")
        return jsonify({
            "message": f"❌ Erreur pendant la suppression : {str(e)}",
            "redirect_url": url_for('delete_collab_data_error')  # ou une URL vers une page succès dans ton app
        })

@app.route("/delete_collab_data/success")
def delete_collab_data_success():
    message = request.args.get("message", "Succès !")
    return render_template("success.html", message=message)

@app.route("/delete_collab_data/error")
def delete_collab_data_error():
    message = request.args.get("message", "Succès !")
    return render_template("error.html", message=message)

# Démarrage du serveur
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))  # fallback à 5000 si PORT non défini
    app.run(debug=True, host="0.0.0.0", port=port)

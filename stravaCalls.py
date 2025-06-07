import json, urllib.parse
from flask import redirect
from config import getConfig
import requests
from datetime import datetime, timezone
from dbCalls import saveUser

# Charger la config
config = getConfig()

def askStravaData(collab_id, challenge_id):
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

def getTokens(code):
    token_res = requests.post("https://www.strava.com/oauth/token", data={
        "client_id": config["STRAVA_CLIENT_ID"],
        "client_secret": config["STRAVA_CLIENT_SECRET"],
        "code": code,
        "grant_type": "authorization_code"
    })
    return token_res.json()

def refresh_token(refresh_token, client_id, client_secret, athlete_page_id, user):
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

    #Mise à jour dans la bdd
    user.access_token = access_token
    user.refresh_token = new_refresh_token
    user.expires_at = datetime.utcfromtimestamp(token_data["expires_at"])
    user.last_sync = datetime.now(timezone.utc).isoformat()

    saveUser(user)

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
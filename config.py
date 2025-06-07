import json

#config_path = os.getenv("CONFIG_PATH", "/etc/secrets/config.json")

# Charger la config
with open("config.json") as f:
    config = json.load(f)

def getConfig():
    return config
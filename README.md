# strava-to-notion

init bdd :
py init-db-py

update :
générer migration : python -m alembic revision --autogenerate -m "ajout colonne last_sync"
Run migration : python -m alembic upgrade head
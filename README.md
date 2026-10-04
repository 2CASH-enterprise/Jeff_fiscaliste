# Jeff

Assistant fiscal et social des TPE, PME et indépendants, d'abord au Cameroun.
WhatsApp est le fiscaliste, le dashboard est le coffre fiscal.

Le projet avance par lots numérotés (« Méthode de développement par lots »).

## Services

| Service | Rôle |
| --- | --- |
| `api` | FastAPI : webhooks, bulle web, dashboard, admin |
| `worker`, `beat` | Celery : tâches de fond et tâches planifiées |
| `db` | PostgreSQL 16 avec pgvector |
| `redis` | File de tâches |

## Démarrer sur le serveur

```bash
cp .env.example .env        # puis remplir les valeurs
docker compose up -d --build
docker compose exec api alembic upgrade head
curl http://127.0.0.1:8010/sante
```

## Tests

```bash
pip install -r requirements-dev.txt
DATABASE_URL=postgresql+psycopg://... pytest
```

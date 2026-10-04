"""Commande : prépare les rappels tout de suite, sans attendre la tâche de 7 h 30.

Sur le serveur : docker compose exec api python -m app.rappels.preparer
Pour un essai : ... python -m app.rappels.preparer 2026-10-08  (prépare comme si on était ce jour-là).
"""
import sys
from datetime import date

from app import models as _modeles  # noqa: F401 (toutes les tables, pour les clés étrangères)
from app.core.db import get_session
from app.rappels.preparation import preparer_rappels


def main(arguments: list[str]) -> int:
    try:
        jour = date.fromisoformat(arguments[0]) if arguments else None
    except ValueError:
        print("Date invalide : utilisez le format AAAA-MM-JJ, par exemple 2026-10-08.")
        return 1
    session = get_session()
    try:
        nombre = preparer_rappels(session, jour)
        session.commit()
    finally:
        session.close()
    print(f"Rappels préparés : {nombre}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

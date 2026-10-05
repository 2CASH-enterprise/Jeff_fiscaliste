"""Commande : charge le fichier de règles dans la base.

Sur le serveur : docker compose exec api python -m app.regles.charger
(par défaut le fichier du pays du déploiement, app/regles/donnees/regles_<pays>.json).
"""
import sys
from pathlib import Path

from app.core.config import get_settings
from app.core.db import get_session
from app.regles.chargement import ReglesInvalides, charger_fichier

DOSSIER = Path(__file__).resolve().parent / "donnees"


def main(arguments: list[str]) -> int:
    chemin = Path(arguments[0]) if arguments else DOSSIER / f"regles_{get_settings().juridiction.lower()}.json"
    session = get_session()
    try:
        bilan = charger_fichier(session, chemin)
        session.commit()
    except ReglesInvalides as erreur:
        session.rollback()
        print("Aucune règle n'a été chargée. Erreurs :")
        for ligne in erreur.erreurs:
            print(f"  - {ligne}")
        return 1
    finally:
        session.close()
    print(f"Fichier : {chemin.name}")
    print(f"Ajoutées : {len(bilan.ajoutees)} {', '.join(bilan.ajoutees)}")
    print(f"Statut modifié : {len(bilan.statut_modifie)} {', '.join(bilan.statut_modifie)}")
    print(f"Domaine modifié : {len(bilan.domaine_modifie)} {', '.join(bilan.domaine_modifie)}")
    print(f"Inchangées : {len(bilan.inchangees)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

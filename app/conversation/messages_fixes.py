"""Messages fixes de Jeff : écrits une fois, testés, jamais générés par l'IA.

Règle de ton : vouvoiement des clients, imposé par un test.
"""

ACCUEIL = "Bonjour, je suis Jeff, votre assistant fiscal. Que souhaitez-vous faire ?"

# Menu principal : mêmes choix sur WhatsApp et dans la bulle web.
MENU = (
    ("1", "Préparer ma déclaration"),
    ("2", "Voir mes obligations"),
    ("3", "Voir mes échéances"),
    ("4", "Poser une question"),
)

BIENTOT = "« {libelle} » sera bientôt disponible. Tapez « menu » pour revenir aux choix."

INCOMPRIS = "Je n'ai pas compris votre message. Tapez « menu » pour voir ce que je peux faire pour vous."

TROP_LONG = "Votre message est trop long. Pouvez-vous le raccourcir ?"

# Tous les messages fixes, pour les tests de ton.
TOUS = (ACCUEIL, BIENTOT, INCOMPRIS, TROP_LONG, *(libelle for _, libelle in MENU))

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


# --- Parcours d'onboarding (lot 3) ------------------------------------------------------

PROPOSITION_ONBOARDING = (
    "Pour cela, j'ai d'abord besoin de connaître votre entreprise : "
    "9 questions, environ 3 minutes. On commence ?"
)
CHOIX_PROPOSITION = (("oui", "Oui, commençons"), ("plus tard", "Plus tard"))
PLUS_TARD = "Très bien. Vous pourrez commencer quand vous le souhaitez depuis le menu."
PAUSE = "Le questionnaire est en pause. Tapez « reprendre » pour continuer, ou choisissez une option."
ANNULE = "Le questionnaire est annulé. Vos réponses n'ont pas été enregistrées."

Q_RAISON_SOCIALE = "Quelle est la raison sociale de votre entreprise ?"
Q_NIU = "Quel est votre numéro d'identifiant unique (NIU) ? Il figure sur votre attestation d'immatriculation."
Q_FORME_JURIDIQUE = "Quelle est la forme juridique de votre entreprise ?"
Q_SECTEUR = "Quel est votre secteur d'activité principal ?"
Q_CHIFFRE_AFFAIRES = (
    "Quel est votre chiffre d'affaires annuel hors taxes, en FCFA ? "
    "Par exemple : 150 000 000 ou 150 millions."
)
Q_CENTRE_IMPOTS = "À quel centre des impôts votre entreprise est-elle rattachée ?"
Q_REGIME = "Quel est votre régime d'imposition actuel ?"
Q_TVA = "Votre entreprise est-elle assujettie à la TVA ?"
Q_SALARIES = "Combien de salariés employez-vous ? Répondez 0 si vous n'en avez pas."
Q_CNPS = "Quel est votre numéro d'employeur à la CNPS ?"

ERR_TEXTE_COURT = "Cette réponse semble trop courte. Pouvez-vous la préciser ?"
ERR_TEXTE_LONG = "Cette réponse est trop longue. Pouvez-vous la raccourcir ?"
ERR_NIU = "Ce NIU ne semble pas valide : il ne doit contenir que des lettres et des chiffres. Pouvez-vous le vérifier ?"
NIU_DEJA_CONNU = (
    "Ce NIU est déjà associé à une entreprise dans Jeff. Pour votre sécurité, je ne peux pas "
    "vous y rattacher ici : contactez l'équipe Jeff. Si vous avez fait une erreur de saisie, "
    "envoyez le bon NIU."
)
ERR_CHOIX = "Je n'ai pas reconnu votre choix. Touchez l'un des boutons ou envoyez son numéro."
ERR_MONTANT = "Je n'ai pas compris ce montant. Écrivez-le en chiffres, par exemple 150 000 000 ou 150 millions."
ERR_NOMBRE = "Je n'ai pas compris ce nombre. Écrivez-le en chiffres, par exemple 3."
ERR_CNPS = "Ce numéro ne semble pas valide. Vérifiez-le, ou répondez « plus tard »."

RECAP_INTRO = "Voici le récapitulatif de vos réponses :"
RECAP_QUESTION = "Est-ce correct ?"
CHOIX_RECAP = (("oui", "Oui, c'est correct"), ("corriger", "Corriger"))
CORRECTION = "Quelle réponse souhaitez-vous corriger ?"
NE_SAIS_PAS = "Je ne sais pas"
A_COMPLETER = "À compléter"
BIENVENUE = (
    "C'est enregistré, merci ! Le profil de « {raison_sociale} » est créé. "
    "Choisissez « Voir mes obligations » pour connaître vos obligations fiscales et sociales."
)

TOUS = TOUS + (
    PROPOSITION_ONBOARDING, PLUS_TARD, PAUSE, ANNULE,
    Q_RAISON_SOCIALE, Q_NIU, Q_FORME_JURIDIQUE, Q_SECTEUR, Q_CHIFFRE_AFFAIRES, Q_CENTRE_IMPOTS,
    Q_REGIME, Q_TVA, Q_SALARIES, Q_CNPS,
    ERR_TEXTE_COURT, ERR_TEXTE_LONG, ERR_NIU, NIU_DEJA_CONNU, ERR_CHOIX, ERR_MONTANT, ERR_NOMBRE,
    ERR_CNPS, RECAP_INTRO, RECAP_QUESTION, CORRECTION, NE_SAIS_PAS, A_COMPLETER, BIENVENUE,
    *(libelle for _, libelle in CHOIX_PROPOSITION), *(libelle for _, libelle in CHOIX_RECAP),
)


# --- Obligations (lot 4) ------------------------------------------------------------------

OBLIGATIONS_INTRO = "Voici les obligations de « {raison_sociale} » d'après votre profil :"
OBLIGATIONS_A_CONFIRMER = "À confirmer, selon vos réponses « je ne sais pas » :"
OBLIGATIONS_ALERTES = "Points à vérifier :"
OBLIGATIONS_AUCUNE = (
    "Je n'ai trouvé aucune obligation pour votre profil dans mes règles actuelles. "
    "Elles sont encore en cours d'enrichissement."
)
OBLIGATIONS_AVERTISSEMENT = (
    "Ces informations sont en cours de validation par notre fiscaliste : "
    "vérifiez-les avant toute démarche."
)
OBLIGATIONS_ECHEANCE = "Échéance : {echeance}"
OBLIGATIONS_SOURCE = "Source : {source}"
A_CONFIRMER = "à confirmer"
SOURCE_A_COMPLETER = "à compléter"

TOUS = TOUS + (
    OBLIGATIONS_INTRO, OBLIGATIONS_A_CONFIRMER, OBLIGATIONS_ALERTES, OBLIGATIONS_AUCUNE,
    OBLIGATIONS_AVERTISSEMENT, OBLIGATIONS_ECHEANCE, OBLIGATIONS_SOURCE, A_CONFIRMER, SOURCE_A_COMPLETER,
)


# --- Échéances (lot 5) ---------------------------------------------------------------------

ECHEANCES_INTRO = "Voici les prochaines échéances de « {raison_sociale} » :"
ECHEANCES_LIGNE = "Au plus tard le {date} ({delai})"
ECHEANCES_WEEK_END = "Attention : cette date tombe un {jour}. Anticipez votre démarche."
ECHEANCES_FERIE = "Attention : cette date tombe un jour férié ({nom}). Anticipez votre démarche."
ECHEANCES_SANS_DATE = "Date à confirmer :"
ECHEANCES_PONCTUELLES = "À faire dès que possible :"
ECHEANCES_A_CONFIRMER = "À confirmer, selon vos réponses « je ne sais pas » :"
ECHEANCES_AUCUNE = (
    "Je n'ai trouvé aucune échéance pour votre profil dans mes règles actuelles. "
    "Elles sont encore en cours d'enrichissement."
)

TOUS = TOUS + (
    ECHEANCES_INTRO, ECHEANCES_LIGNE, ECHEANCES_WEEK_END, ECHEANCES_FERIE, ECHEANCES_SANS_DATE,
    ECHEANCES_PONCTUELLES, ECHEANCES_A_CONFIRMER, ECHEANCES_AUCUNE,
)

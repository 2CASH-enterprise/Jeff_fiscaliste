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
    ("5", "Mon entreprise"),
)

BIENTOT = "« {libelle} » sera bientôt disponible. Tapez « menu » pour revenir aux choix."

INCOMPRIS = "Je n'ai pas compris votre message. Tapez « menu » pour voir ce que je peux faire pour vous."

TROP_LONG = "Votre message est trop long. Pouvez-vous le raccourcir ?"

# Tous les messages fixes, pour les tests de ton.
TOUS = (ACCUEIL, BIENTOT, INCOMPRIS, TROP_LONG, *(libelle for _, libelle in MENU))


# --- Parcours d'onboarding (lot 3) ------------------------------------------------------

PROPOSITION_ONBOARDING = (
    "Pour cela, j'ai d'abord besoin de connaître votre entreprise : "
    "une dizaine de questions, environ 3 minutes. On commence ?"
)
CHOIX_PROPOSITION = (("oui", "Oui, commençons"), ("plus tard", "Plus tard"), ("deja", "J'ai déjà un profil"))
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


# --- Profil de l'entreprise (lot 6) -------------------------------------------------------

PROFIL_INTRO = "Voici le profil de « {raison_sociale} » :"
NON_MODIFIABLE = "non modifiable"
PROFIL_NIU = "Le NIU ne peut pas être modifié ici. En cas d'erreur, contactez l'équipe Jeff."
CHOIX_PROFIL = (("modifier", "Modifier mon profil"), ("menu", "Retour au menu"))
MODIFICATION_QUELLE = "Quelle information souhaitez-vous modifier ?"
MODIFICATION_RECAP_INTRO = "Voici votre profil avec vos modifications :"
MODIFICATION_RECAP_QUESTION = "Enregistrer ces modifications ?"
CHOIX_RECAP_MODIFICATION = (("oui", "Oui, enregistrer"), ("corriger", "Modifier autre chose"))
MODIFICATION_ANNULEE = "La modification est annulée. Votre profil n'a pas changé."
PROFIL_A_JOUR = (
    "Votre profil est à jour. Choisissez « Voir mes obligations » pour vérifier "
    "vos obligations après ces changements."
)
PROFIL_INCHANGE = "Vous n'avez rien modifié : votre profil reste inchangé."

TOUS = TOUS + (
    PROFIL_INTRO, NON_MODIFIABLE, PROFIL_NIU, MODIFICATION_QUELLE, MODIFICATION_RECAP_INTRO,
    MODIFICATION_RECAP_QUESTION, MODIFICATION_ANNULEE, PROFIL_A_JOUR, PROFIL_INCHANGE,
    *(libelle for _, libelle in CHOIX_PROFIL), *(libelle for _, libelle in CHOIX_RECAP_MODIFICATION),
)


# --- Rappels (lot 7) ------------------------------------------------------------------------

RAPPEL = "Rappel : « {titre} » — {periode}."

TOUS = TOUS + (RAPPEL,)


# --- Adresse email (lot 8) ------------------------------------------------------------------

Q_EMAIL = (
    "Quelle est votre adresse email ? Elle sert à vous envoyer vos rappels d'échéances. "
    "Vous pouvez aussi répondre « plus tard »."
)
ERR_EMAIL = "Cette adresse email ne semble pas valide. Vérifiez-la, par exemple nom@entreprise.cm, ou répondez « plus tard »."
EMAIL_A_CONFIRMER = "à confirmer"
CHOIX_EMAIL = (("plus tard", "Je la donnerai plus tard"),)

CODE_ENVOYE = (
    "Je vous envoie un code à 6 chiffres à {email}. Recopiez-le ici pour confirmer votre adresse : "
    "vos rappels partiront ensuite par email. Le code est valable 15 minutes."
)
CODE_RENVOYE = "Je vous ai envoyé un nouveau code à {email}. Recopiez-le ici."
CODE_FORMAT = (
    "Le code contient 6 chiffres. Recopiez-le, tapez « renvoyer » pour en recevoir un nouveau, "
    "ou « menu » pour revenir aux choix."
)
CODE_ATTENDU = "Recopiez le code à 6 chiffres envoyé à {email}, ou tapez « renvoyer » pour en recevoir un nouveau."
CODE_FAUX = "Ce code ne correspond pas. Vérifiez-le et réessayez, ou tapez « renvoyer »."
CODE_EXPIRE = "Ce code a expiré. Tapez « renvoyer » pour en recevoir un nouveau."
CODE_TROP_D_ESSAIS = (
    "Trop d'essais. Votre adresse n'est pas confirmée : vos rappels restent dans cette conversation. "
    "Vous pourrez recommencer depuis « Mon entreprise »."
)
CODE_TROP_DE_RENVOIS = "Vous avez déjà demandé plusieurs codes. Utilisez le dernier reçu, ou réessayez plus tard depuis « Mon entreprise »."
EMAIL_CONFIRME = "Votre adresse {email} est confirmée. Vos prochains rappels partiront par email."
CONFIRMATION_ANNULEE = "La confirmation est annulée. Vos rappels restent dans cette conversation."
CHOIX_CODE = (("renvoyer", "Renvoyer le code"),)
CHOIX_CONFIRMER = ("confirmer", "Confirmer mon email")

EMAIL_SIGNATURE = "Jeff, votre assistant fiscal."
EMAIL_DESABONNEMENT = (
    "Pour ne plus recevoir ces rappels par email, écrivez à Jeff : « 5 » (Mon entreprise), "
    "« Modifier mon profil », puis l'adresse email, et répondez « supprimer »."
)
EMAIL_CODE_OBJET = "Votre code de confirmation Jeff"
EMAIL_CODE_TEXTE = (
    "Bonjour,\n\nVotre code de confirmation Jeff est : {code}\n\n"
    "Il est valable 15 minutes. Recopiez-le dans votre conversation avec Jeff.\n"
    "Si vous n'êtes pas à l'origine de cette demande, ignorez simplement cet email."
)
EMAIL_RAPPEL_OBJET = "Rappel Jeff : {titre}, au plus tard le {date}"
EMAIL_RAPPEL_INTRO = "Bonjour,\n\nVoici un rappel pour « {raison_sociale} » :"
EMAIL_TEST_OBJET = "Jeff : email de test"
EMAIL_TEST_TEXTE = "Bonjour,\n\nCet email de test confirme que Jeff peut envoyer des emails depuis le serveur."

TOUS = TOUS + (
    Q_EMAIL, ERR_EMAIL, EMAIL_A_CONFIRMER, CODE_ENVOYE, CODE_RENVOYE, CODE_FORMAT, CODE_FAUX, CODE_EXPIRE,
    CODE_TROP_D_ESSAIS, CODE_TROP_DE_RENVOIS, EMAIL_CONFIRME, CONFIRMATION_ANNULEE, EMAIL_SIGNATURE,
    EMAIL_DESABONNEMENT, CODE_ATTENDU,
    EMAIL_CODE_OBJET, EMAIL_CODE_TEXTE, EMAIL_RAPPEL_OBJET, EMAIL_RAPPEL_INTRO, EMAIL_TEST_OBJET, EMAIL_TEST_TEXTE,
    *(libelle for _, libelle in CHOIX_EMAIL), *(libelle for _, libelle in CHOIX_CODE), CHOIX_CONFIRMER[1],
)


# --- Liaison d'une conversation à un profil existant (lot 9) ----------------------------------

LIAISON_EMAIL = (
    "Quelle est l'adresse email confirmée de votre profil Jeff ? Je vous y enverrai un code "
    "pour relier cette conversation à votre entreprise."
)
LIAISON_CODE_ENVOYE = (
    "Si cette adresse correspond à un profil Jeff confirmé, vous allez recevoir un code à 6 chiffres. "
    "Recopiez-le ici (valable 15 minutes), ou tapez « annuler »."
)
LIAISON_CODE_ATTENDU = "Recopiez le code à 6 chiffres reçu par email, tapez « renvoyer » pour en recevoir un nouveau, ou « annuler »."
LIAISON_OK = "C'est fait : cette conversation est reliée au profil de « {raison_sociale} »."
LIAISON_ANNULEE = "La liaison est annulée. Tapez « menu » pour voir les choix, ou « 1 » pour créer un profil."
LIAISON_TROP_D_ESSAIS = "Trop d'essais : la liaison est annulée. Vous pourrez réessayer plus tard depuis le menu."
EMAIL_LIAISON_OBJET = "Votre code Jeff pour relier une conversation"
EMAIL_LIAISON_TEXTE = (
    "Bonjour,\n\nUne demande a été faite pour relier une nouvelle conversation (WhatsApp ou web) "
    "à votre profil Jeff ({entreprises}).\n\nVotre code : {code}\n\n"
    "Il est valable 15 minutes. Si vous n'êtes pas à l'origine de cette demande, ignorez cet email : "
    "rien ne sera relié sans ce code."
)

# --- WhatsApp (lot 9) ---------------------------------------------------------------------------

WA_TYPE_NON_PRIS = "Je ne lis que les messages écrits pour l'instant. Écrivez votre demande, ou tapez « menu »."
WA_BOUTON_LISTE = "Voir les choix"
WA_VOTRE_CHOIX = "Votre choix :"

TOUS = TOUS + (
    LIAISON_EMAIL, LIAISON_CODE_ENVOYE, LIAISON_CODE_ATTENDU, LIAISON_OK, LIAISON_ANNULEE, LIAISON_TROP_D_ESSAIS,
    EMAIL_LIAISON_OBJET, EMAIL_LIAISON_TEXTE, WA_TYPE_NON_PRIS, WA_BOUTON_LISTE, WA_VOTRE_CHOIX,
    CHOIX_PROPOSITION[2][1],
)


# --- Modèle WhatsApp des rappels (lot 10), soumis à Meta -----------------------------------------
# {{1}} raison sociale, {{2}} obligation, {{3}} période, {{4}} date limite. Une variable ne doit
# ni ouvrir ni fermer le texte, et deux variables ne se suivent jamais (règles de Meta).

MODELE_RAPPEL_TEXTE = (
    "Bonjour, ceci est un rappel de Jeff pour « {{1}} » : {{2}}, période {{3}}, "
    "à faire au plus tard le {{4}}. Répondez à ce message pour voir vos échéances ou poser une question."
)
MODELE_RAPPEL_EXEMPLE = ("Ets BABA", "Déclaration et paiement mensuels de la TVA", "septembre 2026", "jeudi 15 octobre 2026")

TOUS = TOUS + (MODELE_RAPPEL_TEXTE,)


# --- Lot 11 : choix de l'entreprise à relier, arrêt des rappels WhatsApp ------------------------

LIAISON_CHOIX = "Cette adresse est associée à plusieurs entreprises. Laquelle voulez-vous relier à cette conversation ?"
WA_STOP = (
    "C'est noté : je ne vous enverrai plus de rappels sur WhatsApp. Vous les recevrez par email si votre "
    "adresse est confirmée, sinon au prochain message que vous m'écrirez. "
    "Écrivez « reprendre les rappels » pour les réactiver."
)
WA_RAPPELS_REPRIS = "C'est noté : vos rappels d'échéances reviennent sur WhatsApp."

TOUS = TOUS + (LIAISON_CHOIX, WA_STOP, WA_RAPPELS_REPRIS)

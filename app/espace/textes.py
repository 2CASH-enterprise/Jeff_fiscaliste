"""Textes fixes du coffre fiscal (lot 12). Toujours au vouvoiement : vérifié par les tests."""

TITRE = "Votre coffre fiscal"
CONNEXION_INTRO = "Entrez l'adresse email confirmée avec Jeff. Vous recevrez un code à 6 chiffres."
CONNEXION_BOUTON = "Recevoir le code"
CONNEXION_PIED = "Pas encore de profil ? Écrivez à Jeff sur WhatsApp pour le créer."
SESSION_DUREE = "Une fois connecté, vous le restez 30 jours sur cet appareil."
ERR_EMAIL = "Cette adresse email ne semble pas valide. Vérifiez-la et réessayez."
TROP_DE_DEMANDES = "Vous avez demandé plusieurs codes en peu de temps. Réessayez dans une heure."

CODE_TITRE = "Entrez votre code"
CODE_ENVOYE = (
    "Si l'adresse {email} correspond à un profil Jeff confirmé, vous allez recevoir un code à 6 chiffres. "
    "Il est valable 15 minutes."
)
CODE_BOUTON = "Se connecter"
CODE_RENVOYER = "Renvoyer le code"
CODE_AUTRE_ADRESSE = "Utiliser une autre adresse"
CODE_RENVOYE = "Un nouveau code vient de partir, si l'adresse correspond à un profil confirmé."
CODE_FORMAT = "Le code contient 6 chiffres. Recopiez-le tel qu'il apparaît dans l'email."
CODE_FAUX = "Ce code ne correspond pas. Vérifiez le dernier email reçu et réessayez."
CODE_EXPIRE = "Ce code a expiré. Demandez-en un nouveau avec « Renvoyer le code »."
CODE_TROP_DE_RENVOIS = "Vous avez déjà demandé plusieurs codes. Utilisez le dernier reçu, ou recommencez dans une heure."
CODE_TROP_D_ESSAIS = "Trop d'essais : ce code n'est plus valable. Recommencez avec votre adresse email."
CODE_INVALIDE = "Cette demande de connexion n'est plus valable. Recommencez avec votre adresse email."
CONNEXION_IMPOSSIBLE = "Aucune entreprise n'est plus confirmée pour cette adresse. Recommencez avec votre adresse email."
DECONNECTE = "Vous êtes déconnecté. À bientôt."

CHOIX_TITRE = "Choisissez une entreprise"
CHOIX_INTRO = "Plusieurs entreprises sont reliées à votre adresse email."
CHOIX_PIED = "Vous pourrez changer d'entreprise à tout moment depuis le haut de l'écran."

ONGLETS = (
    ("accueil", "Accueil"),
    ("echeances", "Échéances"),
    ("obligations", "Obligations"),
    ("documents", "Documents"),
    ("entreprise", "Mon entreprise"),
)
ONGLET_COURT = {"entreprise": "Entreprise"}  # Barre du bas sur téléphone : place comptée.
DECONNEXION = "Se déconnecter"
CHANGER_ENTREPRISE = "Changer d'entreprise"

BONJOUR = "Bonjour"
PROCHAINE_ECHEANCE = "Prochaine échéance"
PERIODE = "Période : {periode}"
A_FAIRE_AVANT = "À faire au plus tard le {date}"
JOURS_RESTANTS = "jours restants"
AUJOURD_HUI = "C'est aujourd'hui"
DEMAIN = "C'est demain"
AUCUNE_ECHEANCE = "Aucune échéance datée pour votre entreprise pour l'instant."
A_VENIR = "Ensuite"
A_CONFIRMER = "À confirmer"
A_CONFIRMER_INTRO = "Ces obligations dépendent d'informations que Jeff n'a pas encore :"
A_CONFIRMER_AIDE = "Complétez votre profil en écrivant « 5 » à Jeff, puis « Modifier mon profil »."
SANS_DATE = "Obligations sans date fixe"
EN_CHIFFRES = "En un coup d'œil"
OBLIGATIONS_SUIVIES = "obligations suivies"
OBLIGATIONS_A_CONFIRMER = "à confirmer"
AVERTISSEMENT_VALIDATION = (
    "Certaines règles sont en attente de validation par un fiscaliste. En cas de doute, demandez à Jeff."
)

BIENTOT_TITRE = "Bientôt disponible"
BIENTOT = {
    "documents": "Vous pourrez bientôt déposer ici vos factures, bulletins de paie et déclarations, en photo ou en PDF.",
}

PROFIL = "Profil"
NIU_VERROUILLE = "non modifiable"
CONTACT = "Contact"
EMAIL = "Email"
EMAIL_CONFIRMEE = "Confirmée"
WHATSAPP = "WhatsApp"
WHATSAPP_RELIE = "Relié"
WHATSAPP_AUCUN = "Aucun numéro relié"
RAPPELS = "Rappels"
RAPPELS_WHATSAPP = "Rappels WhatsApp"
RAPPELS_EMAIL = "Rappels par email"
ACTIFS = "Actifs"
ARRETES = "Arrêtés"
MODIFIER_AIDE = (
    "Pour modifier ces informations, écrivez « 5 » à Jeff (Mon entreprise), puis « Modifier mon profil ». "
    "Le NIU ne se modifie pas."
)

# --- Lot 13 : Échéances et Obligations ---------------------------------------------------------

MOIS_PRECEDENT = "Mois précédent"
MOIS_SUIVANT = "Mois suivant"
ECHEANCES_DATEES = "Dates limites"
AUCUNE_DATE_CE_MOIS = "Aucune date limite connue ce mois-ci."
DATE_A_CONFIRMER = "Date à confirmer"
DATE_A_CONFIRMER_AIDE = "Ces obligations reviennent chaque mois ; leur date limite sera ajoutée après validation par un fiscaliste."
SANS_DATE_CONNUE = "Autres obligations sans date connue"
PASSEE = "Date passée"
RAPPEL_PREVU = "Rappel J-{palier} le {date}"
INCERTAINES_LIEN = "{nombre} obligation(s) à confirmer selon votre profil"
VOIR_DETAIL = "Voir le détail"
VOIR_CALENDRIER = "Voir le calendrier"
VOIR_OBLIGATIONS = "Voir vos obligations"

FILTRES = (("fiscales", "Fiscales"), ("sociales", "Sociales"), ("a_confirmer", "À confirmer"))
FILTRE_VIDE = {
    "fiscales": "Aucune obligation fiscale ne ressort de votre profil pour l'instant.",
    "sociales": "Aucune obligation sociale ne ressort de votre profil pour l'instant.",
    "a_confirmer": "Rien à confirmer : votre profil permet à Jeff de trancher pour chaque obligation.",
}
POINTS_ATTENTION = "Points d'attention"
FREQUENCE = "Fréquence"
ECHEANCE = "Échéance"
PROCHAINE_DATE = "Prochaine date limite"
SOURCE = "Source"
OUVRIR_SOURCE = "Ouvrir la source"
POURQUOI = "Pourquoi cette obligation ?"
POURQUOI_A_CONFIRMER = "Pourquoi à confirmer ?"
D_APRES_PROFIL = "D'après votre profil :"
INFORMATIONS_MANQUANTES = "Jeff n'a pas encore ces informations :"
TOUTES_LES_ENTREPRISES = "Cette règle s'applique à toutes les entreprises."
EN_ATTENTE_VALIDATION = "En attente de validation"
VALIDATION_DETAIL = "Cette règle n'a pas encore été validée par un fiscaliste. En cas de doute, demandez à Jeff."
SANS_SOURCE = "Source à préciser par le fiscaliste."

EMAIL_CONNEXION_OBJET = "Votre code de connexion Jeff"
EMAIL_CONNEXION_TEXTE = (
    "Bonjour,\n\nVoici votre code pour ouvrir votre coffre fiscal Jeff ({entreprises}) : {code}\n\n"
    "Il est valable 15 minutes. Si vous n'êtes pas à l'origine de cette demande, ignorez cet email : "
    "personne ne peut ouvrir votre coffre sans ce code."
)

TOUS = (
    TITRE, CONNEXION_INTRO, CONNEXION_BOUTON, CONNEXION_PIED, SESSION_DUREE, ERR_EMAIL, TROP_DE_DEMANDES,
    CODE_TITRE, CODE_ENVOYE, CODE_BOUTON, CODE_RENVOYER, CODE_AUTRE_ADRESSE, CODE_RENVOYE, CODE_FORMAT, CODE_FAUX,
    CODE_EXPIRE, CODE_TROP_DE_RENVOIS, CODE_TROP_D_ESSAIS, CODE_INVALIDE, CONNEXION_IMPOSSIBLE, DECONNECTE,
    CHOIX_TITRE, CHOIX_INTRO, CHOIX_PIED, *(l for _, l in ONGLETS), *ONGLET_COURT.values(), DECONNEXION,
    CHANGER_ENTREPRISE, BONJOUR, PROCHAINE_ECHEANCE, PERIODE, A_FAIRE_AVANT, JOURS_RESTANTS, AUJOURD_HUI, DEMAIN,
    AUCUNE_ECHEANCE, A_VENIR, A_CONFIRMER, A_CONFIRMER_INTRO, A_CONFIRMER_AIDE, SANS_DATE, EN_CHIFFRES,
    OBLIGATIONS_SUIVIES, OBLIGATIONS_A_CONFIRMER, AVERTISSEMENT_VALIDATION, BIENTOT_TITRE, *BIENTOT.values(),
    PROFIL, NIU_VERROUILLE, CONTACT, EMAIL, EMAIL_CONFIRMEE, WHATSAPP, WHATSAPP_RELIE, WHATSAPP_AUCUN, RAPPELS,
    RAPPELS_WHATSAPP, RAPPELS_EMAIL, ACTIFS, ARRETES, MODIFIER_AIDE, EMAIL_CONNEXION_OBJET, EMAIL_CONNEXION_TEXTE,
    MOIS_PRECEDENT, MOIS_SUIVANT, ECHEANCES_DATEES, AUCUNE_DATE_CE_MOIS, DATE_A_CONFIRMER, DATE_A_CONFIRMER_AIDE,
    SANS_DATE_CONNUE, PASSEE, RAPPEL_PREVU, INCERTAINES_LIEN, VOIR_DETAIL, VOIR_CALENDRIER, VOIR_OBLIGATIONS,
    *(l for _, l in FILTRES), *FILTRE_VIDE.values(), POINTS_ATTENTION, FREQUENCE, ECHEANCE, PROCHAINE_DATE, SOURCE,
    OUVRIR_SOURCE, POURQUOI, POURQUOI_A_CONFIRMER, D_APRES_PROFIL, INFORMATIONS_MANQUANTES, TOUTES_LES_ENTREPRISES,
    EN_ATTENTE_VALIDATION, VALIDATION_DETAIL, SANS_SOURCE,
)

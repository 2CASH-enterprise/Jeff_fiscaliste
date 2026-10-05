"""Profil de l'entreprise (lot 6) : le consulter, le modifier, garder la trace des changements.

La modification réutilise les questions, contrôles et récapitulatif de l'onboarding. Elle met
à jour l'entreprise existante (jamais de nouvelle entreprise) et enregistre, champ par champ,
l'ancienne et la nouvelle valeur. Le NIU est affiché mais ne se modifie pas ici.
"""
from sqlalchemy.orm import Session

from app.conversation import confirmation, onboarding
from app.conversation import messages_fixes as mf
from app.conversation.models import TERMINE, Conversation, Parcours
from app.conversation.normalisation import normaliser
from app.conversation.onboarding import CORRECTION, CORRIGER, INCONNU, MODIFICATION, OUI, RECAPITULATIF, RETOUR_RECAP
from app.conversation.reponse import Reponse
from app.entreprises.models import Entreprise, ModificationEntreprise

CNPS = "numero_employeur_cnps"
ORIGINE = "_origine"  # Profil au début de la modification, pour ne toucher qu'aux champs changés.
TYPE = MODIFICATION


def donnees_depuis_entreprise(entreprise: Entreprise) -> dict:
    """Profil enregistré → réponses du questionnaire, pour pré-remplir la modification."""
    tva = entreprise.assujetti_tva_declare
    donnees = {
        "raison_sociale": entreprise.raison_sociale,
        "niu": entreprise.niu,
        "forme_juridique": entreprise.forme_juridique,
        "secteur": entreprise.secteur,
        "chiffre_affaires_annuel": entreprise.chiffre_affaires_annuel,
        "centre_impots": entreprise.centre_impots,
        "regime_declare": entreprise.regime_declare,
        "assujetti_tva_declare": INCONNU if tva is None else ("oui" if tva else "non"),
        "nombre_salaries": entreprise.nombre_salaries,
    }
    if onboarding.PAR_CLE[CNPS].condition(donnees):
        donnees[CNPS] = entreprise.numero_employeur_cnps
    donnees["email"] = entreprise.email
    return donnees


def email_a_confirmer(entreprise: Entreprise) -> bool:
    return bool(entreprise.email) and entreprise.email_confirme_le is None


def voir_profil(entreprise: Entreprise) -> Reponse:
    donnees = donnees_depuis_entreprise(entreprise)
    lignes = onboarding.lignes_profil(donnees, niu_verrouille=True)
    choix = list(mf.CHOIX_PROFIL)
    if email_a_confirmer(entreprise):
        lignes[-1] += f" ({mf.EMAIL_A_CONFIRMER})"
        choix.insert(1, mf.CHOIX_CONFIRMER)
    texte = "\n".join([
        mf.PROFIL_INTRO.format(raison_sociale=entreprise.raison_sociale),
        *lignes,
        "",
        mf.PROFIL_NIU,
    ])
    return Reponse(texte, choix)


def demarrer(session: Session, conversation: Conversation, entreprise: Entreprise) -> Reponse:
    """Ouvre directement le choix de l'information à modifier ; chaque réponse ramène au récapitulatif."""
    origine = donnees_depuis_entreprise(entreprise)
    parcours = Parcours(
        conversation_id=conversation.id,
        type=TYPE,
        etape=CORRECTION,
        donnees={**origine, RETOUR_RECAP: True, ORIGINE: origine},
    )
    session.add(parcours)
    session.flush()
    return onboarding.question(parcours)


def avancer(session: Session, conversation: Conversation, parcours: Parcours, texte: str) -> Reponse:
    if parcours.etape == RECAPITULATIF:
        mots = normaliser(texte)
        if mots in OUI:
            return finaliser(session, conversation, parcours)
        if mots in CORRIGER:
            parcours.etape = CORRECTION
            return onboarding.question(parcours)
        return Reponse(mf.ERR_CHOIX, list(mf.CHOIX_RECAP_MODIFICATION))
    return onboarding.avancer(session, conversation, parcours, texte)


def nouvelles_valeurs(donnees: dict) -> dict:
    valeurs = onboarding.colonnes(donnees)
    # Sans la question CNPS (aucun salarié), le numéro déjà enregistré est conservé.
    if CNPS in donnees:
        valeurs[CNPS] = donnees[CNPS]
    return valeurs


def finaliser(session: Session, conversation: Conversation, parcours: Parcours) -> Reponse:
    entreprise = session.get(Entreprise, conversation.entreprise_id)
    parcours.statut = TERMINE
    avant = nouvelles_valeurs(parcours.donnees[ORIGINE])
    changements = 0
    for champ, nouvelle in nouvelles_valeurs(parcours.donnees).items():
        # Seuls les champs changés par le client pendant ce parcours sont écrits : une autre
        # modification enregistrée entre-temps (autre canal) n'est pas écrasée.
        if champ in avant and avant[champ] == nouvelle:
            continue
        ancienne = getattr(entreprise, champ)
        if ancienne == nouvelle:
            continue
        session.add(ModificationEntreprise(
            entreprise_id=entreprise.id,
            conversation_id=conversation.id,
            champ=champ,
            ancienne_valeur=ancienne,
            nouvelle_valeur=nouvelle,
        ))
        setattr(entreprise, champ, nouvelle)
        changements += 1
        if champ == "email":
            # Une nouvelle adresse doit être confirmée avant de recevoir des rappels.
            entreprise.email_confirme_le = None
    session.flush()
    if changements == 0:
        return Reponse(mf.PROFIL_INCHANGE, list(mf.MENU))
    if email_a_confirmer(entreprise):
        code = confirmation.demarrer(session, conversation, entreprise)
        return Reponse(mf.PROFIL_A_JOUR + "\n\n" + code.texte, code.choix)
    return Reponse(mf.PROFIL_A_JOUR, list(mf.MENU))

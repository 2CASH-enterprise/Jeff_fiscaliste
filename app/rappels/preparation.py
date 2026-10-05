"""Préparation des rappels : chaque matin, pour chaque entreprise, les échéances proches.

Décisions du lot 7 : rappels à J-7 et J-2, uniquement pour les obligations datées et certaines.
Si l'échéance tombe un week-end ou un jour férié, le rappel arrive au plus tard le dernier jour
ouvré qui la précède. Si deux paliers sont dus en même temps (client inscrit tard, tâche
manquée), seul le plus urgent est créé.
"""
from datetime import date, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.calendrier.dates import prochaine_echeance
from app.calendrier.feries import jour_ferie
from app.core.temps import aujourd_hui
from app.emails import models as emails
from app.emails.composition import email_rappel
from app.entreprises.models import Entreprise
from app.calendrier.dates import formater_date
from app.rappels.canal import EMAIL, WHATSAPP, choisir
from app.rappels.models import A_ENVOYER, IGNORE, Rappel
from app.referentiel.models import Juridiction
from app.regles.conditions import INCERTAIN
from app.regles.models import OBLIGATION
from app.regles.moteur import evaluer_entreprise

PALIERS = (7, 2)


def jour_ouvre(jour: date) -> bool:
    return jour.weekday() < 5 and jour_ferie(jour) is None


def date_prevue(date_limite: date, palier: int) -> date:
    prevue = date_limite - timedelta(days=palier)
    if not jour_ouvre(date_limite):
        dernier_ouvre = date_limite - timedelta(days=1)
        while not jour_ouvre(dernier_ouvre):
            dernier_ouvre -= timedelta(days=1)
        prevue = min(prevue, dernier_ouvre)
    return prevue


def preparer_entreprise(
    session: Session, entreprise: Entreprise, ce_jour: date, maintenant: datetime | None = None
) -> list[Rappel]:
    from app.whatsapp import models as whatsapp

    fuseau = session.get(Juridiction, entreprise.juridiction_code).fuseau_horaire
    crees = []
    for resultat in evaluer_entreprise(session, entreprise, ce_jour):
        regle = resultat.regle
        if regle.type != OBLIGATION or resultat.applicabilite == INCERTAIN or not regle.echeance_calcul:
            continue
        echeance = prochaine_echeance(regle.echeance_calcul, ce_jour)
        dus = [p for p in PALIERS if date_prevue(echeance.date_limite, p) <= ce_jour]
        if not dus:
            continue
        palier = min(dus)
        existants = list(session.scalars(select(Rappel).where(
            Rappel.entreprise_id == entreprise.id,
            Rappel.regle_code == regle.code,
            Rappel.date_limite == echeance.date_limite,
        )))
        if any(r.palier <= palier for r in existants):
            continue
        for ancien in existants:
            if ancien.statut == A_ENVOYER:
                ancien.statut = IGNORE
                session.execute(
                    update(emails.Email)
                    .where(emails.Email.rappel_id == ancien.id, emails.Email.statut == emails.A_ENVOYER)
                    .values(statut=emails.ANNULE)
                )
                session.execute(
                    update(whatsapp.WhatsappEnvoi)
                    .where(whatsapp.WhatsappEnvoi.rappel_id == ancien.id, whatsapp.WhatsappEnvoi.statut == whatsapp.A_ENVOYER)
                    .values(statut=whatsapp.ANNULE)
                )
        rappel = Rappel(
            entreprise_id=entreprise.id,
            regle_id=regle.id,
            regle_code=regle.code,
            periode=echeance.periode,
            date_limite=echeance.date_limite,
            palier=palier,
            date_prevue=date_prevue(echeance.date_limite, palier),
            statut=A_ENVOYER,
        )
        choix = choisir(session, entreprise, palier, maintenant, fuseau)
        rappel.canal = choix.canal
        session.add(rappel)
        session.flush()
        if rappel.canal == EMAIL:
            email_rappel(session, entreprise, rappel, regle, ce_jour)
        elif rappel.canal == WHATSAPP:
            whatsapp_rappel(session, entreprise, rappel, regle, ce_jour, choix)
        crees.append(rappel)
    session.flush()
    return crees


def preparer_rappels(session: Session, jour: date | None = None) -> int:
    """Prépare les rappels de toutes les entreprises des juridictions actives. Renvoie le nombre créé."""
    total = 0
    for juridiction in session.scalars(select(Juridiction).where(Juridiction.active.is_(True))):
        ce_jour = jour or aujourd_hui(juridiction.fuseau_horaire)
        entreprises = session.scalars(
            select(Entreprise).where(Entreprise.juridiction_code == juridiction.code).order_by(Entreprise.cree_le)
        )
        for entreprise in entreprises:
            total += len(preparer_entreprise(session, entreprise, ce_jour))
    return total


def whatsapp_rappel(session: Session, entreprise: Entreprise, rappel: Rappel, regle, ce_jour: date, choix) -> None:
    """Message libre dans la fenêtre de 24 h, sinon le modèle Meta (message prioritaire)."""
    from app.rappels.livraison import texte_rappel
    from app.whatsapp import format
    from app.whatsapp.models import A_ENVOYER as EN_ATTENTE, WhatsappEnvoi

    if choix.modele:
        valeurs = [entreprise.raison_sociale, regle.titre, rappel.periode, formater_date(rappel.date_limite)]
        contenus = [format.modele(choix.modele, valeurs)]
    else:
        contenus = format.textes(texte_rappel(rappel, regle, ce_jour))
    for contenu in contenus:
        session.add(WhatsappEnvoi(
            conversation_id=choix.conversation.id,
            destinataire=choix.conversation.identifiant_externe,
            contenu=contenu,
            statut=EN_ATTENTE,
            essais=0,
            entreprise_id=entreprise.id,
            rappel_id=rappel.id,
            modele=choix.modele,
        ))
    rappel.conversation_id = choix.conversation.id
    session.flush()

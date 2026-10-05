"""Rédaction des emails (texte et HTML) et dépôt dans la boîte d'envoi. Aucun envoi ici."""
import uuid
from html import escape

from sqlalchemy.orm import Session

from app.conversation import messages_fixes as mf
from app.emails.models import A_ENVOYER, CODE, RAPPEL, Email

OBJET_MAX = 200


def html_depuis_texte(texte: str) -> str:
    """Version HTML d'un texte : chaque paragraphe échappé (aucun HTML venu du client n'est interprété)."""
    paragraphes = "".join(
        '<p style="margin:0 0 12px">' + escape(p).replace("\n", "<br>") + "</p>" for p in texte.split("\n\n")
    )
    return (
        '<!doctype html><html lang="fr"><body style="margin:0;background:#f4f7fa;'
        'font-family:Arial,Helvetica,sans-serif;color:#1d2630;line-height:1.5">'
        '<div style="max-width:560px;margin:0 auto;padding:16px">'
        '<div style="background:#4680ff;color:#ffffff;padding:12px 16px;border-radius:8px 8px 0 0;'
        'font-weight:bold;font-size:18px">Jeff</div>'
        f'<div style="background:#ffffff;padding:16px;border-radius:0 0 8px 8px">{paragraphes}</div>'
        "</div></body></html>"
    )


def deposer(
    session: Session,
    type_: str,
    destinataire: str,
    objet: str,
    texte: str,
    entreprise_id: uuid.UUID | None = None,
    rappel_id: int | None = None,
) -> Email:
    email = Email(
        type=type_,
        destinataire=destinataire,
        objet=objet[:OBJET_MAX],
        texte=texte,
        html=html_depuis_texte(texte),
        entreprise_id=entreprise_id,
        rappel_id=rappel_id,
        statut=A_ENVOYER,
        essais=0,
    )
    session.add(email)
    session.flush()
    return email


def email_code(session: Session, entreprise_id: uuid.UUID, destinataire: str, code: str) -> Email:
    texte = mf.EMAIL_CODE_TEXTE.format(code=code) + "\n\n" + mf.EMAIL_SIGNATURE
    return deposer(session, CODE, destinataire, mf.EMAIL_CODE_OBJET, texte, entreprise_id)


def email_rappel(session: Session, entreprise, rappel, regle, ce_jour) -> Email:
    """Même contenu que le rappel de la bulle, avec l'entreprise, la signature et le désabonnement."""
    from app.calendrier.dates import formater_date
    from app.rappels.livraison import texte_rappel

    texte = "\n\n".join([
        mf.EMAIL_RAPPEL_INTRO.format(raison_sociale=entreprise.raison_sociale),
        texte_rappel(rappel, regle, ce_jour),
        mf.EMAIL_SIGNATURE,
        mf.EMAIL_DESABONNEMENT,
    ])
    objet = mf.EMAIL_RAPPEL_OBJET.format(titre=regle.titre, date=formater_date(rappel.date_limite))
    return deposer(session, RAPPEL, entreprise.email, objet, texte, entreprise.id, rappel.id)


def email_liaison(session: Session, entreprises: list, code: str) -> Email:
    """Un seul email, même si l'adresse est confirmée pour plusieurs entreprises (lot 11)."""
    noms = ", ".join(f"« {e.raison_sociale} »" for e in entreprises)
    texte = mf.EMAIL_LIAISON_TEXTE.format(entreprises=noms, code=code) + "\n\n" + mf.EMAIL_SIGNATURE
    premiere = entreprises[0]
    return deposer(session, CODE, premiere.email, mf.EMAIL_LIAISON_OBJET, texte, premiere.id)

"""Lot 9 — WhatsApp (API Cloud de Meta) : webhook, mise en forme, envoi, fenêtre de 24 h, liaison par code."""
import hashlib
import hmac
import json
import os
import re
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from celery.schedules import crontab
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select

from app.conversation import confirmation, liaison
from app.conversation import messages_fixes as mf
from app.conversation.models import ABANDONNE, CANAL_WEB, CANAL_WHATSAPP, EN_PAUSE, ENTRANT, SORTANT, Conversation, Message, Parcours
from app.conversation.moteur import fenetre_ouverte, traiter_message, trouver_ou_creer_conversation
from app.conversation.reponse import Reponse
from app.core.config import VERSION, Settings, get_settings
from app.core.db import get_engine, get_session
from app.emails.models import CODE, Email
from app.entreprises.models import Entreprise
from app.main import app
from app.regles.chargement import charger_fichier
from app.whatsapp import envoi, format, reception
from app.whatsapp.models import A_ENVOYER, ECHEC, ENVOYE, WhatsappEnvoi, WhatsappRecu
from app.worker import celery_app, tache_envoyer_whatsapp
from tests.test_lot03_onboarding import niu_unique

RACINE = Path(__file__).resolve().parent.parent
FICHIER_CM = RACINE / "app/regles/donnees/regles_cm.json"
NUMERO_JEFF = "109876543210"
JETON = "jeton-meta-de-test"
SECRET = "secret-app-de-test"
VERIFICATION = "phrase-de-verification"


# --- Outils --------------------------------------------------------------------------------------

@pytest.fixture
def whatsapp_configure(monkeypatch):
    for nom, valeur in {
        "WHATSAPP_JETON": JETON, "WHATSAPP_SECRET_APP": SECRET, "WHATSAPP_JETON_VERIFICATION": VERIFICATION,
        "WHATSAPP_ID_NUMERO": NUMERO_JEFF, "WHATSAPP_VERSION_API": "v23.0",
    }.items():
        monkeypatch.setenv(nom, valeur)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class ReponseHttp:
    def __init__(self, code=200, donnees=None, texte=""):
        self.status_code = code
        self._donnees = donnees
        self.text = texte

    def json(self):
        if self._donnees is None:
            raise ValueError("pas de JSON")
        return self._donnees


class FauxMeta:
    def __init__(self):
        self.appels = []
        self.panne = None
        self.reponse = None

    def __call__(self, url, json=None, headers=None, timeout=None):
        self.appels.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        if self.panne:
            raise self.panne
        if self.reponse:
            return self.reponse
        return ReponseHttp(200, {"messages": [{"id": f"wamid.sortant.{len(self.appels)}"}]})


@pytest.fixture
def meta(monkeypatch, whatsapp_configure):
    faux = FauxMeta()
    monkeypatch.setattr(envoi.httpx, "post", faux)
    return faux


def numero_unique() -> str:
    return "2376" + str(uuid.uuid4().int)[:8]


def notification(numero, *messages, numero_jeff=NUMERO_JEFF) -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [{"id": "WABA", "changes": [{"field": "messages", "value": {
            "messaging_product": "whatsapp",
            "metadata": {"display_phone_number": "15550000000", "phone_number_id": numero_jeff},
            "contacts": [{"profile": {"name": "Client"}, "wa_id": numero}],
            "messages": [{"from": numero, "id": "wamid." + uuid.uuid4().hex, "timestamp": "1790000000", **m} for m in messages],
        }}]}],
    }


def texte(corps):
    return {"type": "text", "text": {"body": corps}}


def bouton(identifiant):
    return {"type": "interactive", "interactive": {"type": "button_reply", "button_reply": {"id": identifiant, "title": "x"}}}


def ligne(identifiant):
    return {"type": "interactive", "interactive": {"type": "list_reply", "list_reply": {"id": identifiant, "title": "x"}}}


class Client:
    """Un client WhatsApp simulé : ses messages passent par la réception, comme ceux de Meta."""

    def __init__(self, session):
        self.session = session
        self.numero = numero_unique()

    def ecrit(self, message) -> list[dict]:
        if isinstance(message, str):
            message = texte(message)
        identifiants = reception.traiter_notification(self.session, notification(self.numero, message))
        return [self.session.get(WhatsappEnvoi, i).contenu for i in identifiants]

    def dit(self, contenu) -> str:
        """Le texte de la dernière réponse (corps du message texte ou interactif)."""
        derniere = self.ecrit(contenu)[-1]
        return derniere["text"]["body"] if derniere["type"] == "text" else derniere["interactive"]["body"]["text"]

    @property
    def conversation(self) -> Conversation:
        return trouver_ou_creer_conversation(self.session, CANAL_WHATSAPP, self.numero)


def signer(corps: bytes, secret=SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), corps, hashlib.sha256).hexdigest()


# --- Mise en forme ------------------------------------------------------------------------------

def test_texte_simple():
    assert format.contenus(Reponse("Bonjour")) == [{"type": "text", "text": {"body": "Bonjour", "preview_url": False}}]


def test_long_texte_coupe_entre_paragraphes():
    paragraphe = "a" * 3000
    messages = format.textes(paragraphe + "\n\n" + paragraphe + "\n\n" + "fin")
    assert [len(m["text"]["body"]) for m in messages] == [3000, 3005]
    assert messages[1]["text"]["body"].endswith("\n\nfin")


def test_paragraphe_geant_coupe_a_4096():
    messages = format.textes("b" * 9000)
    assert [len(m["text"]["body"]) for m in messages] == [4096, 4096, 808]


def test_menu_en_liste():
    [message] = format.contenus(Reponse(mf.ACCUEIL, list(mf.MENU)))
    interactif = message["interactive"]
    assert message["type"] == "interactive" and interactif["type"] == "list"
    assert interactif["body"]["text"] == mf.ACCUEIL
    assert interactif["action"]["button"] == mf.WA_BOUTON_LISTE == "Voir les choix"
    [section] = interactif["action"]["sections"]
    assert [(r["id"], r["title"]) for r in section["rows"]] == list(mf.MENU)
    assert all("description" not in r for r in section["rows"])


def test_trois_choix_courts_en_boutons():
    [message] = format.contenus(Reponse(mf.PROPOSITION_ONBOARDING, list(mf.CHOIX_PROPOSITION)))
    interactif = message["interactive"]
    assert interactif["type"] == "button"
    assert [(b["reply"]["id"], b["reply"]["title"]) for b in interactif["action"]["buttons"]] == list(mf.CHOIX_PROPOSITION)
    assert all(b["type"] == "reply" for b in interactif["action"]["buttons"])


def test_libelle_trop_long_pour_un_bouton_passe_en_liste():
    [message] = format.contenus(Reponse(mf.Q_EMAIL, list(mf.CHOIX_EMAIL)))  # « Je la donnerai plus tard » : 24 caractères
    assert message["interactive"]["type"] == "list"


def test_quatre_choix_en_liste():
    choix = [("1", "Un"), ("2", "Deux"), ("3", "Trois"), ("4", "Quatre")]
    assert format.contenus(Reponse("?", choix))[0]["interactive"]["type"] == "list"


def test_libelle_long_coupe_avec_description():
    [message] = format.contenus(Reponse("?", [("4", "Chiffre d'affaires annuel"), ("5", "Centre des impôts")]))
    lignes = message["interactive"]["action"]["sections"][0]["rows"]
    assert lignes[0] == {"id": "4", "title": "Chiffre d'affaires annu…", "description": "Chiffre d'affaires annuel"}
    assert len(lignes[0]["title"]) == 24
    assert lignes[1] == {"id": "5", "title": "Centre des impôts"}


def test_dix_choix_en_liste_onze_en_texte():
    dix = [(str(n), f"Choix {n}") for n in range(1, 11)]
    assert format.contenus(Reponse("?", dix))[0]["interactive"]["type"] == "list"
    onze = dix + [("11", "Choix 11")]
    [message] = format.contenus(Reponse("Quelle réponse ?", onze))
    assert message["type"] == "text"
    assert message["text"]["body"] == "Quelle réponse ?\n\n" + "\n".join(f"{n}. Choix {n}" for n in range(1, 12))


def test_choix_non_numerotes_en_texte():
    choix = [(str(n), f"C{n}") for n in range(1, 11)] + [("plus tard", "Plus tard")]
    assert format.contenus(Reponse("?", choix))[0]["text"]["body"].endswith("10. C10\n« plus tard » : Plus tard")


def test_corps_trop_long_pour_l_interactif():
    long = "x" * 1500
    messages = format.contenus(Reponse(long, list(mf.MENU)))
    assert messages[0] == {"type": "text", "text": {"body": long, "preview_url": False}}
    assert messages[1]["interactive"]["body"]["text"] == mf.WA_VOTRE_CHOIX
    assert len(format.contenus(Reponse("y" * 1024, list(mf.MENU)))) == 1


def test_rappels_avant_la_reponse():
    messages = format.contenus(Reponse(mf.ACCUEIL, list(mf.MENU), rappels=["Rappel A", "Rappel B"]))
    assert [m.get("text", {}).get("body") for m in messages[:2]] == ["Rappel A", "Rappel B"]
    assert messages[2]["interactive"]["type"] == "list"


def test_tous_les_choix_fixes_tiennent_dans_whatsapp():
    for choix in (mf.MENU, mf.CHOIX_PROPOSITION, mf.CHOIX_RECAP, mf.CHOIX_RECAP_MODIFICATION, mf.CHOIX_PROFIL, mf.CHOIX_CODE):
        for message in format.contenus(Reponse("?", list(choix))):
            interactif = message["interactive"]
            if interactif["type"] == "button":
                assert all(len(b["reply"]["title"]) <= 20 for b in interactif["action"]["buttons"])
            else:
                assert all(len(r["title"]) <= 24 for r in interactif["action"]["sections"][0]["rows"])


# --- Réception ----------------------------------------------------------------------------------

def test_signature(whatsapp_configure):
    corps = b'{"object":"whatsapp_business_account"}'
    assert reception.signature_valide(corps, signer(corps)) is True
    assert reception.signature_valide(corps, signer(corps, "autre-secret")) is False
    assert reception.signature_valide(corps + b" ", signer(corps)) is False
    assert reception.signature_valide(corps, signer(corps).removeprefix("sha256=")) is False
    assert reception.signature_valide(corps, None) is False
    assert reception.signature_valide(corps, "") is False


def test_signature_sans_secret_refusee(monkeypatch):
    monkeypatch.delenv("WHATSAPP_SECRET_APP", raising=False)
    get_settings.cache_clear()
    try:
        corps = b"{}"
        assert reception.signature_valide(corps, "sha256=" + hmac.new(b"", corps, hashlib.sha256).hexdigest()) is False
    finally:
        get_settings.cache_clear()


def test_messages_recus_filtre(whatsapp_configure):
    numero = numero_unique()
    assert len(reception.messages_recus(notification(numero, texte("a"), texte("b")))) == 2
    assert reception.messages_recus(notification(numero, texte("a"), numero_jeff="999")) == []
    assert reception.messages_recus({**notification(numero, texte("a")), "object": "page"}) == []
    autre = notification(numero, texte("a"))
    autre["entry"][0]["changes"][0]["field"] = "account_update"
    assert reception.messages_recus(autre) == []
    statuts = notification(numero)
    statuts["entry"][0]["changes"][0]["value"]["statuses"] = [{"id": "wamid.x", "status": "read"}]
    assert reception.messages_recus(statuts) == []
    assert reception.messages_recus([]) == []
    sans_id = notification(numero, texte("a"))
    del sans_id["entry"][0]["changes"][0]["value"]["messages"][0]["id"]
    assert reception.messages_recus(sans_id) == []


@pytest.mark.parametrize(
    "message, attendu",
    [
        (texte("Bonjour"), "Bonjour"),
        (bouton("oui"), "oui"),
        (ligne("3"), "3"),
        ({"type": "button", "button": {"payload": "renvoyer", "text": "Renvoyer"}}, "renvoyer"),
        ({"type": "button", "button": {"text": "Renvoyer"}}, "Renvoyer"),
        ({"type": "image", "image": {"id": "123"}}, None),
        ({"type": "audio", "audio": {"id": "123"}}, None),
        (texte(""), None),
        ({"type": "interactive", "interactive": {"type": "nfm_reply"}}, None),
    ],
)
def test_texte_du_message(message, attendu):
    assert reception.texte_du_message(message) == attendu


def test_premier_message_whatsapp(session, whatsapp_configure):
    client = Client(session)
    [reponse] = client.ecrit("Bonjour")
    assert reponse["interactive"]["type"] == "list"
    assert reponse["interactive"]["body"]["text"] == mf.ACCUEIL
    conversation = client.conversation
    assert conversation.canal == CANAL_WHATSAPP
    assert conversation.dernier_message_client_le is not None
    [envoi_attente] = session.scalars(select(WhatsappEnvoi).where(WhatsappEnvoi.conversation_id == conversation.id)).all()
    assert (envoi_attente.destinataire, envoi_attente.statut, envoi_attente.essais) == (client.numero, A_ENVOYER, 0)
    messages = session.scalars(select(Message).where(Message.conversation_id == conversation.id).order_by(Message.id)).all()
    assert [(m.sens, m.texte) for m in messages] == [(ENTRANT, "Bonjour"), (SORTANT, mf.ACCUEIL)]


def test_meme_message_recu_deux_fois(session, whatsapp_configure):
    numero = numero_unique()
    donnees = notification(numero, texte("Bonjour"))
    assert len(reception.traiter_notification(session, donnees)) == 1
    assert reception.traiter_notification(session, donnees) == []
    conversation = trouver_ou_creer_conversation(session, CANAL_WHATSAPP, numero)
    assert session.scalars(select(WhatsappRecu).where(WhatsappRecu.conversation_id == conversation.id)).one()


def test_message_non_ecrit(session, whatsapp_configure):
    client = Client(session)
    assert client.dit({"type": "image", "image": {"id": "1"}}) == mf.WA_TYPE_NON_PRIS
    assert client.conversation.dernier_message_client_le is not None
    textes = [m.texte for m in session.scalars(select(Message).where(Message.conversation_id == client.conversation.id).order_by(Message.id))]
    assert textes == ["[image]", mf.WA_TYPE_NON_PRIS]


def test_plusieurs_messages_dans_une_notification(session, whatsapp_configure):
    numero = numero_unique()
    identifiants = reception.traiter_notification(session, notification(numero, texte("Bonjour"), texte("2")))
    assert len(identifiants) == 2
    assert identifiants == sorted(identifiants)


def test_onboarding_par_whatsapp(session, whatsapp_configure):
    client = Client(session)
    assert client.dit(ligne("1")) == mf.PROPOSITION_ONBOARDING
    assert client.dit(bouton("oui")) == mf.Q_RAISON_SOCIALE
    for reponse in ["Ets WhatsApp", niu_unique(), "1", "1", "20 millions", "CDI Douala", "3", "2", "0"]:
        client.ecrit(reponse)
    assert client.dit(ligne("plus tard")).startswith(mf.RECAP_INTRO)
    assert client.dit(bouton("oui")).startswith(mf.BIENVENUE.format(raison_sociale="Ets WhatsApp"))
    assert client.conversation.entreprise_id is not None


def test_fenetre_de_24_heures(session):
    conversation = trouver_ou_creer_conversation(session, CANAL_WHATSAPP, numero_unique())
    maintenant = datetime.now(timezone.utc)
    assert fenetre_ouverte(conversation, maintenant) is False
    conversation.dernier_message_client_le = maintenant - timedelta(hours=23, minutes=59)
    assert fenetre_ouverte(conversation, maintenant) is True
    conversation.dernier_message_client_le = maintenant - timedelta(hours=24)
    assert fenetre_ouverte(conversation, maintenant) is False
    conversation.dernier_message_client_le = maintenant - timedelta(minutes=1)
    assert fenetre_ouverte(conversation) is True


def test_la_bulle_note_aussi_le_dernier_message(session):
    identifiant = "web-" + uuid.uuid4().hex
    traiter_message(session, CANAL_WEB, identifiant, "bonjour")
    assert fenetre_ouverte(trouver_ou_creer_conversation(session, CANAL_WEB, identifiant))


# --- Liaison à un profil existant -----------------------------------------------------------------

def profil_confirme(session, email=None) -> Entreprise:
    e = Entreprise(
        juridiction_code="CM", niu=niu_unique(), raison_sociale="Ets Relié", regime_declare="reel",
        assujetti_tva_declare=True, nombre_salaries=0, email=email or f"relie.{uuid.uuid4().hex[:8]}@exemple.cm",
        email_confirme_le=datetime.now(timezone.utc),
    )
    session.add(e)
    session.flush()
    return e


def dernier_code(session, destinataire):
    email = session.scalars(select(Email).where(Email.destinataire == destinataire).order_by(Email.id.desc())).first()
    return re.search(r"\b(\d{6})\b", email.texte).group(1)


def codes_envoyes(session, destinataire) -> int:
    return len(session.scalars(select(Email).where(Email.destinataire == destinataire)).all())


def vers_la_liaison(client):
    client.ecrit(ligne("1"))
    assert client.dit(bouton("deja")) == mf.LIAISON_EMAIL


def liaison_de(client) -> Parcours:
    return client.session.scalars(
        select(Parcours).where(Parcours.conversation_id == client.conversation.id, Parcours.type == liaison.TYPE)
    ).first()


def test_relier_whatsapp_a_un_profil(session, whatsapp_configure):
    charger_fichier(session, FICHIER_CM)
    profil = profil_confirme(session)
    client = Client(session)
    vers_la_liaison(client)
    assert client.dit("pas une adresse") == mf.ERR_EMAIL
    assert client.dit("plus tard") == mf.ERR_EMAIL
    assert client.dit(profil.email.upper()) == mf.LIAISON_CODE_ENVOYE
    [email] = session.scalars(select(Email).where(Email.destinataire == profil.email)).all()
    assert email.type == CODE
    assert email.objet == mf.EMAIL_LIAISON_OBJET
    code = dernier_code(session, profil.email)
    assert email.texte == mf.EMAIL_LIAISON_TEXTE.format(raison_sociale="Ets Relié", code=code) + "\n\n" + mf.EMAIL_SIGNATURE
    assert code not in json.dumps(liaison_de(client).donnees)
    fin = client.ecrit(code)[-1]
    assert fin["interactive"]["body"]["text"] == mf.LIAISON_OK.format(raison_sociale="Ets Relié")
    assert fin["interactive"]["type"] == "list"
    assert client.conversation.entreprise_id == profil.id
    assert client.dit(ligne("2")).startswith(mf.OBLIGATIONS_INTRO.format(raison_sociale="Ets Relié"))


def test_liaison_depuis_la_bulle(session):
    profil = profil_confirme(session)
    identifiant = "web-" + uuid.uuid4().hex

    def dit(t):
        return traiter_message(session, CANAL_WEB, identifiant, t)
    dit("5")
    assert dit("J'ai déjà un profil").texte == mf.LIAISON_EMAIL
    dit(profil.email)
    assert dit(dernier_code(session, profil.email)).texte == mf.LIAISON_OK.format(raison_sociale="Ets Relié")
    assert trouver_ou_creer_conversation(session, CANAL_WEB, identifiant).entreprise_id == profil.id


def test_adresse_inconnue_meme_reponse_sans_email(session, whatsapp_configure):
    client = Client(session)
    vers_la_liaison(client)
    inconnue = f"inconnu.{uuid.uuid4().hex[:8]}@exemple.cm"
    assert client.dit(inconnue) == mf.LIAISON_CODE_ENVOYE
    assert codes_envoyes(session, inconnue) == 0
    assert client.dit("renvoyer") == mf.LIAISON_CODE_ENVOYE
    assert codes_envoyes(session, inconnue) == 0
    for _ in range(confirmation.ESSAIS_MAX - 1):
        assert client.dit("123456") == mf.CODE_FAUX
    assert client.dit("123456") == mf.LIAISON_TROP_D_ESSAIS
    assert liaison_de(client).statut == ABANDONNE
    assert client.conversation.entreprise_id is None


def test_adresse_non_confirmee_aucun_code(session, whatsapp_configure):
    profil = profil_confirme(session)
    profil.email_confirme_le = None
    session.flush()
    client = Client(session)
    vers_la_liaison(client)
    assert client.dit(profil.email) == mf.LIAISON_CODE_ENVOYE
    assert codes_envoyes(session, profil.email) == 0


def test_liaison_code_faux_puis_bon(session, whatsapp_configure):
    profil = profil_confirme(session)
    client = Client(session)
    vers_la_liaison(client)
    client.ecrit(profil.email)
    code = dernier_code(session, profil.email)
    faux = "000000" if code != "000000" else "111111"
    assert client.dit(faux) == mf.CODE_FAUX
    assert client.dit("12 34") == mf.CODE_FORMAT
    assert client.dit(code[:3] + " " + code[3:]) == mf.LIAISON_OK.format(raison_sociale="Ets Relié")


def test_liaison_code_expire_et_renvois(session, whatsapp_configure, monkeypatch):
    profil = profil_confirme(session)
    client = Client(session)
    vers_la_liaison(client)
    client.ecrit(profil.email)
    ancien = dernier_code(session, profil.email)
    plus_tard = datetime.now(timezone.utc) + timedelta(minutes=16)
    monkeypatch.setattr(confirmation, "maintenant", lambda: plus_tard)
    assert client.dit(ancien) == mf.CODE_EXPIRE
    for _ in range(confirmation.RENVOIS_MAX):
        assert client.dit("renvoyer") == mf.LIAISON_CODE_ENVOYE
    assert client.dit("renvoyer") == mf.CODE_TROP_DE_RENVOIS
    assert codes_envoyes(session, profil.email) == 1 + confirmation.RENVOIS_MAX
    assert client.dit(dernier_code(session, profil.email)) == mf.LIAISON_OK.format(raison_sociale="Ets Relié")


def test_liaison_annulee(session, whatsapp_configure):
    client = Client(session)
    vers_la_liaison(client)
    assert client.dit("annuler") == mf.LIAISON_ANNULEE
    assert liaison_de(client).statut == ABANDONNE


def test_liaison_en_pause_puis_reprise(session, whatsapp_configure):
    profil = profil_confirme(session)
    client = Client(session)
    vers_la_liaison(client)
    client.ecrit("menu")
    assert liaison_de(client).statut == EN_PAUSE
    assert client.dit("reprendre") == mf.LIAISON_EMAIL
    client.ecrit(profil.email)
    client.ecrit("menu")
    assert client.dit("reprendre") == mf.LIAISON_CODE_ATTENDU


def test_adresse_changee_avant_le_code(session, whatsapp_configure):
    profil = profil_confirme(session)
    client = Client(session)
    vers_la_liaison(client)
    client.ecrit(profil.email)
    code = dernier_code(session, profil.email)
    profil.email = "nouvelle@exemple.cm"
    session.flush()
    assert client.dit(code) == mf.LIAISON_ANNULEE
    assert client.conversation.entreprise_id is None


def test_confirmation_retiree_avant_le_code(session, whatsapp_configure):
    profil = profil_confirme(session)
    client = Client(session)
    vers_la_liaison(client)
    client.ecrit(profil.email)
    code = dernier_code(session, profil.email)
    profil.email_confirme_le = None
    session.flush()
    assert client.dit(code) == mf.LIAISON_ANNULEE


def test_liaison_hors_juridiction(session, whatsapp_configure, monkeypatch):
    profil = profil_confirme(session)
    monkeypatch.setenv("JURIDICTION", "SN")
    get_settings.cache_clear()
    assert liaison.entreprise_confirmee(session, profil.email) is None
    monkeypatch.setenv("JURIDICTION", "CM")
    get_settings.cache_clear()
    assert liaison.entreprise_confirmee(session, profil.email).id == profil.id


# --- Envoi à Meta --------------------------------------------------------------------------------

def test_envoyer_graph(meta):
    wamid = envoi.envoyer_graph("237690000000", {"type": "text", "text": {"body": "Bonjour"}})
    assert wamid == "wamid.sortant.1"
    [appel] = meta.appels
    assert appel["url"] == f"https://graph.facebook.com/v23.0/{NUMERO_JEFF}/messages"
    assert appel["headers"] == {"Authorization": f"Bearer {JETON}"}
    assert appel["json"] == {
        "messaging_product": "whatsapp", "recipient_type": "individual", "to": "237690000000",
        "type": "text", "text": {"body": "Bonjour"},
    }
    assert appel["timeout"] == 15


def test_erreur_de_meta(meta):
    meta.reponse = ReponseHttp(400, {"error": {"code": 131047, "message": "Re-engagement message"}})
    with pytest.raises(envoi.ErreurMeta) as erreur:
        envoi.envoyer_graph("237690000000", {"type": "text", "text": {"body": "x"}})
    assert str(erreur.value) == "HTTP 400 : 131047 Re-engagement message"
    meta.reponse = ReponseHttp(502, None, "Bad gateway")
    with pytest.raises(envoi.ErreurMeta, match="HTTP 502 : Bad gateway"):
        envoi.envoyer_graph("237690000000", {"type": "text", "text": {"body": "x"}})


def envoi_en_attente(session, numero=None) -> WhatsappEnvoi:
    conversation = trouver_ou_creer_conversation(session, CANAL_WHATSAPP, numero or numero_unique())
    e = WhatsappEnvoi(conversation_id=conversation.id, destinataire=conversation.identifiant_externe,
                      contenu={"type": "text", "text": {"body": "Bonjour"}}, statut=A_ENVOYER, essais=0)
    session.add(e)
    session.flush()
    return e


def test_envoyer_un(session, meta):
    e = envoi_en_attente(session)
    assert envoi.envoyer_un(session, e.id) is True
    assert (e.statut, e.wamid, e.erreur) == (ENVOYE, "wamid.sortant.1", None)
    assert e.envoye_le is not None
    assert envoi.envoyer_un(session, e.id) is None  # jamais deux fois
    assert len(meta.appels) == 1


def test_echecs_puis_abandon(session, meta):
    e = envoi_en_attente(session)
    meta.panne = ConnectionError(f"refus avec {JETON} dans le message")
    for essai in range(1, envoi.ESSAIS_MAX + 1):
        assert envoi.envoyer_un(session, e.id) is False
        assert e.essais == essai
    assert e.statut == ECHEC
    assert JETON not in e.erreur
    assert e.erreur == "ConnectionError: refus avec *** dans le message"
    assert envoi.envoyer_un(session, e.id) is None


def test_un_echec_puis_reussite(session, meta):
    e = envoi_en_attente(session)
    meta.panne = TimeoutError("lent")
    envoi.envoyer_un(session, e.id)
    meta.panne = None
    assert envoi.envoyer_un(session, e.id) is True
    assert (e.statut, e.essais, e.erreur) == (ENVOYE, 1, None)


def test_erreur_tronquee(session, meta):
    e = envoi_en_attente(session)
    meta.panne = RuntimeError("x" * 900)
    envoi.envoyer_un(session, e.id)
    assert len(e.erreur) == 500


def test_reprise_des_messages_en_attente(session, meta, monkeypatch):
    recent, ancien = envoi_en_attente(session), envoi_en_attente(session)
    session.execute(WhatsappEnvoi.__table__.update().where(WhatsappEnvoi.id == ancien.id)
                    .values(cree_le=datetime.now(timezone.utc) - timedelta(minutes=2)))
    session.execute(WhatsappEnvoi.__table__.update().where(WhatsappEnvoi.id == recent.id)
                    .values(cree_le=datetime.now(timezone.utc)))
    bilan = envoi.envoyer_en_attente(session)
    assert (bilan.envoyes, bilan.echecs, bilan.desactive) == (1, 0, False)
    session.refresh(ancien)
    session.refresh(recent)
    assert (ancien.statut, recent.statut) == (ENVOYE, A_ENVOYER)
    assert envoi.DELAI_REPRISE == timedelta(seconds=30)
    meta.panne = OSError("coupure")
    session.execute(WhatsappEnvoi.__table__.update().where(WhatsappEnvoi.id == recent.id)
                    .values(cree_le=datetime.now(timezone.utc) - timedelta(minutes=2)))
    assert envoi.envoyer_en_attente(session).echecs >= 1


def test_reprise_desactivee_sans_reglages(session, monkeypatch):
    for nom in ("WHATSAPP_JETON", "WHATSAPP_SECRET_APP", "WHATSAPP_JETON_VERIFICATION", "WHATSAPP_ID_NUMERO"):
        monkeypatch.delenv(nom, raising=False)
    get_settings.cache_clear()
    try:
        assert envoi.envoyer_en_attente(session).desactive is True
    finally:
        get_settings.cache_clear()


def test_reglages_whatsapp():
    complets = dict(whatsapp_jeton="j", whatsapp_secret_app="s", whatsapp_jeton_verification="v", whatsapp_id_numero="1")
    assert Settings(**complets).whatsapp_configure is True
    for cle in complets:
        assert Settings(**{**complets, cle: ""}).whatsapp_configure is False
        assert Settings(**{**complets, cle: "A_REMPLACER"}).whatsapp_configure is False
    assert Settings(**complets).whatsapp_version_api == "v23.0"


def test_fichiers_de_configuration():
    exemple = (RACINE / ".env.example").read_text()
    for nom in ("WHATSAPP_JETON", "WHATSAPP_SECRET_APP", "WHATSAPP_JETON_VERIFICATION", "WHATSAPP_ID_NUMERO"):
        assert f"{nom}=A_REMPLACER" in exemple
    assert "httpx==" in (RACINE / "requirements.txt").read_text()


# --- Webhook (de bout en bout, avec la vraie base) ---------------------------------------------

def test_verification_par_meta(whatsapp_configure):
    client = TestClient(app)
    ok = client.get("/whatsapp/webhook", params={"hub.mode": "subscribe", "hub.verify_token": VERIFICATION, "hub.challenge": "12345"})
    assert (ok.status_code, ok.text) == (200, "12345")
    assert client.get("/whatsapp/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "faux", "hub.challenge": "1"}).status_code == 403
    assert client.get("/whatsapp/webhook", params={"hub.mode": "unsubscribe", "hub.verify_token": VERIFICATION, "hub.challenge": "1"}).status_code == 403
    assert client.get("/whatsapp/webhook").status_code == 403


def test_verification_refusee_sans_configuration(monkeypatch):
    monkeypatch.setenv("WHATSAPP_JETON_VERIFICATION", VERIFICATION)
    monkeypatch.delenv("WHATSAPP_JETON", raising=False)
    get_settings.cache_clear()
    try:
        reponse = TestClient(app).get("/whatsapp/webhook", params={"hub.mode": "subscribe", "hub.verify_token": VERIFICATION, "hub.challenge": "1"})
        assert reponse.status_code == 403
    finally:
        get_settings.cache_clear()


def poster(client, donnees, signature=None):
    corps = json.dumps(donnees).encode()
    return client.post("/whatsapp/webhook", content=corps, headers={
        "Content-Type": "application/json", "X-Hub-Signature-256": signature or signer(corps),
    })


def test_webhook_de_bout_en_bout(meta, monkeypatch):
    monkeypatch.delenv("ESSAI_ACTIF", raising=False)  # le webhook ne dépend pas de la page d'essai
    client = TestClient(app)
    numero = numero_unique()
    donnees = notification(numero, texte("Bonjour"))
    reponse = poster(client, donnees)
    assert (reponse.status_code, reponse.json()) == (200, {"ok": True})
    [appel] = meta.appels
    assert appel["json"]["to"] == numero
    assert appel["json"]["interactive"]["body"]["text"] == mf.ACCUEIL
    # Meta renvoie la même notification : rien n'est renvoyé au client.
    assert poster(client, donnees).status_code == 200
    assert len(meta.appels) == 1
    session = get_session()
    try:
        conversation = trouver_ou_creer_conversation(session, CANAL_WHATSAPP, numero)
        [envoye] = session.scalars(select(WhatsappEnvoi).where(WhatsappEnvoi.conversation_id == conversation.id)).all()
        assert (envoye.statut, envoye.wamid) == (ENVOYE, "wamid.sortant.1")
    finally:
        session.rollback()
        session.close()


def test_webhook_meta_indisponible(meta):
    meta.panne = ConnectionError("injoignable")
    numero = numero_unique()
    assert poster(TestClient(app), notification(numero, texte("Bonjour"))).status_code == 200
    session = get_session()
    try:
        conversation = trouver_ou_creer_conversation(session, CANAL_WHATSAPP, numero)
        [attente] = session.scalars(select(WhatsappEnvoi).where(WhatsappEnvoi.conversation_id == conversation.id)).all()
        assert (attente.statut, attente.essais) == (A_ENVOYER, 1)
    finally:
        session.rollback()
        session.close()


def test_webhook_signature_invalide(meta):
    client = TestClient(app)
    donnees = notification(numero_unique(), texte("Bonjour"))
    assert poster(client, donnees, signature="sha256=" + "0" * 64).status_code == 403
    assert client.post("/whatsapp/webhook", content=b"{}").status_code == 403
    assert meta.appels == []


def test_webhook_corps_illisible(meta):
    corps = b"pas du json"
    reponse = TestClient(app).post("/whatsapp/webhook", content=corps, headers={"X-Hub-Signature-256": signer(corps)})
    assert reponse.status_code == 400


def test_webhook_corps_trop_gros(meta, monkeypatch):
    from app.canaux import whatsapp as canal

    monkeypatch.setattr(canal, "CORPS_MAX", 10)
    corps = json.dumps(notification(numero_unique(), texte("Bonjour"))).encode()
    reponse = TestClient(app).post("/whatsapp/webhook", content=corps, headers={"X-Hub-Signature-256": signer(corps)})
    assert reponse.status_code == 403


def test_webhook_non_configure(monkeypatch):
    for nom in ("WHATSAPP_JETON", "WHATSAPP_SECRET_APP", "WHATSAPP_JETON_VERIFICATION", "WHATSAPP_ID_NUMERO"):
        monkeypatch.delenv(nom, raising=False)
    get_settings.cache_clear()
    try:
        assert TestClient(app).post("/whatsapp/webhook", content=b"{}").status_code == 503
    finally:
        get_settings.cache_clear()


# --- Tâche, base, version ------------------------------------------------------------------------

def test_tache_de_reprise_chaque_minute():
    entree = celery_app.conf.beat_schedule["envoyer-whatsapp"]
    assert (entree["task"], entree["schedule"]) == ("jeff.envoyer_whatsapp", crontab())
    assert "jeff.envoyer_whatsapp" in celery_app.tasks


class SessionFactice:
    def __init__(self):
        self.actions = []

    def rollback(self):
        self.actions.append("rollback")

    def close(self):
        self.actions.append("close")


def test_la_tache_de_reprise(monkeypatch):
    factice = SessionFactice()
    monkeypatch.setattr("app.core.db.get_session", lambda: factice)
    monkeypatch.setattr(envoi, "envoyer_en_attente", lambda s: envoi.Bilan(envoyes=3))
    assert tache_envoyer_whatsapp() == {"envoyes": 3, "echecs": 0, "desactive": False}
    assert factice.actions == ["close"]

    def panne(s):
        raise RuntimeError("panne")
    monkeypatch.setattr(envoi, "envoyer_en_attente", panne)
    with pytest.raises(RuntimeError):
        tache_envoyer_whatsapp()
    assert factice.actions == ["close", "rollback", "close"]


def test_la_tache_connait_toutes_les_tables():
    code = (
        "import app.worker as w, app.whatsapp.envoi as e, app.core.db as db\n"
        "from app.core.db import Base\n"
        "class S:\n    def rollback(self): pass\n    def close(self): pass\n"
        "def verifier(session):\n"
        "    [fk.column for t in Base.metadata.tables.values() for fk in t.foreign_keys]\n"
        "    return e.Bilan()\n"
        "e.envoyer_en_attente = verifier\ndb.get_session = lambda: S()\nw.tache_envoyer_whatsapp()\n"
    )
    resultat = subprocess.run([sys.executable, "-c", code], cwd=RACINE, env=os.environ.copy(), capture_output=True, text=True)
    assert resultat.returncode == 0, resultat.stderr


def test_tables():
    inspecteur = inspect(get_engine())
    assert inspecteur.get_columns("conversations")[-1]  # la table existe
    colonnes_conversations = {c["name"]: c for c in inspecteur.get_columns("conversations")}
    assert colonnes_conversations["dernier_message_client_le"]["nullable"] is True
    assert {c["name"] for c in inspecteur.get_columns("whatsapp_recus")} == {"wamid", "conversation_id", "recu_le"}
    assert inspecteur.get_pk_constraint("whatsapp_recus")["constrained_columns"] == ["wamid"]
    envois = {c["name"]: c for c in inspecteur.get_columns("whatsapp_envois")}
    assert set(envois) >= {"id", "conversation_id", "destinataire", "contenu", "statut", "essais", "erreur", "wamid", "cree_le", "envoye_le"}
    for obligatoire in ("conversation_id", "destinataire", "contenu", "statut", "essais"):
        assert envois[obligatoire]["nullable"] is False
    assert {i["name"] for i in inspecteur.get_indexes("whatsapp_envois")} >= {"ix_whatsapp_envois_statut", "ix_whatsapp_envois_conversation_id"}


def test_proposition_a_trois_choix():
    assert mf.CHOIX_PROPOSITION[2] == ("deja", "J'ai déjà un profil")


def test_version():
    assert TestClient(app).get("/sante").json()["version"] == VERSION


# --- Limites et reprise (compléments) -------------------------------------------------------------

def test_limites_decidees():
    assert envoi.ESSAIS_MAX == 3
    assert (format.TEXTE_MAX, format.CORPS_INTERACTIF_MAX, format.BOUTONS_MAX) == (4096, 1024, 3)
    assert (format.BOUTON_TITRE_MAX, format.LISTE_MAX, format.LIGNE_TITRE_MAX, format.LIGNE_DESCRIPTION_MAX) == (20, 10, 24, 72)


def test_corps_de_1025_caracteres_part_seul():
    assert len(format.contenus(Reponse("y" * 1025, list(mf.MENU)))) == 2


def test_la_reprise_ne_prend_que_les_messages_en_attente(session, meta, monkeypatch):
    monkeypatch.setattr(envoi, "LOT", 1)
    deja, attente = envoi_en_attente(session), envoi_en_attente(session)
    deja.statut = ENVOYE
    session.execute(WhatsappEnvoi.__table__.update().where(WhatsappEnvoi.id.in_([deja.id, attente.id]))
                    .values(cree_le=datetime.now(timezone.utc) - timedelta(hours=1)))
    session.flush()
    # D'autres messages anciens peuvent rester en attente dans la base de test : on les écarte.
    session.execute(WhatsappEnvoi.__table__.update()
                    .where(WhatsappEnvoi.statut == A_ENVOYER, WhatsappEnvoi.id != attente.id).values(statut=ECHEC))
    assert envoi.envoyer_en_attente(session).envoyes == 1
    session.refresh(attente)
    assert attente.statut == ENVOYE


def test_bloc_nginx_n_ouvre_que_le_webhook():
    bloc = (RACINE / "deploy/nginx/jeff-webhook.conf").read_text()
    lignes = [l.strip() for l in bloc.splitlines() if l.strip() and not l.strip().startswith("#")]
    assert [l for l in lignes if l.startswith("location")] == ["location = /jeff/whatsapp/webhook {"]
    assert "proxy_pass http://127.0.0.1:8020/whatsapp/webhook;" in lignes
    assert lignes[-1] == "}"
    assert bloc.count("{") == bloc.count("}") == 1

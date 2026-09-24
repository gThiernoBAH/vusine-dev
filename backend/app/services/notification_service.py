"""
notification_service.py -- envoi d'emails (SMTP) et de messages Telegram.
*** NOUVEAU 2026-09-24 (Palier 1, rapport matinal) ***

Avant cette date, le dépôt ne contenait AUCUN code d'envoi : les réglages SMTP_* et
TELEGRAM_BOT_TOKEN existaient dans settings.py mais rien ne les utilisait. Ce module ne
dépend que de la bibliothèque standard (smtplib, urllib) -- aucune dépendance ajoutée.

Chaque fonction LÈVE une exception en cas d'échec : l'appelant décide quoi en faire
(rapport_matinal_service isole les échecs destinataire par destinataire).
"""
import json
import logging
import smtplib
import urllib.request
from email.message import EmailMessage

from ..core.settings import settings

logger = logging.getLogger(__name__)

SMTP_TIMEOUT_S = 20
TELEGRAM_TIMEOUT_S = 10
TELEGRAM_MAX_CARACTERES = 4000   # limite de l'API : 4096


def envoyer_email(destinataire: str, sujet: str, html: str, texte: str) -> None:
    """Un message multipart (texte + HTML) par destinataire : les adresses ne sont jamais
    exposées entre elles, et l'échec d'une adresse n'empêche pas les autres."""
    msg = EmailMessage()
    msg["Subject"] = sujet
    msg["From"] = settings.SMTP_FROM
    msg["To"] = destinataire
    msg.set_content(texte)
    msg.add_alternative(html, subtype="html")

    port = settings.SMTP_PORT
    cls = smtplib.SMTP_SSL if port == 465 else smtplib.SMTP
    with cls(settings.SMTP_HOST, port, timeout=SMTP_TIMEOUT_S) as serveur:
        # Chiffrement STARTTLS dès que le serveur l'annonce ; identification seulement si le
        # serveur la propose (un relais interne sans authentification reste utilisable).
        if port != 465 and serveur.has_extn("starttls"):
            serveur.starttls()
            serveur.ehlo()
        if settings.SMTP_USERNAME and settings.SMTP_PASSWORD and serveur.has_extn("auth"):
            serveur.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
        serveur.send_message(msg)


def envoyer_telegram(chat_id: str, texte: str) -> None:
    if not settings.TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN n'est pas configuré.")
    charge = json.dumps({"chat_id": chat_id, "text": texte[:TELEGRAM_MAX_CARACTERES],
                         "disable_web_page_preview": True}).encode("utf-8")
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage",
        data=charge, headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=TELEGRAM_TIMEOUT_S) as reponse:
        corps = json.loads(reponse.read().decode("utf-8"))
    if not corps.get("ok"):
        raise RuntimeError(f"Telegram a refusé le message : {corps.get('description', 'erreur inconnue')}")

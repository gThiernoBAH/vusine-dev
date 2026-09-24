"""Jetons d'accès signés (HMAC-SHA256), sans dépendance externe.

*** AJOUT 2026-09-24 *** : remplace l'ancien mécanisme « header X-User-ID » (simple
revendication d'identité, non vérifiée -- quiconque connaissait un id pouvait appeler
l'API en son nom, y compris celui d'un admin).

Format : `<payload_b64url>.<signature_b64url>`
  payload = {"sub": id_utilisateur, "iat": émis_à, "exp": expire_à, "pwd": empreinte}
  signature = HMAC-SHA256(AUTH_SECRET_KEY, payload_b64url)

`pwd` est une empreinte tronquée du hash de mot de passe : changer le mot de passe d'un
compte invalide automatiquement tous ses jetons déjà émis, sans table de révocation.
La désactivation d'un compte (is_active=False) est vérifiée à chaque requête dans
auth_routes.get_current_user, pas ici.
"""
import base64
import hashlib
import hmac
import json
import time
from typing import Optional

from .settings import settings


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _signer(message: str) -> str:
    digest = hmac.new(settings.AUTH_SECRET_KEY.encode("utf-8"), message.encode("ascii"), hashlib.sha256).digest()
    return _b64e(digest)


def empreinte_mot_de_passe(password_hash: str) -> str:
    """Empreinte courte (non réversible) du hash bcrypt, embarquée dans le jeton."""
    return hashlib.sha256(password_hash.encode("utf-8")).hexdigest()[:16]


def creer_jeton(user_id: int, password_hash: str, duree_heures: Optional[float] = None) -> tuple[str, int]:
    """Retourne (jeton, expiration en epoch secondes)."""
    duree = settings.AUTH_TOKEN_TTL_HOURS if duree_heures is None else duree_heures
    maintenant = int(time.time())
    expire = maintenant + int(duree * 3600)
    payload = {"sub": user_id, "iat": maintenant, "exp": expire, "pwd": empreinte_mot_de_passe(password_hash)}
    corps = _b64e(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    return f"{corps}.{_signer(corps)}", expire


def lire_jeton(jeton: str) -> Optional[dict]:
    """Payload du jeton s'il est authentique et non expiré, sinon None (jamais d'exception)."""
    try:
        corps, signature = jeton.split(".", 1)
        if not hmac.compare_digest(signature, _signer(corps)):
            return None
        payload = json.loads(_b64d(corps))
        if not isinstance(payload.get("sub"), int) or int(payload.get("exp", 0)) < time.time():
            return None
        return payload
    except Exception:
        return None

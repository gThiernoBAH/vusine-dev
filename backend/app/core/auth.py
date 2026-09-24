from datetime import datetime, timedelta
import secrets
import bcrypt


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Vérifie si un mot de passe en clair correspond à un mot de passe haché."""
    try:
        return bcrypt.checkpw(
            plain_password.encode('utf-8'),
            hashed_password.encode('utf-8')
        )
    except Exception:
        return False


def get_password_hash(password: str) -> str:
    """Hache un mot de passe en clair pour un stockage sécurisé avec un sel unique."""
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')


def generate_reset_token() -> str:
    """Génère un token aléatoire et sécurisé pour la réinitialisation de mot de passe."""
    return secrets.token_urlsafe(32)


def get_reset_token_expiry() -> datetime:
    """Définit la durée de validité du token de réinitialisation (1 heure)."""
    return datetime.now() + timedelta(hours=1)

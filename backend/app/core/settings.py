from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
import os


class Settings(BaseSettings):
    # --- Database (base transactionnelle propre à Vusine) ---
    DATABASE_URL: str

    # --- Odoo Cloud : lecture référentiel + écriture retour par lot ---
    ODOO_CLOUD_URL: str
    ODOO_CLOUD_DB: str
    ODOO_CLOUD_USER: str
    ODOO_CLOUD_API_KEY: str
    ODOO_SYNC_INTERVAL_MINUTES: int = 10
    ODOO_WRITEBACK_ENABLED: bool = False

    # --- SMTP ---
    SMTP_HOST: str
    SMTP_PORT: int
    SMTP_USERNAME: str
    SMTP_PASSWORD: str
    SMTP_FROM: str

    # --- Telegram (optionnel, même principe que SIVOX) ---
    TELEGRAM_BOT_TOKEN: str = ""

    # --- Security ---
    ENCRYPTION_KEY: str

    # *** AJOUT 2026-09-24 *** : clé de signature des jetons d'accès (cf. core/tokens.py).
    # OBLIGATOIRE, au moins 32 caractères -- le serveur refuse de démarrer sinon, plutôt
    # que de tourner avec une clé faible ou vide. Générer par exemple avec :
    #   python3 -c "import secrets; print(secrets.token_urlsafe(48))"
    # Changer cette clé déconnecte tout le monde (tous les jetons émis deviennent invalides).
    AUTH_SECRET_KEY: str
    # Durée de vie d'une session, en heures (un poste = ~10 h).
    AUTH_TOKEN_TTL_HOURS: float = 12
    # *** AJOUT 2026-09-24 (Andon) *** : durée de session d'un compte « kiosque » (écran
    # d'atelier) -- long, car personne n'est là pour se reconnecter ; compensé par le fait
    # qu'un compte kiosque ne peut appeler QUE la route de l'écran Andon (cf.
    # auth_routes.get_current_user), en lecture seule.
    KIOSK_TOKEN_TTL_DAYS: float = 30
    # Anti force brute sur /auth/login : N échecs consécutifs -> verrouillage M minutes.
    LOGIN_MAX_ATTEMPTS: int = 5
    LOGIN_LOCK_MINUTES: int = 15

    @field_validator("AUTH_SECRET_KEY")
    @classmethod
    def _cle_assez_longue(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("AUTH_SECRET_KEY doit faire au moins 32 caractères.")
        return v

    # --- LLM (chantier Labo, F4 : explications à la demande) ---
    # *** MODIFIÉ 2026-09-23 *** : OpenRouter (même forfait que SIVOX) au lieu de l'API
    # Anthropic directe. Optionnel -- si OPENROUTER_API_KEY est vide, F4 reste désactivé
    # (labo_explication_service lève une erreur explicite, jamais un plantage silencieux).
    OPENROUTER_API_KEY: str = ""
    LLM_MODEL: str = "google/gemini-2.5-flash"
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"

    # --- Scheduler d'alertes (retard/arrêt lignes) ---
    # Même prudence que SIVOX (cf. main.py côté SIVOX, lifespan) : désactivé par défaut,
    # le temps de valider le cycle en conditions réelles avant de l'automatiser.
    ALERT_SCHEDULER_ENABLED: bool = False

    # --- *** AJOUT 2026-09-24 (Palier 1) *** Rapport matinal automatique ---
    # Désactivé par défaut (même prudence que les autres jobs) : à activer une fois le rapport
    # validé via GET /rapports/matinal/apercu et un envoi de test (POST /rapports/matinal/envoyer?test=true).
    # Nécessite aussi SNAPSHOT_SCHEDULER_ENABLED=True (le rapport lit les performances figées
    # chaque soir, et le scheduler ne démarre que dans ce cas). Heure et jours : paramètres
    # rapport_matinal_heure / rapport_matinal_jours (Administration -> Paramètres).
    RAPPORT_MATINAL_ENABLED: bool = False

    # --- Scheduler de snapshot performance quotidien (base du scoring historique) ---
    # Même prudence : désactivé par défaut -- POST /scoring/snapshot/run-now permet de
    # déclencher un snapshot manuellement en attendant de valider le cycle automatique.
    SNAPSHOT_SCHEDULER_ENABLED: bool = False

    # --- Scheduler de synchro Odoo périodique ---
    # Même prudence : désactivé par défaut le temps de valider le premier run réel
    # (POST /sync/run-now) en conditions réelles avant de l'automatiser.
    ODOO_SYNC_SCHEDULER_ENABLED: bool = False

    model_config = SettingsConfigDict(
        env_file=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".env")
    )


settings = Settings()

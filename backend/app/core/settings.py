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

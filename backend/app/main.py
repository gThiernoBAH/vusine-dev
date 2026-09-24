import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s : %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

from app.api.auth_routes import router as auth_router
from app.api.entity_routes import router as entity_router
from app.api.action_routes import router as action_router
from app.api.dashboard_routes import router as dashboard_router
from app.api.scoring_routes import router as scoring_router
from app.api.sync_routes import router as sync_router
from app.api.config_admin_routes import router as config_admin_router
# *** AJOUTS 2026-09-17 *** : reports_routes.py existait déjà mais n'était jamais monté
# (oubli -- cf. diagnostic "Not Found" sur l'écran Rapports). alert_routes.py est
# nouveau (le fichier n'existait pas du tout -- écran Alertes jamais branché).
from app.api.reports_routes import router as reports_router
from app.api.alert_routes import router as alert_router
# *** AJOUT (chantier Labo) ***
from app.api.labo_routes import router as labo_router
from app.core.settings import settings
from app.services.scheduler import start_scheduler, stop_scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Startup ---
    # Même philosophie de tolérance aux pannes que SIVOX (main.py) : un échec ici ne doit
    # jamais empêcher le serveur de démarrer -- POST /scoring/snapshot/run-now reste le
    # filet de sécurité manuel dans tous les cas.
    if settings.SNAPSHOT_SCHEDULER_ENABLED:
        try:
            logger.info("[INITIALISATION] Démarrage du scheduler de snapshot performance...")
            start_scheduler()
        except Exception as e:
            logger.critical(f"[CRASH INITIALISATION SCHEDULER] : {str(e)}", exc_info=True)
    else:
        logger.info(
            "[INITIALISATION] Scheduler de snapshot désactivé (SNAPSHOT_SCHEDULER_ENABLED=False) "
            "-- déclenchement manuel uniquement via POST /scoring/snapshot/run-now."
        )

    yield

    # --- Shutdown ---
    stop_scheduler()


app = FastAPI(title="Vusine API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(entity_router)
app.include_router(action_router)
app.include_router(dashboard_router)
app.include_router(scoring_router)
app.include_router(sync_router)
app.include_router(config_admin_router)
app.include_router(reports_router)
app.include_router(alert_router)
app.include_router(labo_router)
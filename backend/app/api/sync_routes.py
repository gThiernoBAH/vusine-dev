from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func

from ..core.database import get_db
from ..core.models import User
from ..core.settings import settings
from ..models.production import LigneCache, OfCache, CadenceReference
from ..services.odoo_sync_service import synchroniser_tout, OdooSyncError
from .auth_routes import require_admin

router = APIRouter(prefix="/sync", tags=["sync"])


@router.get("/status")
def get_sync_status(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    """État des 3 caches Odoo (lignes/OF/cadence) -- dernière synchro et volume, pour
    surveiller que le job périodique tourne bien."""
    def _stat(model):
        return {
            "count": db.query(func.count(model.id)).scalar(),
            "derniere_synchro": db.query(func.max(model.synced_at)).scalar(),
        }

    return {
        "lignes_cache": _stat(LigneCache),
        "of_cache": _stat(OfCache),
        "cadence_reference": _stat(CadenceReference),
        "intervalle_minutes": settings.ODOO_SYNC_INTERVAL_MINUTES,
        "ecriture_odoo_activee": settings.ODOO_WRITEBACK_ENABLED,
    }


@router.post("/run-now")
def trigger_sync_now(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    """Déclenchement manuel -- même filet de sécurité que POST /scoring/snapshot/run-now
    tant que le scheduler périodique n'est pas activé (ODOO_SYNC_SCHEDULER_ENABLED)."""
    try:
        resultats = synchroniser_tout(db)
    except OdooSyncError as e:
        raise HTTPException(status_code=502, detail=f"Échec de la synchro Odoo : {e}")
    return {"message": "Synchro Odoo terminée.", "resultats": resultats}

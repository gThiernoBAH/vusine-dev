from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..core.models import User
from ..models.production import Alerte, LigneCache
from ..services.alertes_engine import executer_cycle_alertes
from .auth_routes import require_permission

router = APIRouter(prefix="/alertes", tags=["alertes"])


# Défini ici plutôt que dans schemas/ (jamais vu la structure de ce dossier pour les
# alertes -- fichier autonome, à déplacer dans schemas/admin.py ou schemas/alertes.py
# si vous préférez centraliser).
class AlerteOut(BaseModel):
    id: int
    type: str
    ligne_code: Optional[str] = None
    message: str
    niveau: str
    created_at: datetime
    resolue: bool = False   # *** AJOUT 2026-09-25 *** : utile seulement en consultation par `jour` (cf. plus bas)

    class Config:
        from_attributes = True


class RunNowOut(BaseModel):
    alertes_creees: int


# Réutilise la permission "view_vue_usine" (même public que Vue Usine/Rapports) --
# évite d'introduire une nouvelle clé de permission tant que auth_routes.py
# (PERMISSION_REGISTRY) n'a pas été relu ; à migrer vers une clé "view_alertes"
# dédiée si vous préférez une permission plus fine plus tard.

@router.get("", response_model=list[AlerteOut])
def list_alertes(
    jour: Optional[date] = Query(None, description="*** AJOUT 2026-09-25 *** : consulter les alertes CRÉÉES ce jour-là (résolues ou non), au lieu des alertes actives d'aujourd'hui. ATTENTION : il n'existe pas de date de résolution en base (`resolue` n'a pas de `resolue_at`) -- ceci montre ce qui a été déclenché ce jour-là, PAS une reconstitution fiable de ce qui était encore ouvert à une heure précise de ce jour-là."),
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("view_vue_usine")),
):
    """Sans `jour` : alertes actives (non résolues) d'aujourd'hui, les plus récentes
    d'abord -- écran Alertes, bouton 'Actualiser maintenant' à part (cf. run_alertes_now
    ci-dessous). Avec `jour` : alertes créées ce jour-là, résolues ou non (cf. avertissement
    ci-dessus sur les limites de cette vue historique)."""
    q = db.query(Alerte)
    q = q.filter(Alerte.created_at >= datetime.combine(jour, datetime.min.time()),
                 Alerte.created_at < datetime.combine(jour, datetime.max.time())) if jour else q.filter(Alerte.resolue.is_(False))
    alertes = q.order_by(Alerte.created_at.desc()).all()
    lignes_par_id = {
        l.id: l.code
        for l in db.query(LigneCache).filter(LigneCache.id.in_({a.ligne_id for a in alertes})).all()
    } if alertes else {}
    return [
        AlerteOut(
            id=a.id, type=a.type, ligne_code=lignes_par_id.get(a.ligne_id),
            message=a.message, niveau=a.niveau, created_at=a.created_at, resolue=a.resolue,
        )
        for a in alertes
    ]


@router.post("/run-now", response_model=RunNowOut)
def run_alertes_now(
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("view_vue_usine")),
):
    """Déclenchement manuel d'un cycle du moteur d'alertes (slide 13, plan de test #3)
    -- tant que le job planifié (cycle 5 min) reste désactivé par défaut, cf. recap."""
    nb = executer_cycle_alertes(db)
    return RunNowOut(alertes_creees=nb)
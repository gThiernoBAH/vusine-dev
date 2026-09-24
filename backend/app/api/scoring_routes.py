from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..core.models import User
from ..schemas.scoring import PersonnelScoreOut
from ..services.scoring_service import calculer_score_personnel
from ..services.snapshot_service import snapshoter_performance_du_jour
from .auth_routes import require_permission, require_admin

router = APIRouter(prefix="/scoring", tags=["scoring"])


@router.post("/snapshot/run-now")
def declencher_snapshot(db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    """Filet de sécurité manuel tant que SNAPSHOT_SCHEDULER_ENABLED=False (défaut) --
    même principe que POST /api/alerts/run-now côté SIVOX. À utiliser en fin de
    journée/poste, cf. avertissement dans snapshot_service.py."""
    nb = snapshoter_performance_du_jour(db)
    return {"message": f"Snapshot effectué pour {nb} ligne(s)."}


@router.get("/personnel", response_model=list[PersonnelScoreOut])
def list_scores_personnel(
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("view_scoring")),
):
    """Classement CDI/CDD (écran "Performance du personnel" du cockpit) -- les
    Journaliers n'apparaissent jamais ici, cf. schema.sql/scoring_service.py."""
    personnel = db.query(User).filter(User.categorie_personnel.in_(["CDI", "CDD"])).all()

    resultats = []
    for u in personnel:
        s = calculer_score_personnel(db, u)
        resultats.append(PersonnelScoreOut(
            user_id=u.id, nom=u.nom, matricule=u.matricule,
            categorie_personnel=u.categorie_personnel, **s,
        ))

    # Non-scorés (pas encore d'heures exploitables) en fin de liste, plutôt que mélangés
    # avec un score de 0% qui laisserait croire à une vraie contre-performance.
    resultats.sort(key=lambda r: (r.score_pct is None, -(r.score_pct or 0)))
    return resultats


@router.get("/personnel/{user_id}", response_model=PersonnelScoreOut)
def get_score_personnel(
    user_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission("view_scoring")),
):
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable.")
    if u.categorie_personnel not in ("CDI", "CDD"):
        raise HTTPException(status_code=422, detail="Pas de score pour un compte direction ou un journalier.")

    s = calculer_score_personnel(db, u)
    return PersonnelScoreOut(
        user_id=u.id, nom=u.nom, matricule=u.matricule,
        categorie_personnel=u.categorie_personnel, **s,
    )
